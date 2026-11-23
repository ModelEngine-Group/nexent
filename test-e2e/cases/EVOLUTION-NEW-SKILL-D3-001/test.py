# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI


@pytest.mark.case_id("EVOLUTION-NEW-SKILL-D3-001")
@pytest.mark.stage("D3")
@pytest.mark.asyncio
async def test_new_skill_over_agentos(tmp_path, monkeypatch):
    from contracts.agentos import EvaluationAgentResult, NewSkillTrial, PreparedEvaluationRun, RunInput
    from contracts.errors.exceptions import RuntimeUpstreamError
    from contracts.constants import environment
    from infrastructure import skill_package
    from infrastructure.agentos_client import AgentOSClient
    from infrastructure.rdb import skill_candidate_records
    from management.services.evaluation.replay_dialogue import run_turns
    from nexent.core.tools.read_skill_md_tool import ReadSkillMdTool
    from runtime.agentos import prepared_evaluation as runtime, prepared_skills
    from runtime.agentos.evaluation import create_evaluation_router
    from runtime.agentos.middleware import AgentOSMiddleware

    monkeypatch.setattr(environment, "JWT_SECRET", "trial-test-signing-key")
    monkeypatch.setattr(environment, "EVOLUTION_REPLAY_RUNTIME", True)
    stored = {"SKILL.md": b"---\nname: intake\ndescription: Intake\n---\nRecord the intake number."}
    digest = sha256(skill_package.encode_skill_package(stored)).hexdigest()

    def proposal(tenant, agent, version, cid):
        assert (tenant, agent, version, cid) == ("tenant", 7, 1, 8)
        return {"name": "intake", "description": "Intake", "digest": digest}

    monkeypatch.setattr(skill_candidate_records, "read_new_skill_trial", proposal)
    monkeypatch.setattr(skill_package, "load_new_skill_package", lambda *args: dict(stored))
    monkeypatch.setattr(
        prepared_skills, "skill_stage_path", lambda workspace_path, create: tmp_path / workspace_path
    )
    app = FastAPI(root_path="/api")
    app.add_middleware(AgentOSMiddleware)
    app.include_router(create_evaluation_router())
    client = AgentOSClient(
        "http://offline", lambda **kw: httpx.AsyncClient(transport=httpx.ASGITransport(app), **kw)
    )
    spec = PreparedEvaluationRun.model_validate(
        {
            "mode": "nexent",
            "resource": {
                "agent_id": 7,
                "version_no": 1,
                "name": "intake-agent",
                "description": "test",
                "model_alias": "local",
                "prompt_templates": {"system_prompt": "process"},
                "evaluation_options": {"context_items": []},
            },
            "models": {"llm": {"model_id": 1, "alias": "local", "revision": "1"}},
            "input": {"query": ""},
            "observe_root_skill_choices": True,
        }
    )

    async def materialize(payload, actor, prepare):
        key = uuid4().hex
        tools = {}
        resource = prepared_skills.mount_new_skill_trial(
            payload.resource, actor, key, tools, payload.new_skill_trial, "en"
        )
        items = [SimpleNamespace(**i) for i in resource.evaluation_options.context_items]
        return SimpleNamespace(
            observer=SimpleNamespace(),
            thread_future=None,
            attempt_outcome="completed",
            query=payload.input.query,
            workspace_path=key,
            agent_config=SimpleNamespace(
                tools=list(tools.values()), context_items=items, worker_agents=[], external_a2a_agents=[]
            ),
        )

    async def execute(info, *args):
        tools = info.agent_config.tools
        assert not tools or [t.name for t in tools] == ["read_skill_md"]
        if info.query == "intake" and tools:
            config = tools[0]
            guide = ReadSkillMdTool(**config.params, **config.metadata).forward("intake")
            assert "Record the intake number" in guide
        return EvaluationAgentResult(answer="done", events=[{"type": "final_answer", "content": "done"}])

    def release(info, *args):
        from shutil import rmtree

        directory = tmp_path / info.workspace_path
        if directory.exists():
            rmtree(directory)

    monkeypatch.setattr(runtime, "load_prepared_run", materialize)
    monkeypatch.setattr(runtime, "collect_observer_output", execute)
    monkeypatch.setattr(runtime.agent_run_manager, "register_agent_run", lambda *args: None)
    monkeypatch.setattr(runtime, "release_prepared_run", release)
    for arm, query, expected in (
        ("base", "intake", {}),
        ("result", "intake", {"intake": 1}),
        ("result", "time", {}),
    ):
        trial = NewSkillTrial(candidate_id=8, name="intake", digest=digest, arm=arm)
        run = spec.model_copy(update={"new_skill_trial": trial})
        obs, _, error = await run_turns(
            client,
            run,
            {"expected_skill_names": ["intake"] if query == "intake" else []},
            AsyncMock(return_value=RunInput(query=query)),
            {"receipt_id": uuid4().hex, "trial_id": 9},
            "editor",
            "tenant",
        )
        assert not error
        assert (
            obs[0].replay_receipt.root_guide_reads == expected
            and obs[0].replay_receipt.new_skill_trial == trial
        )
        assert not list(tmp_path.iterdir())
    stored["SKILL.md"] += b" changed"
    with pytest.raises(RuntimeUpstreamError) as mismatch:
        await run_turns(
            client,
            run,
            {"expected_skill_names": ["intake"]},
            AsyncMock(return_value=RunInput(query="intake")),
            {"receipt_id": uuid4().hex, "trial_id": 10},
            "editor",
            "tenant",
        )
    assert (
        mismatch.value.status_code == 409 and b"AGENTOS_NEW_SKILL_REVISION_MISMATCH" in mismatch.value.content
    )
    assert not list(tmp_path.iterdir())
