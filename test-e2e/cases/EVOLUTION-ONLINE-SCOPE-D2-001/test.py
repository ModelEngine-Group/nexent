# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from local_auth_http import bearer, native_runtime, register, runtime


@pytest.mark.case_id("EVOLUTION-ONLINE-SCOPE-D2-001")
@pytest.mark.stage("D2")
def test_online_scope_http(runtime):
    from backend.http.server.exception_handlers import register_exception_handlers
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.rdb.conversation_record import ConversationRecord
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.api.conversation.conversation_management import router as chats
    from management.api.evaluation.evolution import router as evaluation
    from management.thread_management import config_thread_manager
    from nexent.core.concurrency import clear_default_thread_manager, set_default_thread_manager

    identity, _, _, models = runtime
    load_system_configuration()
    actor = register(identity)
    owner = actor["user"]["id"]
    headers = bearer(actor["session"]["access_token"])
    migrations = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    models.TableBase.metadata.create_all(db_client.engine)
    with db_client.engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        for name in ("003_conversation_run_admission", "006_prepared_conversation_turn", "015_conversation_evolution",
                     "016_evolution_candidates", "017_evolution_skill_candidates", "018_evolution_replay_cases",
                     "019_evolution_experiments", "021_evolution_online_reviews", "022_evolution_suggestions",
                     "025_evolution_regression_cases"):
            cursor.execute((migrations / f"v2.9.0_{name}.sql").read_text(encoding="utf-8"))
    with get_db_session() as session:
        for cid, user in [(17,owner),(18,"other")]:
            session.add(ConversationRecord(conversation_id=cid,created_by=user,delete_flag="N"))
            session.execute(text("""INSERT INTO nexent.evolution_review_turn_t
                (tenant_id,owner_id,agent_id,agent_version_no,conversation_id,source_message_id,trajectory_id,
                 grant_epoch,valid_until,observation_state,observation) VALUES ('tenant-native',:user,7,1,:cid,
                 :cid,:uuid,0,now()+interval '1 day','observed','{"coverage":"complete"}')"""),
                dict(user=user,cid=cid,uuid=str(uuid4())))
        for agent,user in [(7,owner),(8,"other")]:
            for version in (0,1):
                session.add(models.AgentInfo(agent_id=agent,version_no=version,tenant_id="tenant-native",
                    name=f"scope-{agent}",created_by=user,updated_by=user,delete_flag="N",ingroup_permission="PRIVATE"))
                session.flush()
        for mid, v, status, expected in [(1,1,"submitted","target"),(2,1,"clarifying","draft"),(3,2,"submitted","other version")]:
            session.execute(text("""INSERT INTO nexent.evolution_suggestion_t (tenant_id,submitter_id,conversation_id,
                source_message_id,agent_id,version_no,skill_id,expected_behavior,status,last_message_id)
                VALUES ('tenant-native',:owner,17,:mid,7,:v,3,:expected,:status,:mid)"""),
                dict(owner=owner, mid=mid, v=v, expected=expected, status=status))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(chats, prefix="/api")
    app.include_router(evaluation, prefix="/api")
    config_thread_manager.start()
    set_default_thread_manager(config_thread_manager)
    try:
        def has_evidence(cid):
            with get_db_session() as session:
                return session.scalar(text("SELECT observation IS NOT NULL FROM nexent.evolution_review_turn_t WHERE conversation_id=:cid"), {"cid":cid})

        with TestClient(app) as client:
            path = "/api/conversation/17/evolution-setting"
            for enabled in (True, False):
                assert client.put(path, json={"enabled":enabled}, headers=headers).json()["data"]["enabled"] == enabled
            assert has_evidence(17)
            assert client.delete(path, headers=headers).json()["data"]["enabled"] is False
            assert not has_evidence(17)
            assert client.delete(path.replace("17","18"), headers=headers).status_code == 404 and has_evidence(18)
            workspace = "/api/agent-evolution/agents/7/versions/1/workspace"
            result = client.get(workspace, headers=headers)
            assert result.status_code == 200, result.text
            assert [s["expected_behavior"] for s in result.json()["data"]["suggestions"]] == ["target"]
            assert client.get(workspace.replace("agents/7","agents/8"),headers=headers).status_code == 403
    finally:
        clear_default_thread_manager(config_thread_manager)
        asyncio.run(config_thread_manager.shutdown(timeout=5))
