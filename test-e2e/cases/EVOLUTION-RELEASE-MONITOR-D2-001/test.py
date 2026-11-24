# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from local_auth_http import bearer, register, seed_membership_roles
from local_auth_http import native_runtime as native_runtime, runtime as runtime


@pytest.mark.case_id("EVOLUTION-RELEASE-MONITOR-D2-001")
@pytest.mark.stage("D2")
def test_release_monitoring(runtime):
    from backend.http.server.exception_handlers import register_exception_handlers
    from infrastructure.rdb.client import db_client
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.api.evaluation.evolution import router
    from management.thread_management import config_thread_manager
    from nexent.core.concurrency import clear_default_thread_manager, set_default_thread_manager

    identity, _, _, models = runtime
    load_system_configuration()
    login = register(identity)
    user = login["user"]["id"]
    headers = bearer(login["session"]["access_token"])
    seed_membership_roles(user, ["ADMIN"])
    models.TableBase.metadata.create_all(db_client.engine)
    migrations = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    with db_client.engine.begin() as conn, conn.connection.driver_connection.cursor() as cur:
        for file in (
            "v2.9.0_003_conversation_run_admission.sql",
            "v2.9.0_004_agent_execution.sql",
            "v2.9.0_006_prepared_conversation_turn.sql",
            "v2.9.0_011_trajectory.sql",
            "v2.9.0_015_conversation_evolution.sql",
            "v2.9.0_018_evolution_replay_cases.sql",
            "v2.9.0_019_evolution_experiments.sql",
            "v2.9.0_021_evolution_online_reviews.sql",
            "v2.9.0_022_evolution_suggestions.sql",
            "v2.9.0_028_evolution_confirmation_suites.sql",
            "v2.9.0_029_evolution_confirmation_locks.sql",
            "v2.9.0_030_evolution_confirmation_results.sql",
            "v2.9.0_031_evolution_session_versions.sql",
            "v2.9.0_032_evolution_releases.sql",
            "v2.9.0_040_evolution_release_monitoring.sql",
        ):
            cur.execute((migrations / file).read_text(encoding="utf8"))
    tenant = "tenant-native"
    with db_client.engine.begin() as conn:

        def sql(stmt, **params):
            return conn.execute(text(stmt), dict(t=tenant, u=user, **params))

        eid = sql("""INSERT INTO nexent.evolution_experiment_t(tenant_id,created_by,agent_id,version_no,request_id,request_digest,plan)
            VALUES (:t,:u,7,1,'one','a','{}') RETURNING experiment_id""").scalar_one()
        sid = sql("""INSERT INTO nexent.evolution_confirmation_suite_t(tenant_id,agent_id,version_no,digest,manifest,created_by)
            VALUES (:t,7,1,'a','{}',:u) RETURNING suite_id""").scalar_one()
        sql(
            """INSERT INTO nexent.evolution_confirmation_candidate_t(experiment_id,digest,recipe,submitted_by)
               VALUES (:e,'a','{}',:u)""",
            e=eid,
        )
        lock = sql(
            """INSERT INTO nexent.evolution_confirmation_lock_t(suite_id,experiment_id,digest,policy,locked_by)
                    VALUES (:s,:e,'a','{}',:u) RETURNING lock_id""",
            s=sid,
            e=eid,
        ).scalar_one()
        sql(
            """INSERT INTO nexent.evolution_confirmation_result_t(lock_id,lock_digest,decision,summary) VALUES (:l,'a','passed','{}')""",
            l=lock,
        )
        sql(
            """INSERT INTO nexent.evolution_release_scope_t(tenant_id,agent_id,initial_version) VALUES (:t,7,1)"""
        )
        sql(
            """INSERT INTO nexent.evolution_release_t(lock_id,tenant_id,agent_id,base_version,new_version,candidate_digest,
            baseline_digest,published_by,reason,published_at,rollback_at) VALUES (:l,:t,7,1,2,'a','b',:u,'verified',now()-interval '10 days',now())""",
            l=lock,
        )
        for act in ("publish", "rollback"):
            sql(
                """INSERT INTO nexent.evolution_release_event_t(lock_id,action,actor,reason,created_at) VALUES
                (:l,:act,:u,:act,CASE WHEN :act='publish' THEN now()-interval '10 days' ELSE now() END)""",
                l=lock,
                act=act,
            )
        for cid, version in [(61, 1), (62, 2)]:
            sql(
                """INSERT INTO nexent.conversation_record_t(conversation_id,created_by,delete_flag) VALUES (:cid,:u,'N')""",
                cid=cid,
            )
            sql(
                """INSERT INTO nexent.evolution_session_version_t VALUES (:t,7,:cid,:v,:u)""",
                cid=cid,
                v=version,
            )

        def run(
            cid, version, status="completed", source="CHAT", days=0, trace=False, review=False, duplicate=False
        ):
            rid = uuid4().hex
            msg = sql(
                """INSERT INTO nexent.conversation_message_t(message_id,conversation_id,message_role,message_source,message_content,created_by,delete_flag)
                VALUES (nextval('nexent.conversation_message_t_message_id_seq'),:cid,'assistant',:source,'PRIVATE BODY',:u,'N') RETURNING message_id""",
                cid=cid,
                source=source,
            ).scalar_one()
            sql(
                """INSERT INTO nexent.agent_execution_t(run_id,conversation_id,tenant_id,resource_versions,status,created_by,updated_by,delete_flag,create_time)
                VALUES (:r,:cid,:t,CAST(:receipt AS jsonb),:status,:u,:u,'N',now()- :days * interval '1 day')""",
                r=rid,
                cid=cid,
                status=status,
                days=days,
                receipt=json.dumps({"agent_id": 7, "model_revision": "trusted", "agent_version_no": version}),
            )
            for _ in range(2 if duplicate else 1):
                sql(
                    """INSERT INTO nexent.conversation_run_admission_t(scope_sha256,tenant_id,run_id,request_sha256,conversation_id,
                    prepared_assistant_id,created_by,updated_by,delete_flag,evolution_source_message_id,evolution_valid_until,evolution_grant_epoch)
                    VALUES (:s,:t,:r,'a',:cid,:m,:u,:u,'N',:m,now()+interval '1 hour',0)""",
                    s=uuid4().hex,
                    r=rid,
                    cid=cid,
                    m=msg,
                )
            if trace:
                tid = str(uuid4())
                sql(
                    """INSERT INTO nexent.trajectory_execution_t(trajectory_id,conversation_id,turn_no,agent_id,agent_version_no,
                    agentos_run_id,status,duration_ms,total_tokens,created_by,updated_by,delete_flag)
                    VALUES (:tid,:cid,1,7,:v,:r,'error',110,0,:u,:u,'N')""",
                    tid=tid,
                    cid=cid,
                    v=version,
                    r=rid,
                )
                if review:
                    sql(
                        """INSERT INTO nexent.evolution_review_turn_t(tenant_id,agent_id,agent_version_no,conversation_id,source_message_id,
                        trajectory_id,grant_epoch,valid_until,owner_id,run_id,observation_state,observation)
                        VALUES (:t,7,:v,:cid,:m,:tid,0,now()+interval '1 hour',:u,:r,'observed',CAST(:facts AS jsonb))""",
                        v=version,
                        cid=cid,
                        m=msg,
                        tid=tid,
                        r=rid,
                        facts=json.dumps(
                            {
                                "coverage": "complete",
                                "signals": ["tool_error", "user_correction"],
                                "private": "PRIVATE SIGNAL",
                            }
                        ),
                    )

        run(61, 1)
        run(62, 2, status="failed", trace=True, review=True)
        run(62, 2, status="stopped")
        run(62, 1)
        run(62, 9)
        run(62, 2, days=8)
        run(62, 2, source="AUTOMATION")
        run(62, 2, duplicate=True)

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api")
    config_thread_manager.start()
    set_default_thread_manager(config_thread_manager)
    try:
        with TestClient(app) as client:
            url = f"/api/agent-evolution/confirmation-locks/{lock}/release/monitoring"
            assert client.get(url, headers=headers).status_code == 403
            with db_client.engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO nexent.evolution_publisher_t VALUES (:t,7,:u,true,:u)"),
                    dict(t=tenant, u=user),
                )
            response = client.get(url, headers=headers)
            assert response.is_success, response.text
            report = response.json()["data"]
            base, new = report["versions"]
            assert (
                base["version_no"],
                base["sessions"],
                base["executions"],
                base["p90_ms"],
                base["mean_tokens"],
            ) == (1, 2, 2, None, None)
            assert base["binding_mismatches"] == 1
            assert (
                new["version_no"],
                new["sessions"],
                new["executions"],
                new["failed"],
                new["stopped"],
                new["unverified"],
            ) == (2, 1, 2, 1, 1, 1)
            assert (new["metered"], new["mean_tokens"], new["timed"], new["p90_ms"]) == (1, 0, 1, 110)
            assert (new["reviewed"], new["tool_errors"], new["corrected"]) == (1, 1, 1)
            assert [e["action"] for e in report["events"]] == ["publish", "rollback"]
            assert "PRIVATE" not in response.text and "conversation_id" not in response.text
            with db_client.engine.begin() as conn:
                conn.execute(
                    text("UPDATE nexent.trajectory_execution_t SET status='expired' WHERE conversation_id=62")
                )
            expired = client.get(url, headers=headers).json()["data"]["versions"][1]
            assert (
                expired["reviewed"] == expired["timed"] == expired["metered"] == 0
                and expired["executions"] == 2
            )
            with db_client.engine.begin() as conn:
                conn.execute(
                    text("UPDATE nexent.trajectory_execution_t SET status='error' WHERE conversation_id=62")
                )
            with db_client.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE nexent.conversation_record_t SET evolution_grant_epoch=1 WHERE conversation_id=62"
                    )
                )
            updated = client.get(url, headers=headers).json()["data"]["versions"][1]
            assert (
                updated["reviewed"] == updated["tool_errors"] == updated["corrected"] == 0
                and updated["executions"] == 2
            )
    finally:
        clear_default_thread_manager(config_thread_manager)
        asyncio.run(config_thread_manager.shutdown(timeout=5))
