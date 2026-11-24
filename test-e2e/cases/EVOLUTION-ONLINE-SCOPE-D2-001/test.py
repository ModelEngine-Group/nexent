# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from local_auth_http import bearer, native_runtime, register, runtime, seed_membership_roles


@pytest.mark.case_id("EVOLUTION-ONLINE-SCOPE-D2-001")
@pytest.mark.stage("D2")
def test_online_scope_http(runtime):
    from backend.http.server.exception_handlers import register_exception_handlers
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.rdb.conversation_record import ConversationRecord
    from infrastructure.rdb.skill_execution_records import SkillInfo, SkillInstance
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.api.conversation.conversation_management import router as chats
    from management.api.evaluation.evolution import router as evaluation
    from management.db.conversation.suggestions import record_intent
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
                     "025_evolution_regression_cases", "028_evolution_confirmation_suites", "020_evolution_feedback_handoff",
                     "034_evolution_new_skill_candidates", "039_evolution_tool_builds", "041_evolution_generation_attempts",
                     "043_evolution_model_charges", "046_evolution_online_diagnosis",
                     "035_evolution_release_guides", "049_evolution_review_workspace_indexes",
                     "050_evolution_scoped_skill_suggestions", "051_evolution_scoped_skill_candidates"):
            cursor.execute((migrations / f"v2.9.0_{name}.sql").read_text(encoding="utf-8"))
    with get_db_session() as session:
        session.add(models.UserTenant(user_id="other", tenant_id="tenant-native", user_role="USER", delete_flag="N"))
        batches = session.execute(text("""INSERT INTO nexent.evolution_review_batch_t
            (tenant_id,agent_id,agent_version_no,status,result) VALUES
            ('tenant-native',7,1,'completed',jsonb_build_object('private_stale_summary',true)),
            ('tenant-native',7,1,'pending',NULL),
            ('tenant-native',7,2,'completed',jsonb_build_object('private_other_version',true)) RETURNING batch_id""")).scalars().all()
        finished_batch, pending_batch, other_version_batch = batches
        for cid in range(17, 24):
            user = owner if cid == 17 else "other"
            args = dict(user=user,cid=cid,uuid=str(uuid4()),run=uuid4().hex,
                        version=2 if cid == 23 else 1,
                        batch={22: pending_batch, 23: other_version_batch}.get(cid, finished_batch))
            session.add(ConversationRecord(conversation_id=cid,created_by=user,delete_flag="N"))
            session.execute(text("""INSERT INTO nexent.evolution_review_turn_t
                (tenant_id,owner_id,agent_id,agent_version_no,conversation_id,source_message_id,trajectory_id,run_id,
                 grant_epoch,valid_until,batch_id,observation_state,observation,diagnosis) VALUES ('tenant-native',:user,7,:version,:cid,
                 :cid,:uuid,:run,0,now()+interval '1 day',:batch,
                 CASE WHEN :cid=22 THEN 'reading' WHEN :cid=21 THEN 'missing' ELSE 'observed' END,
                 CASE WHEN :cid=22 THEN NULL WHEN :cid=21 THEN '{"coverage":"partial","signals":[]}'::jsonb
                   WHEN :cid IN (19,20) THEN '{"coverage":"complete","signals":[],"successful_tool_steps":["read_ticket"],
                       "case_outline":{"tool_count": 1,"tools":[]}}'::jsonb
                   ELSE '{"coverage":"complete","signals":["tool_error"],"case_outline":{"tool_count": 1,"tools":[]}}'::jsonb END,
                 CASE WHEN :cid=22 THEN NULL WHEN :cid=21 THEN '{"status":"needs_evidence","reason":"incomplete_trace"}'::jsonb
                   WHEN :cid IN (19,20) THEN '{"status":"no_issue","reason":"no_signal"}'::jsonb
                   ELSE '{"status":"needs_review","direction":"tool","reason":"tool_failure"}'::jsonb END)"""), args)
            session.execute(text("""INSERT INTO nexent.conversation_run_admission_t (scope_sha256,tenant_id,run_id,
                request_sha256,conversation_id,created_by,updated_by,evolution_source_message_id,
                evolution_grant_epoch,evolution_valid_until,delete_flag)
                VALUES (:run,'tenant-native',:run,:run,:cid,:user,:user,:cid,0,now()+interval '1 day','N')"""), args)
            session.execute(text("""INSERT INTO nexent.trajectory_execution_t (trajectory_id,conversation_id,turn_no,
                agent_id,agentos_run_id,agent_version_no,status,created_by,updated_by,delete_flag)
                VALUES (:uuid,:cid,1,7,:run,:version,'success',:user,:user,'N')"""), args)
            session.execute(text("""INSERT INTO nexent.conversation_message_t (message_id,conversation_id,message_role,
                message_content,minio_files,created_by,updated_by,delete_flag) VALUES (:cid,:cid,'user',
                'private meeting text','[{"name":"private-notes.txt","object_name":"private/storage"}]',:user,:user,'N')"""), args)
        for agent,user in [(7,owner),(8,"other")]:
            for version in range(3 if agent == 7 else 2):
                session.add(models.AgentInfo(agent_id=agent,version_no=version,tenant_id="tenant-native",
                    name=f"scope-{agent}",created_by=user,updated_by=user,delete_flag="N",ingroup_permission="PRIVATE"))
                session.flush()
        for mid, v, status, expected in [(1,1,"submitted","target"),(2,1,"clarifying","draft"),(3,2,"submitted","other version")]:
            session.execute(text("""INSERT INTO nexent.evolution_suggestion_t (tenant_id,submitter_id,conversation_id,
                source_message_id,agent_id,version_no,skill_id,expected_behavior,status,last_message_id)
                VALUES ('tenant-native',:owner,17,:mid,7,:v,3,:expected,:status,:mid)"""),
                dict(owner=owner, mid=mid, v=v, expected=expected, status=status))
        session.execute(text("""INSERT INTO nexent.evolution_release_guide_t
            (tenant_id,agent_id,version_no,name,candidate_id,digest) VALUES
            ('tenant-native',7,2,'meeting-guide',29,repeat('a',64)),
            ('tenant-native',8,2,'other-guide',30,repeat('b',64)),
            ('another-tenant',7,2,'tenant-guide',31,repeat('c',64))"""))
        turn = SimpleNamespace(tenant_id="tenant-native", user_id=owner, reference=SimpleNamespace(conversation_id=17))
        query = "以后这个 Skill 要保留没有负责人的待办。"
        scope = {"agent":7, "version":2, "language":"zh", "instances":[], "released_guide_ids":[29,30,31]}
        receipt = record_intent(session, turn, 17, {"query":query, "suggestion_scope":scope})
        assert "meeting-guide" in receipt["message"] and receipt["suggestion_id"] > 0
        old_scope = {**scope, "version":1}
        assert "没有你可提出改进建议" in record_intent(session, turn, 18, {"query":query, "suggestion_scope":old_scope})["message"]
        unbound_scope = {**scope, "released_guide_ids":[30,31]}
        assert "没有你可提出改进建议" in record_intent(session, turn, 19, {"query":query, "suggestion_scope":unbound_scope})["message"]
        session.add(SkillInfo(skill_id=3, skill_name="handovers", tenant_id="tenant-native", created_by="other",
                              updated_by="other", ingroup_permission="READ_ONLY", delete_flag="N"))
        session.add(SkillInstance(skill_instance_id=3, skill_id=3, tenant_id="tenant-native", agent_id=7,
                                  version_no=1, enabled=True, delete_flag="N"))
        suggestion = session.scalar(text("SELECT suggestion_id FROM nexent.evolution_suggestion_t WHERE source_message_id=1"))
        session.execute(text("""INSERT INTO nexent.conversation_message_t (message_id,conversation_id,message_role,
            message_content,created_by,updated_by,delete_flag) VALUES (24,17,'assistant','receipt',:owner,:owner,'N')"""), {"owner": owner})
        session.execute(text("""UPDATE nexent.conversation_run_admission_t SET prepared_assistant_id=24,
            evolution_reply=jsonb_build_object('suggestion_id',CAST(:suggestion AS bigint)) WHERE conversation_id=17"""),
            {"suggestion": suggestion})
        candidate = session.scalar(text("""INSERT INTO nexent.evolution_skill_candidate_t
            (tenant_id,skill_id,skill_name,base_digest,result_digest,created_by,feedback_digest,feedback)
            VALUES ('tenant-native',3,'handovers',repeat('a',64),repeat('b',64),'other',repeat('c',64),
                jsonb_build_object('method','S2','receipt_suggestion_id',CAST(:suggestion AS bigint),
                'edit',jsonb_build_object('old','old step','new','candidate step'))) RETURNING candidate_id"""), {"suggestion": suggestion})
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
            workspace = "/api/agent-evolution/agents/7/versions/1/workspace"
            receipt_path = "/api/agent-evolution/conversations/17/receipts/24"
            candidate_path = receipt_path + f"/skill-candidates/{candidate}"
            compare = client.get(receipt_path + "/actions", headers=headers)
            assert compare.status_code == 200 and "no-store" in compare.headers["Cache-Control"]
            assert compare.json()["data"] == {"compare": {"agent_id": 7, "version_no": 1,
                "suggestion_id": suggestion, "experiment_id": None, "candidate_id": candidate}}
            assert client.get(candidate_path, headers=headers).status_code == 403
            assert client.post(candidate_path, headers=headers, json={"replacement": "other step"}).status_code == 403
            assert client.get(candidate_path.replace("/receipts/24", "/receipts/17"), headers=headers).status_code == 404
            with get_db_session() as session:
                session.execute(text("UPDATE nexent.ag_tenant_agent_t SET created_by='other' WHERE agent_id=7 AND version_no=0"))
                session.execute(text("UPDATE nexent.ag_skill_info_t SET created_by=:owner WHERE skill_id=3"), {"owner": owner})
            assert client.get(receipt_path + "/actions", headers=headers).json()["data"] == {"edit": {"candidate_id": candidate}}
            editable = client.get(candidate_path, headers=headers)
            assert editable.status_code == 200 and "no-store" in editable.headers["Cache-Control"]
            assert editable.json()["data"] == {"skill_name": "handovers", "old": "old step", "new": "candidate step"}
            assert client.get(workspace, headers=headers).status_code == 403
            with get_db_session() as session:
                session.execute(text("UPDATE nexent.ag_skill_info_t SET created_by='other' WHERE skill_id=3"))
            assert client.get(receipt_path + "/actions", headers=headers).json()["data"] == {}
            assert client.get(candidate_path, headers=headers).status_code == 403
            with get_db_session() as session:
                session.execute(text("UPDATE nexent.ag_tenant_agent_t SET created_by=:owner WHERE agent_id=7 AND version_no=0"), {"owner": owner})

            def workbench(*, expired_turn=None):
                result = client.get(workspace, headers=headers)
                assert result.status_code == 200 and "no-store" in result.headers["Cache-Control"], result.text
                assert "private" not in result.text
                data = result.json()["data"]
                assert [s["expected_behavior"] for s in data["suggestions"]] == ["target"]
                assert [batch["batch_id"] for batch in data["review_batches"]] == [pending_batch, finished_batch]
                assert data["review_batches"][0] == {"batch_id": pending_batch, "state": "pending"}
                if expired_turn is not None:
                    [expired] = [row for row in data["reviews"] if row["turn_id"] == expired_turn]
                    assert expired["state"] == "missing" and expired["signals"] == []
                    assert expired["diagnosis"] == {"status": "needs_evidence", "reason": "trajectory_expired"}
                return data["review_batches"][1]

            completed = workbench()
            assert completed["state"] == "completed" and completed["reviewed"] == 5 and completed["missing"] == 1
            assert completed["findings"] == [{"direction": "tool", "reason": "tool_failure",
                                               "turn_ids": [turn_ids[18], turn_ids[17]]}]
            assert completed["reference_workflows"] == [{"tools": ["read_ticket"],
                                                           "turn_ids": [turn_ids[20], turn_ids[19]]}]
            assert {row["turn_id"] for row in completed["draft_turns"]} == {turn_ids[cid] for cid in (17,18,19,20)}
            assert client.get(workspace.replace("agents/7","agents/8"),headers=headers).status_code == 403
            second_version = client.get(workspace.replace("versions/1", "versions/2"), headers=headers)
            assert second_version.status_code == 200, second_version.text
            assert [row["batch_id"] for row in second_version.json()["data"]["review_batches"]] == [other_version_batch]
            [scoped] = [row for row in second_version.json()["data"]["suggestions"] if row["released_guide_candidate_id"]]
            assert scoped["released_guide_candidate_id"] == 29 and scoped["skill_id"] is None
            assert "没有负责人的待办" in scoped["expected_behavior"]
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
            file_rule = {"initial":{"actions.txt":"draft"}, "expected":{"actions.txt":"ready"}, "protected":[]}
            result = client.post(cases_path, headers=headers, json={**form, "file_state":file_rule})
            assert result.status_code == 200, result.text
            file_case = result.json()["data"]["case_id"]
            detail = client.get(f"/api/agent-evolution/agents/7/versions/1/development-cases/{file_case}", headers=headers)
            assert detail.json()["data"]["task"]["file_state"] == {**file_rule, "adapter":"text-files-v1"}
            invalid = client.post(cases_path, headers=headers, json={**form, "file_state":{**file_rule, "protected":["actions.txt"]}})
            assert invalid.status_code == 422
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
            with get_db_session() as session:
                session.execute(text("UPDATE nexent.trajectory_execution_t SET status='expired' WHERE conversation_id=19"))
            current = workbench(expired_turn=turn_ids[19])
            assert current["findings"][0]["turn_ids"] == [turn_ids[18]] and current["excluded"] == 1
            assert current["reviewed"] == 4 and current["missing"] == 2 and current["reference_workflows"] == []
            assert {row["turn_id"] for row in current["draft_turns"]} == {turn_ids[18], turn_ids[20]}
            assert client.get(base + str(turn_ids[19]) + "/case-draft", headers=headers).status_code == 404

            # A migrated user is now an administrator of a different tenant.
            with get_db_session() as session:
                session.execute(text("UPDATE nexent.user_tenant_t SET tenant_id='tenant-outside' WHERE user_id=:owner"), {"owner": owner})
            seed_membership_roles(owner, ["ADMIN"])
            signed = identity.post("/api/user/signin", json={"email": actor["user"]["email"], "password": "Password123"})
            assert signed.status_code == 200
            foreign = bearer(signed.json()["data"]["session"]["access_token"])
            assert client.get(workspace, headers=foreign).status_code == 404
            denied = client.post("/api/agent-evolution/experiments", headers=foreign, json={
                "request_id": uuid4().hex, "agent_id": 7, "version_no": 1, "case_ids": [file_case],
                "candidate_type": "baseline", "evaluator_id": 1,
            })
            assert denied.status_code == 404 and "experiment_id" not in denied.text
            with get_db_session() as session:
                assert session.scalar(text("SELECT count(*) FROM nexent.evolution_experiment_t")) == 0
    finally:
        clear_default_thread_manager(config_thread_manager)
        asyncio.run(config_thread_manager.shutdown(timeout=5))
