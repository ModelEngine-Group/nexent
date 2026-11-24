# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import nullcontext
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from local_auth_http import native_runtime, register, runtime, seed_membership_roles


@pytest.mark.case_id("EVOLUTION-RELEASED-TOOL-REGRESSION-D3-001")
@pytest.mark.stage("D3")
@pytest.mark.asyncio
async def test_released_tool_regression(runtime, monkeypatch):
    from contracts.agentos import EvaluationAgentResult, PreparedEvaluationRun, ReplayReceipt, RunInput
    from contracts.constants import environment
    from contracts.evolution import DevelopmentExperimentRequest, ToolUseExpectation
    from infrastructure.agentos_client import AgentOSClient
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.db.evaluation.evaluator import create_evaluator, get_evaluator, publish_evaluator
    from management.services.evaluation.experiments import run_verified_arm
    from management.thread_management import config_thread_manager
    from nexent.core.concurrency import clear_default_thread_manager, set_default_thread_manager
    from runtime.agentos import prepared_evaluation
    from runtime.agentos.evaluation import create_evaluation_router
    from runtime.agentos.middleware import AgentOSMiddleware

    load_system_configuration()
    identity, _, _, models = runtime
    editor = register(identity)["user"]["id"]
    seed_membership_roles(editor, ["ADMIN"])
    tenant, agent, tool = "tenant-native", 91, "analyze_text_file"
    models.TableBase.metadata.create_all(db_client.engine)
    with db_client.engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        migrations = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
        cursor.execute((migrations / "v2.9.0_035_evolution_release_guides.sql").read_text(encoding="utf-8"))
    with get_db_session() as session:
        for version in (0, 1, 2):
            session.add(models.AgentInfo(tenant_id=tenant, agent_id=agent, version_no=version, name="tool-regression",
                                         created_by=editor, current_version_no=2 if version == 0 else None, delete_flag="N"))
            session.flush()
        session.execute(text("""INSERT INTO nexent.evolution_release_excluded_tool_t
            (tenant_id,agent_id,version_no,tool_name) VALUES (:t,:a,2,:tool)"""),
            {"t": tenant, "a": agent, "tool": tool})

    evaluator_id = create_evaluator(tenant, editor, "Tool version regression", "Exact answer", "code", None,
        code="def evaluate(query, expected, actual, runtime_events):\n    return {'score': int(expected == actual)}")["evaluator_id"]
    publish_evaluator(evaluator_id, tenant)
    rule = get_evaluator(evaluator_id, tenant)
    observation = None
    requests = []

    async def evaluate(payload, actor):
        assert (actor.user_id, actor.tenant_id) == (editor, tenant)
        assert payload.watch_tool_arguments == {tool: []}
        requests.append(payload.resource.version_no)
        return EvaluationAgentResult(answer="done", events=[{"type": "final_answer", "content": "done"}],
            replay_receipt=ReplayReceipt(trial_id=payload.replay_trial_id, outcome="completed", tool_observation=observation))

    monkeypatch.setattr(environment, "JWT_SECRET", "evolution-regression-transport-fixture-key")
    monkeypatch.setattr(prepared_evaluation, "execute_prepared_evaluation", evaluate)
    app = FastAPI(root_path="/api")
    app.add_middleware(AgentOSMiddleware)
    app.include_router(create_evaluation_router())
    client = AgentOSClient("http://runtime", lambda **kw: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kw))

    async def replay(version, minimum, *, complete=True, registered=()):
        nonlocal observation
        observation = {"registered": list(registered), "complete": complete, "calls": []}
        request = DevelopmentExperimentRequest(agent_id=agent, version_no=version, case_ids=[1], evaluator_id=evaluator_id,
                                               request_id=uuid4().hex, candidate_type="baseline")
        spec = PreparedEvaluationRun.model_validate({"mode": "nexent", "input": {"query": "regression"},
            "resource": {"agent_id": agent, "version_no": version, "name": "tool-regression", "description": "fixture",
                         "prompt_templates": {"system_prompt": "Answer"}},
            "models": {"llm": {"model_id": 11, "alias": "fixture", "revision": "1"}}})
        plan = {"snapshots": {"base": "frozen"}, "evaluator": rule, "regression_cases": {
            "1": {"scoring": {"evaluator": rule, "language": "en", "judge_model_id": None}}}}
        job = {"tenant_id": tenant, "created_by": editor, "case_id": 1, "variant": "base",
               "trial_id": 1, "receipt_id": uuid4().hex, "plan": plan}
        task = {"query": "regression", "expected": "done", "tool_use": ToolUseExpectation(
            rules=[{"name": tool, "min_calls": minimum, "max_calls": minimum}]).model_dump()}
        status, report = await run_verified_arm(request, job, {"digest": "case", "task": task}, spec, client,
                                                lambda _: nullcontext(RunInput(query="regression")))
        assert report["judgment"]["status"] == "pass"
        return status, report["tool_use"]

    config_thread_manager.start()
    set_default_thread_manager(config_thread_manager)
    try:
        status, grade = await replay(2, 0)
        assert status == "pass" and grade["sequence"] == []
        status, grade = await replay(2, 1)
        assert status == "fail" and grade["issues"] == [{"tool": tool, "reason": "too_few", "count": 0}]
        for version, options in ((1, {}), (2, {"complete": False}), (2, {"registered": [tool]})):
            assert (await replay(version, 0, **options))[0] == "missing_evidence"
        assert requests == [2, 2, 1, 2, 2]
    finally:
        clear_default_thread_manager(config_thread_manager)
        await config_thread_manager.shutdown(timeout=5)
