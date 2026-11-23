# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from local_auth_http import bearer, native_runtime, register, runtime


@pytest.mark.case_id("EVAL-CALIBRATION-D2-001")
@pytest.mark.stage("D2")
def test_calibration_http(runtime):
    from backend.http.server.exception_handlers import register_exception_handlers
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.api.evaluation.agent_evaluation import router
    from management.db.agent.repository import create_agent
    from management.db.evaluation.evaluator import create_evaluator, publish_evaluator
    from management.services.evaluation.scoring import validate_code_evaluator
    from management.thread_management import config_thread_manager
    from nexent.core.concurrency import clear_default_thread_manager, set_default_thread_manager

    identity_client, _, _, models = runtime
    load_system_configuration()
    data = register(identity_client)
    owner = data["user"]["id"]
    headers = bearer(data["session"]["access_token"])
    tenant = "tenant-native"
    models.TableBase.metadata.create_all(db_client.engine, tables=[
        model.__table__ for model in (models.AgentInfo, models.Evaluator, models.AgentEvaluation)
    ])
    agent = create_agent({"name": "calibration-target"}, tenant, owner)
    other = create_agent({"name": "private-to-another", "ingroup_permission": "PRIVATE"}, tenant, "other")
    code = "def evaluate(query, expected, actual, runtime_events):\n    return {'score': int(actual)}"
    validate_code_evaluator(code)
    eid = create_evaluator(tenant, owner, "Acceptance", "", "code", None, code=code)["evaluator_id"]
    publish_evaluator(eid, tenant)

    examples = [
        {"query": "check", "actual": value, "expected": expected, "human_verdict": label}
        for value, expected, label in [
            ("1", "x", "pass"), ("1", "x", "fail"), ("0", "x", "pass"),
            ("bad", "x", "fail"), ("0", None, "fail"),
        ]
    ]
    request = dict(agent_id=agent["agent_id"], evaluator_id=eid, required_evidence=["actual", "expected"],
                   examples=examples)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    register_exception_handlers(app)
    config_thread_manager.start()
    set_default_thread_manager(config_thread_manager)
    try:
        with TestClient(app) as client:
            path = "/api/agent-evaluations/calibrate"
            result = client.post(path, json=request, headers=headers)
            assert result.status_code == 200, result.text
            report = result.json()["data"]
            assert report["evaluator_version"] == 1 and report["judge_model_id"] is None
            assert report["counts"] == dict(agree=1, false_accept=1, false_reject=1, invalid=1, missing_evidence=1)
            assert [r["status"] for r in report["examples"]] == ["pass", "pass", "fail", "invalid", "missing_evidence"]
            assert report["examples"][2]["score"] == 0
            assert report["examples"][3]["score"] is None
            assert report["examples"][4]["missing"] == ["expected"]
            forbidden = client.post(path, json={**request, "agent_id": other["agent_id"]}, headers=headers)
            assert forbidden.status_code == 403
            assert "examples" not in forbidden.text
        with get_db_session() as session:
            assert session.query(models.AgentEvaluation).count() == 0
    finally:
        clear_default_thread_manager(config_thread_manager)
        asyncio.run(config_thread_manager.shutdown(timeout=5))
