# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from local_auth_http import bearer, native_runtime, register, runtime


@pytest.mark.stage("D2")
@pytest.mark.case_id("EVOLUTION-PROMPT-CONFLICT-D2-001")
def test_prompt_conflict_reads_only_approved_rules(runtime, monkeypatch):
    from backend.http.server.exception_handlers import register_exception_handlers
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.api.evaluation.evolution import router
    from management.services.evaluation import prompt_candidates
    from management.thread_management import config_thread_manager
    from nexent.core.concurrency import clear_default_thread_manager, set_default_thread_manager

    identity, _, _, models = runtime
    load_system_configuration()
    login = register(identity)
    editor, tenant = login["user"]["id"], "tenant-native"
    headers = bearer(login["session"]["access_token"])
    models.TableBase.metadata.create_all(db_client.engine)
    migration = Path(__file__).resolve().parents[3] / "deploy/sql/migrations/v2.9.0_016_evolution_candidates.sql"
    with db_client.engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        cursor.execute(migration.read_text(encoding="utf-8"))
    related = "Route billing issues to FIN."
    target = "All PORTAL tickets must go to OPS."
    outside = "Keep unrelated response format {format}."
    source = "\n".join((related, target, outside))
    with get_db_session() as session:
        for version in (0, 1):
            session.add(models.AgentInfo(agent_id=7, version_no=version, current_version_no=1,
                tenant_id=tenant, name="ticket pilot", prompt=source, created_by=editor, updated_by=editor,
                delete_flag="N", ingroup_permission="PRIVATE"))
            session.flush()

    reply = {"old": target, "new": related, "reason": "The billing rule already applies.",
             "evidence_ids": ["bad", "guard"]}
    inspected = []
    returned = []

    def generate(**kwargs):
        request = json.loads(kwargs["user_prompt"])
        inspected.append(request)
        assert request["source_passage"] == target and request["related_passage"] == related
        assert outside not in kwargs["user_prompt"]
        assert [request[key]["example_id"] for key in ("failure", "protection")] == ["bad", "guard"]
        return returned[-1]

    monkeypatch.setattr(prompt_candidates, "invoke_candidate_model", generate)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api")
    config_thread_manager.start()
    set_default_thread_manager(config_thread_manager)
    root = "/api/agent-evolution"
    route = root + "/prompt-candidates"
    payload = {"agent_id": 7, "version_no": 1, "model_id": 5, "method": "P3", "source_passage": target,
               "related_passage": related, "goal": "Keep billing in FIN",
               "failure": {"example_id": "bad", "expected": "FIN", "observed": "OPS"},
               "protection": {"example_id": "guard", "expected": "OPS", "observed": "OPS"}}
    try:
        with TestClient(app) as client:
            returned.append("```json\n" + json.dumps(reply) + "\n```")
            response = client.post(route, headers=headers, json=payload)
            assert response.status_code == 200, response.text
            candidate = response.json()["data"]
            assert candidate["edit"]["new"] == ""
            view = client.get(f"{root}/agents/7/versions/1/prompt-candidates/{candidate['candidate_id']}", headers=headers)
            assert view.is_success, view.text
            assert view.json()["data"]["source_text"] == source
            assert view.json()["data"]["result_text"] == source.replace(target, "", 1)

            for unavailable in ("This rule was never published.", "PORTAL tickets"):
                failed = client.post(route, headers=headers, json={**payload, "related_passage": unavailable})
                assert failed.status_code == 400 and "non-overlapping" in failed.text, failed.text
            assert len(inspected) == 1
            for invalid in (json.dumps({**reply, "old": related}), "Effects:\n" + returned[0]):
                returned.append(invalid)
                failed = client.post(route, headers=headers, json=payload)
                assert failed.status_code == 400, failed.text
            assert len(inspected) == 3
            with get_db_session() as session:
                assert session.scalar(text("SELECT count(*) FROM nexent.evolution_candidate_t")) == 1
                rows = session.execute(text("""SELECT current_version_no, prompt FROM nexent.ag_tenant_agent_t
                    WHERE tenant_id=:t AND agent_id=7 ORDER BY version_no"""), {"t": tenant}).all()
                assert rows == [(1, source), (1, source)]
    finally:
        clear_default_thread_manager(config_thread_manager)
        asyncio.run(config_thread_manager.shutdown(timeout=5))
