# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from local_auth_http import bearer, native_runtime, register, runtime


def _signup(identity, nickname, invite):
    response = identity.post("/api/user/signup", json={
        "email": f"{nickname}@example.com", "password": "Password345",
        "invite_code": invite, "auto_login": True,
    })
    assert response.status_code == 200, response.text
    return bearer(response.json()["data"]["session"]["access_token"])


@pytest.mark.case_id("EVOLUTION-PUBLIC-BENCHMARK-D2-001")
@pytest.mark.stage("D2")
def test_public_report_is_separate_from_business_nomination(runtime, monkeypatch):
    from backend.http.server.exception_handlers import register_exception_handlers
    from contracts.constants import environment
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.api.evaluation.evolution import router
    from management.db.evaluation import experiments as jobs
    from management.db.evaluation.candidates import store_prompt_candidate
    from management.db.evaluation.evaluator import create_evaluator, publish_evaluator
    from management.services.evaluation import experiments
    from management.thread_management import config_thread_manager
    from nexent.core.concurrency import clear_default_thread_manager, set_default_thread_manager

    identity, _, _, models = runtime
    load_system_configuration()
    login = register(identity)
    editor, tenant = login["user"]["id"], "tenant-native"
    headers = bearer(login["session"]["access_token"])
    migrations = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    with db_client.engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        for name in ("016_evolution_candidates", "018_evolution_replay_cases", "019_evolution_experiments",
                     "025_evolution_regression_cases", "026_evolution_combination", "028_evolution_confirmation_suites",
                     "029_evolution_confirmation_locks", "041_evolution_generation_attempts",
                     "043_evolution_model_charges", "044_evolution_evaluation_metering",
                     "047_evolution_development_recovery", "048_evolution_public_benchmarks"):
            cursor.execute((migrations / f"v2.9.0_{name}.sql").read_text(encoding="utf-8"))
    models.TableBase.metadata.create_all(db_client.engine)
    with get_db_session() as session:
        session.add(models.TenantInvitationCode(
            tenant_id="tenant-unrelated", invitation_code="FOREIGN-INVITE", group_ids="[]", capacity=1,
            expiry_date=datetime.utcnow() + timedelta(days=1), status="IN_USE", code_type="USER_INVITE",
            roles=["USER"], created_by="test", updated_by="test", delete_flag="N",
        ))
        for version in (0, 1):
            session.add(models.AgentInfo(agent_id=7, version_no=version, tenant_id=tenant, name="business",
                prompt="baseline", created_by=editor, updated_by=editor, delete_flag="N", ingroup_permission="PRIVATE"))
            session.flush()
    reader = _signup(identity, "reader", "NATIVE-INVITE")
    foreign = _signup(identity, "foreign", "FOREIGN-INVITE")

    rule = create_evaluator(tenant, editor, "Business correctness", "", "code", None,
        code="def evaluate(query, expected, actual, runtime_events):\n    return {'score': int(actual == expected)}")
    rule_id = rule["evaluator_id"]
    publish_evaluator(rule_id, tenant)
    candidates = [store_prompt_candidate(tenant, 7, 1, editor, "baseline", name, {"method": "P1"})
                  for name in ("failing candidate", "passing candidate")]
    monkeypatch.setattr(environment, "EVOLUTION_EVALUATION_METERING", "{}")
    monkeypatch.setattr(experiments, "EVOLUTION_REPLAY_RUNTIME_URL", "http://127.0.0.1:1")

    async def snapshot(request, scope, actor, arm):
        assert (scope, actor) == (tenant, editor)
        return SimpleNamespace(model_dump=lambda **_: {
            "models": {"llm": {"alias": "fixture"}}, "resource": {"model_alias": "fixture", "subagents": [],
                "prompt": "baseline" if arm == "base" else str(request.candidate_id)},
        })

    monkeypatch.setattr(experiments, "_snapshot", snapshot)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api")
    config_thread_manager.start()
    set_default_thread_manager(config_thread_manager)
    root = "/api/agent-evolution"
    try:
        with TestClient(app) as client:
            def add_case(query):
                receipt = client.post(root + "/development-cases", headers=headers, json={
                    "agent_id": 7, "version_no": 1, "family": "handoff", "query": query, "expected": "complete",
                })
                assert receipt.is_success, receipt.text
                return receipt.json()["data"]["case_id"]

            target, fixed = add_case("Check owner of new open action"), add_case("Report already assigned action")
            regression = client.post(f"{root}/agents/7/versions/1/development-cases/{fixed}/regression",
                                     headers=headers, json={"enabled": True, "evaluator_id": rule_id})
            assert regression.is_success, regression.text

            def run_comparison(key, candidate, fix_target):
                payload = {"request_id": key, "agent_id": 7, "version_no": 1, "case_ids": [target],
                           "candidate_type": "baseline", "evaluator_id": rule_id}
                if candidate is not None:
                    payload.update(candidate_type="prompt", candidate_id=candidate,
                                   screening={"target_case_ids": [target], "minimum": 1})
                receipt = client.post(root + "/experiments", headers=headers, json=payload)
                assert receipt.status_code == 202, receipt.text
                eid = receipt.json()["data"]["experiment_id"]
                plan = jobs.read_plan(tenant, eid)
                while trial := jobs.claim(eid):
                    variant, key = trial["variant"], str(trial["case_id"])
                    passed = key != str(target) or (fix_target and variant == "result")
                    evaluator = plan.get("regression_cases", {}).get(key, {}).get("scoring", {}).get("evaluator", plan["evaluator"])
                    status = "pass" if passed else "fail"
                    assert jobs.finish(trial, status, {"snapshot_digest": plan["snapshots"][variant],
                        "case_digest": plan["cases"][key], "evaluator_id": evaluator["evaluator_id"],
                        "evaluator_version": evaluator["version_no"], "judgment": {"status": status}})
                return eid, plan

            failed, plan = run_comparison("unchanged-target", candidates[0], False)
            passed, _ = run_comparison("fixed-target", candidates[1], True)
            baseline, _ = run_comparison("baseline", None, False)
            scope = f"{root}/experiments/{failed}"
            report_url = scope + "/public_benchmark_reports"
            payload = {"dataset": "Public instruction fixture", "revision": "v1", "subset": "format",
                       "scoring_protocol": "exact match v2", "adaptation": "none", "run_reference": "fixture-1",
                       "metric": "accuracy (%)", "sample_count": 30, "baseline_score": 40, "candidate_score": 90}
            before = client.get(scope, headers=headers).json()["data"]
            assert before["screening"]["status"] == "failed" and before["valid_pairs"] == 2
            barrier = Barrier(2)

            def upload(_):
                barrier.wait(timeout=5)
                return client.post(report_url, headers=headers, json=payload)

            with ThreadPoolExecutor(max_workers=2) as pool:
                uploads = list(pool.map(upload, range(2)))
            assert all(upload.is_success for upload in uploads), [upload.text for upload in uploads]
            first, second = [upload.json()["data"] for upload in uploads]
            assert first == second and first["experiment_id"] == failed
            assert first["base_snapshot_digest"] == plan["snapshots"]["base"]
            assert first["candidate_snapshot_digest"] == plan["snapshots"]["result"]
            assert all(first[key] == value for key, value in payload.items())
            third = client.post(report_url, headers=headers, json={**payload, "run_reference": "fixture-2"}).json()["data"]
            page = client.get(report_url, headers=headers, params={"limit": 1}).json()["data"]
            assert page == {"items": [third], "next_before": third["report_id"]}
            next_page = client.get(report_url, headers=headers, params={"before": page["next_before"]}).json()["data"]
            assert next_page == {"items": [first], "next_before": None}

            for forbidden in (reader, foreign):
                assert client.get(report_url, headers=forbidden).status_code in {403, 404}
                assert client.post(report_url, headers=forbidden, json=payload).status_code in {403, 404}
            assert client.post(report_url, headers=headers, json={**payload, "cases": []}).status_code == 422
            assert client.post(f"{root}/experiments/{baseline}/public_benchmark_reports",
                               headers=headers, json=payload).status_code == 400
            assert client.get(report_url, headers=headers).json()["data"] == {"items": [third, first], "next_before": None}
            assert client.get(scope, headers=headers).json()["data"] == before
            assert jobs.read_plan(tenant, failed) == plan

            denied = client.post(scope + "/confirmation-candidate", headers=headers)
            assert denied.status_code == 400 and "screening has not passed" in denied.text
            success_scope = f"{root}/experiments/{passed}"
            assert client.get(success_scope + "/public_benchmark_reports", headers=headers).json()["data"]["items"] == []
            nominated = client.post(success_scope + "/confirmation-candidate", headers=headers)
            assert nominated.is_success and nominated.json()["data"]["experiment_id"] == passed, nominated.text
            with get_db_session() as session:
                assert session.scalars(text("SELECT experiment_id FROM nexent.evolution_confirmation_candidate_t")).all() == [passed]
    finally:
        clear_default_thread_manager(config_thread_manager)
        asyncio.run(config_thread_manager.shutdown(timeout=5))
