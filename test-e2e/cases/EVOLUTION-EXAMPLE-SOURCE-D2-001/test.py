# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from local_auth_http import bearer, native_runtime, register, runtime


@pytest.mark.case_id("EVOLUTION-EXAMPLE-SOURCE-D2-001")
@pytest.mark.stage("D2")
def test_reject_same_source_before_trial_submission(runtime, monkeypatch):
    from backend.http.server.exception_handlers import register_exception_handlers
    from types import SimpleNamespace
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.api.evaluation.evolution import router
    from management.db.evaluation.candidates import store_prompt_candidate
    from management.db.evaluation.evaluator import create_evaluator, publish_evaluator
    from management.services.evaluation import experiments
    from management.db.evaluation import experiments as jobs
    from management.db.evaluation.replay_cases import contains_fixed_cases, save_replay_case
    from management.services.evaluation.replay_cases import freeze_regression_members
    from management.services.evaluation.example_candidates import example_source_keys
    from management.thread_management import config_thread_manager
    from nexent.core.concurrency import clear_default_thread_manager, set_default_thread_manager

    identity, _, _, models = runtime
    load_system_configuration()
    login = register(identity)
    user, tenant = login["user"]["id"], "tenant-native"
    headers = bearer(login["session"]["access_token"])
    models.TableBase.metadata.create_all(db_client.engine)
    migrations = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    with db_client.engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        for name in ("016_evolution_candidates", "018_evolution_replay_cases", "019_evolution_experiments",
                     "025_evolution_regression_cases", "026_evolution_combination"):
            cursor.execute((migrations / f"v2.9.0_{name}.sql").read_text(encoding="utf-8"))
    with get_db_session() as session:
        for version in (0, 1, 2):
            session.add(models.AgentInfo(agent_id=7, version_no=version, tenant_id=tenant, name="examples", prompt="base",
                created_by=user, updated_by=user, delete_flag="N", ingroup_permission="PRIVATE"))
            session.flush()
    eid = create_evaluator(tenant, user, "Acceptance", "", "code", None, code=(
        "def evaluate(query, expected, actual, runtime_events):\n    return {'score': int(actual == expected)}"))["evaluator_id"]
    publish_evaluator(eid, tenant)
    sources = example_source_keys(dict(query="List action items", source_group="minutes-51", attachments=[]))
    candidate = store_prompt_candidate(tenant, 7, 1, user, "base", "base with demonstration",
                                       {"method":"P2", "source_keys":sorted(sources)})
    monkeypatch.setattr(experiments, "EVOLUTION_REPLAY_RUNTIME_URL", "http://127.0.0.1:1")
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api")
    config_thread_manager.start()
    set_default_thread_manager(config_thread_manager)
    try:
        with TestClient(app) as client:
            root = "/api/agent-evolution"
            for i, (query, group) in enumerate([("list   ACTION items", None), ("A different wording", "MINUTES-51")]):
                response = client.post(root + "/development-cases", headers=headers, json={
                    "agent_id":7, "version_no":1, "family":"minutes", "query":query, "expected":"done", "source_group":group})
                assert response.status_code == 200, response.text
                case = response.json()["data"]["case_id"]
                response = client.post(root + "/experiments", headers=headers, json={
                    "request_id":f"check-{i}", "agent_id":7, "version_no":1, "case_ids":[case],
                    "candidate_type":"prompt", "candidate_id":candidate, "evaluator_id":eid})
                assert 400 <= response.status_code < 500 and "fresh materials" in response.text, response.text
            with get_db_session() as session:
                assert session.scalar(text("SELECT count(*) FROM nexent.evolution_experiment_t")) == 0
                assert session.scalar(text("SELECT count(*) FROM nexent.evolution_trial_t")) == 0

            path = f"{root}/agents/7/versions/1/development-cases/{case}/regression"
            assert client.post(path, headers=headers, json={"enabled": True, "evaluator_id":eid}).status_code == 200
            assert client.post(path, headers=headers, json={"enabled": True, "evaluator_id":eid}).status_code == 200
            with get_db_session() as session:
                assert session.scalar(text("SELECT count(*) FROM nexent.evolution_regression_case_t WHERE enabled")) == 1
            copied = freeze_regression_members(tenant, user, 7, 2)
            copied_id, = map(int, copied)
            assert copied_id != case and copied[str(copied_id)]["source_case_id"] == case
            frozen_rule = copied[str(copied_id)]["scoring"]["evaluator"]
            assert frozen_rule["evaluator_id"] == eid and frozen_rule["version_no"] > 0
            assert freeze_regression_members(tenant, user, 7, 2) == copied
            same_group = client.post(root + "/development-cases", headers=headers, json={
                "agent_id":7, "version_no":2, "family":"meeting", "query":"New question and grading target",
                "expected":"rows", "source_group":"minutes-51"}).json()["data"]
            assert contains_fixed_cases(tenant, 7, [same_group["case_id"]], [])
            assert not contains_fixed_cases("foreign", 7, [same_group["case_id"]], [])
            dialogue = client.post(root + "/development-cases", headers=headers, json={
                "agent_id":7, "version_no":2, "family":"meeting", "query":"A different wording",
                "followups":[{"query":"Continue"}], "expected":"rows"}).json()["data"]
            assert contains_fixed_cases(tenant, 7, [dialogue["case_id"]], [])
            fresh_dialogue = client.post(root + "/development-cases", headers=headers, json={
                "agent_id":7, "version_no":2, "family":"meeting", "query":"Read the quarterly plan",
                "followups":[{"query":"Continue"}], "expected":"rows"}).json()["data"]
            assert not contains_fixed_cases(tenant, 7, [fresh_dialogue["case_id"]], [dialogue["case_id"]])
            trace_cases = [save_replay_case(tenant, 7, 1, user, {
                "query": wording, "family":"meeting", "expected":"rows", "attachments":[],
                "trace_source":{"source_group":"same-authorized-chat"}})["case_id"]
                for wording in ("List decisions", "Report responsibilities")]
            assert contains_fixed_cases(tenant, 7, trace_cases[:1], trace_cases[1:])
            source_files = []
            for filename, question in (("original.txt","write the minutes"),("renamed.txt","amend the handoff")):
                res = client.post(root + "/development-cases", headers=headers, json={
                    "agent_id":7,"version_no":1,"family":"meeting","query":question,"expected":"ok",
                    "file_state":{"initial":{filename:"shared meeting notes"},"expected":{filename:"new notes"}}})
                assert res.is_success, res.text
                source_files.append(res.json()["data"]["case_id"])
            assert contains_fixed_cases(tenant, 7, source_files[:1], source_files[1:])
            unrelated = client.post(root + "/development-cases", headers=headers, json={
                "agent_id":7, "version_no":1, "family":"minutes", "query":"Different source", "expected":"done"}).json()["data"]
            response = client.post(root + "/experiments", headers=headers, json={
                "request_id":"auto-include", "agent_id":7, "version_no":1, "case_ids":[unrelated["case_id"]],
                "candidate_type":"prompt", "candidate_id":candidate, "evaluator_id":eid})
            assert 400 <= response.status_code < 500 and "fresh materials" in response.text, response.text
            candidate_v2 = store_prompt_candidate(tenant, 7, 2, user, "base", "revised", {"method":"P1"})
            submission = {"request_id":"frozen", "agent_id":7, "version_no":2,
                          "candidate_type":"prompt", "candidate_id":candidate_v2, "evaluator_id":eid}
            response = client.post(root + "/experiments", headers=headers, json={**submission, "case_ids":[same_group["case_id"]]})
            assert 400 <= response.status_code < 500 and "outside the fixed" in response.text, response.text
            fresh = client.post(root + "/development-cases", headers=headers, json={
                "agent_id":7, "version_no":2, "family":"meeting", "query":"A fresh task", "expected":"rows"}).json()["data"]

            async def fixed_snapshot(request, scope_tenant, scope_user, arm):
                return SimpleNamespace(model_dump=lambda **kw: {"models":{"llm":{"alias":"pilot"}},
                    "resource":{"model_alias":"pilot", "subagents":[], "prompt":"base" if arm == "base" else "revised"}})

            monkeypatch.setattr(experiments, "_snapshot", fixed_snapshot)
            response = client.post(root + "/experiments", headers=headers, json={**submission, "case_ids":[fresh["case_id"]]})
            assert response.status_code == 202, response.text
            source_experiment = response.json()["data"]["experiment_id"]
            plan = jobs.read_plan(tenant, source_experiment)
            assert plan["regression_cases"] == copied
            assert set(plan["cases"]) == {str(copied_id), str(fresh["case_id"])}
            assert client.post(path, headers=headers, json={"enabled":False}).status_code == 200
            assert freeze_regression_members(tenant, user, 7, 2) == {}
            response = client.post(root + f"/experiments/{source_experiment}/example-candidates", headers=headers, json={
                "target_case_id":same_group["case_id"], "target_behavior":"extract",
                "examples":[{"case_id":same_group["case_id"], "variant":"base", "behavior":"extract",
                             "input_excerpt":"New", "output_excerpt":"rows"}]})
            assert 400 <= response.status_code < 500 and "Fixed regression" in response.text, response.text
            with get_db_session() as session:
                assert session.scalar(text("SELECT count(*) FROM nexent.evolution_experiment_t")) == 1
            tool_submission = {**submission, "request_id": "tool-source", "case_ids": [fresh["case_id"]],
                               "candidate_type": "tool_set", "candidate_id": 19}
            response = client.post(root + "/experiments", headers=headers, json=tool_submission)
            assert response.status_code == 202, response.text
            tool_experiment = response.json()["data"]["experiment_id"]
            parts = [
                {"experiment_id": source_experiment, "candidate_id": candidate_v2, "candidate_type": "prompt"},
                {"experiment_id": tool_experiment, "candidate_id": 19, "candidate_type": "tool_set"},
            ]
            combined = {**submission, "request_id": "combination", "candidate_type": "combination", "candidate_id": None,
                        "components": parts, "case_ids": [fresh["case_id"]]}
            response = client.post(root + "/experiments", headers=headers, json=combined)
            assert 400 <= response.status_code < 500 and "graded pair" in response.text, response.text
            for single in (source_experiment, tool_experiment):
                frozen = jobs.read_plan(tenant, single)
                while trial := jobs.claim(single):
                    assert jobs.finish(trial, "pass", {"snapshot_digest": frozen["snapshots"][trial["variant"]],
                                                      "case_digest": frozen["cases"][str(trial["case_id"])]})
            forged = {**combined, "components": [parts[0], {**parts[1], "candidate_id": 20}]}
            response = client.post(root + "/experiments", headers=headers, json=forged)
            assert 400 <= response.status_code < 500 and "single experiments" in response.text, response.text
            response = client.post(root + "/experiments", headers=headers, json=combined)
            assert response.status_code == 202, response.text
            combo_id = response.json()["data"]["experiment_id"]
            retry = client.post(root + "/experiments", headers=headers, json=combined)
            assert retry.status_code == 202 and retry.json()["data"]["experiment_id"] == combo_id
            trial_rows = jobs.trials(tenant, combo_id)
            assert len(trial_rows) == 4
            assert {row["variant"] for row in trial_rows} == {"base", "only_a", "only_b", "result"}
            assert all(row["status"] == "pending" for row in trial_rows)
            cancelled = client.post(root + f"/experiments/{tool_experiment}/cancel", headers=headers)
            assert cancelled.is_success
            response = client.post(root + "/experiments", headers=headers, json={**combined, "request_id": "after-cancel"})
            assert 400 <= response.status_code < 500 and "single experiments" in response.text, response.text
            with get_db_session() as session:
                assert session.scalar(text("SELECT count(*) FROM nexent.evolution_experiment_t")) == 3
    finally:
        clear_default_thread_manager(config_thread_manager)
        asyncio.run(config_thread_manager.shutdown(timeout=5))
