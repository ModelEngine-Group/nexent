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
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.api.evaluation.evolution import router
    from management.db.evaluation.candidates import store_prompt_candidate
    from management.db.evaluation.evaluator import create_evaluator, publish_evaluator
    from management.services.evaluation import experiments
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
        for name in ("016_evolution_candidates", "018_evolution_replay_cases", "019_evolution_experiments"):
            cursor.execute((migrations / f"v2.9.0_{name}.sql").read_text(encoding="utf-8"))
    with get_db_session() as session:
        for version in (0, 1):
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
    finally:
        clear_default_thread_manager(config_thread_manager)
        asyncio.run(config_thread_manager.shutdown(timeout=5))
