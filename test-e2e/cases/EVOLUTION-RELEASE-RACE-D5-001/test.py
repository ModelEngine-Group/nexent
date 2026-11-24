# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from time import monotonic, sleep

import pytest
from sqlalchemy import text

from local_auth_http import native_runtime, register, runtime, seed_membership_roles


@pytest.mark.case_id("EVOLUTION-RELEASE-RACE-D5-001")
@pytest.mark.stage("D5")
def test_release_race_and_rollback_to_previous_version(runtime):
    from contracts.confirmation import CuratorGrant
    from contracts.errors.codes import ErrorCode
    from contracts.errors.exceptions import AppException
    from contracts.evolution_sources import task_digest
    from contracts.releases import RollbackRequest
    from infrastructure.rdb.agent_execution import OWNER_ID, RunIdentity, mark_running
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.db.agent.session_versions import confirm_chat_version, lock_release_scope, select_chat_version
    from management.db.evaluation import releases

    identity, _, _, models = runtime
    load_system_configuration()
    first = register(identity)["user"]["id"]
    seed_membership_roles(first, ["ADMIN"])
    login = identity.post("/api/user/signup", json={
        "email": "second-publisher@example.com", "password": "Password123",
        "invite_code": "NATIVE-INVITE", "auto_login": True,
    })
    assert login.status_code == 200
    second = login.json()["data"]["user"]["id"]
    models.TableBase.metadata.create_all(db_client.engine)
    migrations = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    with db_client.engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        for name in ("003_conversation_run_admission", "004_agent_execution", "006_prepared_conversation_turn",
                     "011_trajectory",
                     "015_conversation_evolution", "018_evolution_replay_cases", "019_evolution_experiments",
                     "028_evolution_confirmation_suites", "029_evolution_confirmation_locks",
                     "030_evolution_confirmation_results", "031_evolution_session_versions", "032_evolution_releases",
                     "033_evolution_release_tools", "035_evolution_release_guides", "036_evolution_skill_catalog_entry"):
            cursor.execute((migrations / f"v2.9.0_{name}.sql").read_text(encoding="utf-8"))

    tenant, agent = "tenant-native", 901
    with get_db_session() as session:
        for scope, owner_agent, version, prompt in (
            (tenant, agent, 0, "Draft remains editable"),
            (tenant, agent, 1, "Original published instructions"),
            (tenant, 902, 0, "Another business agent"),
            ("other-tenant", 903, 0, "Another tenant"),
        ):
            session.add(models.AgentInfo(tenant_id=scope, agent_id=owner_agent, version_no=version,
                                         name=f"pilot-{owner_agent}", current_version_no=1 if not version else None,
                                         prompt=prompt, created_by=first, delete_flag="N"))
            session.flush()
    for actor in (first, second):
        releases.set_publisher(tenant, agent, first, CuratorGrant(user_id=actor, enabled=True))

    def confirmed(base, proposed_prompt):
        plan = {"proposed_prompt": proposed_prompt}
        recipe = {"candidate_type": "prompt", "plan_digest": task_digest(plan)}
        digest, suite_digest = task_digest(recipe), task_digest([base, proposed_prompt])
        with db_client.engine.begin() as conn:
            eid = conn.scalar(text("""INSERT INTO nexent.evolution_experiment_t
                (tenant_id, created_by, agent_id, version_no, request_id, request_digest, plan)
                VALUES (:t,:u,:a,:b,:d,:d,CAST(:plan AS jsonb)) RETURNING experiment_id"""),
                dict(t=tenant, u=first, a=agent, b=base, d=digest, plan=json.dumps(plan)))
            suite = conn.scalar(text("""INSERT INTO nexent.evolution_confirmation_suite_t
                (tenant_id, agent_id, version_no, digest, manifest, created_by)
                VALUES (:t,:a,:b,:d,'{}',:u) RETURNING suite_id"""),
                dict(t=tenant, u=first, a=agent, b=base, d=suite_digest))
            conn.execute(text("""INSERT INTO nexent.evolution_confirmation_candidate_t
                (experiment_id, digest, recipe, submitted_by) VALUES (:e,:d,CAST(:recipe AS jsonb),:u)"""),
                dict(e=eid, d=digest, recipe=json.dumps(recipe), u=first))
            lock_digest = task_digest([tenant, suite, suite_digest, eid, digest, {}])
            lock = conn.scalar(text("""INSERT INTO nexent.evolution_confirmation_lock_t
                (suite_id, experiment_id, digest, policy, locked_by) VALUES (:s,:e,:d,'{}',:u) RETURNING lock_id"""),
                dict(s=suite, e=eid, d=lock_digest, u=first))
            conn.execute(text("""INSERT INTO nexent.evolution_confirmation_result_t
                (lock_id, lock_digest, decision, summary) VALUES (:l,:d,'passed','{}')"""), dict(l=lock, d=lock_digest))
        return lock, digest, proposed_prompt

    def publish(actor, candidate, base):
        lock, digest, prompt = candidate
        _, _, stamp = releases.prepare(tenant, actor, lock)
        try:
            return releases.publish(tenant, actor, lock, "race verification", base, digest, stamp, [], prompt,
                                    "baseline-receipt", [])
        except AppException as exc:
            return exc

    def race(actions):
        with ThreadPoolExecutor(max_workers=2) as pool:
            with db_client.engine.begin() as gate:
                lock_release_scope(gate, tenant, agent, exclusive=True)
                workers = [pool.submit(action) for action in actions]
                until = monotonic() + 10
                while monotonic() < until and not any(worker.done() for worker in workers):
                    waiting = gate.scalar(text("""SELECT count(*) FROM pg_locks held JOIN pg_locks pending
                        USING(locktype,database,classid,objid,objsubid)
                        WHERE held.pid=pg_backend_pid() AND held.locktype='advisory' AND NOT pending.granted"""))
                    if waiting == 2:
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Both release transactions must queue on the same PostgreSQL lock")
            return [worker.result(timeout=10) for worker in workers]

    def bind(conversation, expected):
        actual = select_chat_version(tenant, agent, conversation, first, 1)
        assert actual == expected
        with get_db_session() as session:
            assert confirm_chat_version(session, tenant, agent, conversation, first, 1, actual)

    candidates = [confirmed(1, "Published revision B1"), confirmed(1, "Published revision B2")]
    results = race([lambda: publish(first, candidates[0], 1), lambda: publish(second, candidates[1], 1)])
    (winner,) = (i for i, receipt in enumerate(results) if isinstance(receipt, dict))
    rejected = results[1 - winner]
    assert isinstance(rejected, AppException) and rejected.error_code == ErrorCode.COMMON_VALIDATION_ERROR
    assert "default version" in rejected.message
    winner_lock = candidates[winner][0]
    assert results[winner]["new_version"] == 2
    assert publish((first, second)[winner], candidates[winner], 1) == results[winner]
    bind(201, 2)

    next_candidate = confirmed(2, "Published revision C")
    next_lock = next_candidate[0]
    assert publish(first, next_candidate, 2)["new_version"] == 3
    bind(301, 3)
    request = RollbackRequest(expected_version=3, reason="concurrent rollback verification")
    restored = race([lambda: releases.restore(tenant, first, next_lock, request, True),
                     lambda: releases.restore(tenant, second, next_lock, request, True)])
    assert restored[0] == restored[1] and restored[0]["rollback_at"] and not restored[0]["new_sessions_paused"]
    bind(401, 2)
    assert [select_chat_version(tenant, agent, cid, first, 1) for cid in (201, 301, 401)] == [2, 3, 2]

    with db_client.engine.connect() as conn:
        events = conn.execute(text("SELECT lock_id, action FROM nexent.evolution_release_event_t ORDER BY lock_id, action")).all()
        assert events == [(winner_lock, "publish"), (next_lock, "publish"), (next_lock, "rollback")]
        actual = conn.execute(text("""SELECT agent_id,version_no,current_version_no,prompt
            FROM nexent.ag_tenant_agent_t ORDER BY agent_id,version_no""")).all()
        assert actual == [(901, 0, 2, "Draft remains editable"), (901, 1, None, "Original published instructions"),
                          (901, 2, None, candidates[winner][2]), (901, 3, None, "Published revision C"),
                          (902, 0, 1, "Another business agent"), (903, 0, 1, "Another tenant")]

    # Runtime can be preparing an execution when the publisher disables its version.
    written = {
        "a": (tenant, 301, "running", 3),
        "b": (tenant, 401, "running", 2),
        "c": (tenant, 301, "completed", 3),
        "d": ("other-tenant", 501, "running", 3),
        "e": (tenant, 302, "starting", None),
        "f": (tenant, 402, "starting", None),
    }
    with db_client.engine.begin() as conn:
        for name, (scope, conversation, status, version) in written.items():
            versions = {"agent_id": agent, "agent_version_no": version} if version else {}
            conn.execute(text("""INSERT INTO nexent.agent_execution_t
                (run_id,conversation_id,tenant_id,owner_id,lease_until,status,resource_versions,created_by,delete_flag)
                VALUES (:r,:c,:t,:o,now()+interval '1 minute',:s,CAST(:v AS jsonb),:u,'N')"""),
                dict(r=name * 32, c=conversation, t=scope, o=OWNER_ID, s=status, v=json.dumps(versions), u=first))
    stop = request.model_copy(update={"emergency": True})
    assert releases.restore(tenant, first, next_lock, stop, True)["disabled"]
    assert releases.restore(tenant, second, next_lock, stop, True)["disabled"]
    assert not mark_running(RunIdentity(tenant, first, 302, "e" * 32), {"agent_id": agent, "agent_version_no": 3})
    assert mark_running(RunIdentity(tenant, first, 402, "f" * 32), {"agent_id": agent, "agent_version_no": 2})
    with db_client.engine.connect() as conn:
        assert conn.execute(text("""SELECT left(run_id,1),status,cancellation_requested
            FROM nexent.agent_execution_t ORDER BY run_id""")).all() == [
                ("a", "running", True), ("b", "running", False), ("c", "completed", False),
                ("d", "running", False), ("e", "starting", False), ("f", "running", False),
            ]
        assert conn.scalar(text("""SELECT count(*) FROM nexent.evolution_release_event_t
            WHERE lock_id=:l AND action='stop'"""), {"l": next_lock}) == 1
