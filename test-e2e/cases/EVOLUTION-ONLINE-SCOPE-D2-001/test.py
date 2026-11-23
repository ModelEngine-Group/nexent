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
        for name in ("003_conversation_run_admission", "006_prepared_conversation_turn", "011_trajectory", "015_conversation_evolution",
                     "016_evolution_candidates", "017_evolution_skill_candidates", "018_evolution_replay_cases",
                     "019_evolution_experiments", "021_evolution_online_reviews", "022_evolution_suggestions",
                     "025_evolution_regression_cases"):
            cursor.execute((migrations / f"v2.9.0_{name}.sql").read_text(encoding="utf-8"))
    with get_db_session() as session:
        session.add(models.UserTenant(user_id="other", tenant_id="tenant-native", user_role="USER", delete_flag="N"))
        for cid, user in [(17,owner),(18,"other")]:
            args = dict(user=user,cid=cid,uuid=str(uuid4()),run=uuid4().hex)
            session.add(ConversationRecord(conversation_id=cid,created_by=user,delete_flag="N"))
            session.execute(text("""INSERT INTO nexent.evolution_review_turn_t
                (tenant_id,owner_id,agent_id,agent_version_no,conversation_id,source_message_id,trajectory_id,run_id,
                 grant_epoch,valid_until,observation_state,observation) VALUES ('tenant-native',:user,7,1,:cid,
                 :cid,:uuid,:run,0,now()+interval '1 day','observed',
                 '{"coverage":"complete","signals":[],"case_outline":{"tool_count": 1,"tools":[]}}')"""), args)
            session.execute(text("""INSERT INTO nexent.conversation_run_admission_t (scope_sha256,tenant_id,run_id,
                request_sha256,conversation_id,created_by,updated_by,evolution_source_message_id,
                evolution_grant_epoch,evolution_valid_until,delete_flag)
                VALUES (:run,'tenant-native',:run,:run,:cid,:user,:user,:cid,0,now()+interval '1 day','N')"""), args)
            session.execute(text("""INSERT INTO nexent.trajectory_execution_t (trajectory_id,conversation_id,turn_no,
                agent_id,agentos_run_id,agent_version_no,status,created_by,updated_by,delete_flag)
                VALUES (:uuid,:cid,1,7,:run,1,'success',:user,:user,'N')"""), args)
            session.execute(text("""INSERT INTO nexent.conversation_message_t (message_id,conversation_id,message_role,
                message_content,minio_files,created_by,updated_by,delete_flag) VALUES (:cid,:cid,'user',
                'private meeting text','[{"name":"private-notes.txt","object_name":"private/storage"}]',:user,:user,'N')"""), args)
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
            with get_db_session() as session:
                turn_ids = dict(session.execute(text("SELECT conversation_id,turn_id FROM nexent.evolution_review_turn_t")).all())
            base = "/api/agent-evolution/agents/7/versions/1/reviews/"
            draft_path = base + str(turn_ids[17]) + "/case-draft"
            own = client.get(draft_path, headers=headers)
            assert own.status_code == 200 and "no-store" in own.headers["Cache-Control"], own.text
            assert own.json()["data"]["attachment_names"] == ["private-notes.txt"]
            other = client.get(base + str(turn_ids[18]) + "/case-draft", headers=headers)
            assert other.status_code == 200 and other.json()["data"]["query"] is None, other.text
            assert other.json()["data"]["attachment_count"] == 1 and "private" not in other.text
            assert client.get(draft_path.replace("agents/7","agents/8"), headers=headers).status_code == 403
            form = {"agent_id":7,"version_no":1,"family":"minutes","query":"public task","expected":"one row",
                    "trace":{"turn_id":turn_ids[17],"draft_digest":own.json()["data"]["draft_digest"],
                             "purpose":"protect","inputs_reviewed":True}}
            cases_path = "/api/agent-evolution/development-cases"
            res = client.post(cases_path, headers=headers, json=form)
            assert 400 <= res.status_code < 500 and "attachments" in res.text
            form["trace"]["unused_attachment_slots"] = [1]
            res = client.post(cases_path, headers=headers, json=form)
            assert 400 <= res.status_code < 500 and "starting state" in res.text
            form["trace"]["tools_require_no_reset"] = True
            assert client.post(cases_path, headers=headers, json=form).status_code == 200
            for enabled in (True, False):
                assert client.put(path, json={"enabled":enabled}, headers=headers).json()["data"]["enabled"] == enabled
            assert has_evidence(17)
            assert client.delete(path, headers=headers).json()["data"]["enabled"] is False
            assert not has_evidence(17)
            assert client.get(draft_path, headers=headers).status_code == 404
            assert client.post(cases_path, headers=headers, json=form).status_code == 404
            assert client.delete(path.replace("17","18"), headers=headers).status_code == 404 and has_evidence(18)
            workspace = "/api/agent-evolution/agents/7/versions/1/workspace"
            result = client.get(workspace, headers=headers)
            assert result.status_code == 200, result.text
            assert [s["expected_behavior"] for s in result.json()["data"]["suggestions"]] == ["target"]
            assert client.get(workspace.replace("agents/7","agents/8"),headers=headers).status_code == 403
    finally:
        clear_default_thread_manager(config_thread_manager)
        asyncio.run(config_thread_manager.shutdown(timeout=5))
