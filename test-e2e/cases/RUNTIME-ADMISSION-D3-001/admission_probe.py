# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Inspect case-owned conversations and hold bounded history persistence gates."""

import json
import sys
from time import monotonic, sleep
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from uuid import UUID, uuid5

from sqlalchemy import select, text

from contracts.constants.environment import POSTGRES_HOST, RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS, RUNTIME_STATE_REDIS_URL
from gateway.identity.downstream import IDENTITY_HEADER, sign_identity
from infrastructure.rdb.agent_execution import AgentExecution, RunIdentity, finish_execution
from infrastructure.rdb.client import get_db_session
from infrastructure.redis.agent_events import RunJournal
from infrastructure.redis.run_state import runtime_state_service
from infrastructure.rdb.conversation_record import ConversationMessage, ConversationRecord


POSTGRES_HOSTS = {"nexent-postgresql", "nexent-postgresql.nexent", "nexent-postgresql.nexent.svc",
                  "nexent-postgresql.nexent.svc.cluster.local"}
REDIS_HOSTS = {"nexent-redis", "nexent-redis.nexent", "nexent-redis.nexent.svc", "nexent-redis.nexent.svc.cluster.local"}
HISTORY_WAITERS = text("""
    SELECT DISTINCT waiting.pid
    FROM pg_locks AS waiting JOIN pg_locks AS history ON history.pid = waiting.pid
    WHERE NOT waiting.granted AND pg_backend_pid() = ANY(pg_blocking_pids(waiting.pid))
      AND history.locktype = 'relation' AND history.granted AND history.mode = :relation_lock
      AND history.relation = to_regclass(:conversation_table)
""")


def read_batch(token, conversation_ids, *, role="owner"):
    if role not in {"owner", "foreign"}:
        raise ValueError("Unknown admission fixture identity")
    owner = str(uuid5(token, f"{role}:user"))
    tenant = str(uuid5(token, f"{role}:tenant"))
    states = {}
    with get_db_session() as session:
        for identifier in conversation_ids:
            session.execute(select(ConversationRecord.conversation_id).where(
                ConversationRecord.conversation_id == identifier,
                ConversationRecord.created_by == owner,
                ConversationRecord.delete_flag == "N",
            )).scalar_one()
            executions = session.scalars(select(AgentExecution).where(
                AgentExecution.tenant_id == tenant,
                AgentExecution.created_by == owner,
                AgentExecution.conversation_id == identifier,
                AgentExecution.delete_flag == "N",
            ).order_by(AgentExecution.create_time, AgentExecution.run_id)).all()
            messages = session.execute(select(ConversationMessage.message_content).where(
                ConversationMessage.conversation_id == identifier,
                ConversationMessage.message_role == "user",
                ConversationMessage.delete_flag == "N",
            ).order_by(ConversationMessage.message_index)).scalars()
            stream = runtime_state_service.get_run_state(owner, identifier)
            event_ids = [event_id for event_id, _ in runtime_state_service.read_stream_events(owner, identifier)]
            if executions:
                latest = executions[-1]
                journal = RunJournal(tenant, owner, identifier, latest.run_id)
                journal_entries = runtime_state_service.client.xrange(journal.key)
                if journal_entries:
                    stream = {"generation": latest.run_id, "execution_id": latest.run_id}
                    event_ids = [event_id for event_id, _ in journal_entries]
            states[str(identifier)] = {
                "reservations": [{"id": row.run_id, "status": row.status, "owner": row.owner_id,
                                  "agent_scope": row.agent_scope} for row in executions],
                "messages": list(messages),
                "stream": stream,
                "event_ids": event_ids,
            }
    return {"agent_limit": RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS, "conversations": states}


def read_agent_lane(token, port=5014):
    if port not in (5014, 5015) or POSTGRES_HOST not in POSTGRES_HOSTS:
        raise RuntimeError("The Agent capacity probe requires the isolated Runtime listener")
    actor = {"user_id": str(uuid5(token, "owner:user")), "tenant_id": str(uuid5(token, "owner:tenant")),
             "kind": "session"}
    path = "/internal/thread-capacity"
    identity = sign_identity(actor, "runtime", "GET", path, b"")
    request = Request(f"http://127.0.0.1:{port}{path}", headers={IDENTITY_HEADER: identity})
    with build_opener(ProxyHandler({})).open(request, timeout=8) as response:
        snapshot = json.load(response)
    lane, = (item for item in snapshot["lanes"] if item["name"] == "agent-run")
    return {**lane, "rejected_count": snapshot["rejected_count"]}


def set_user_message_fault(token, action, identifier):
    if (action not in {"install", "remove"} or identifier < 1 or POSTGRES_HOST not in POSTGRES_HOSTS
            or urlsplit(RUNTIME_STATE_REDIS_URL).hostname not in REDIS_HOSTS):
        raise ValueError("The persistence fault requires the isolated test conversation and stores")
    owner = str(uuid5(token, "owner:user"))
    table = ConversationMessage.__table__.fullname
    constraint = f"p1_user_write_{token.hex}_{identifier:d}"
    with get_db_session() as session:
        session.execute(select(ConversationRecord.conversation_id).where(
            ConversationRecord.conversation_id == identifier,
            ConversationRecord.created_by == owner,
            ConversationRecord.delete_flag == "N",
        )).scalar_one()
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        if action == "install":
            session.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
                                 f"CHECK (conversation_id <> {identifier:d} OR message_role <> 'user') NOT VALID"))
        else:
            session.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}"))
        installed = session.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_constraint "
                                        "WHERE conrelid = to_regclass(:relation) AND conname = :name)"),
                                   {"relation": table, "name": constraint})
        assert installed is (action == "install")
    return {"installed": installed}


def creator_preparation_gate(token, action, identifier):
    if (action not in {"hold", "probe", "release"} or identifier < 1 or POSTGRES_HOST not in POSTGRES_HOSTS
            or urlsplit(RUNTIME_STATE_REDIS_URL).hostname not in REDIS_HOSTS):
        raise ValueError("The preparation gate requires the case-owned conversation and stores")
    owner = str(uuid5(token, "owner:user"))
    redis = runtime_state_service.client
    signal = f"runtime-scaling-test:{token.hex}:creator-preparation:{identifier}"
    release = signal + ":release"
    table = ConversationMessage.__table__.fullname
    name = f"rs_creator_{token.hex}_{identifier:d}"
    function = f"{ConversationMessage.__table__.schema}.{name}"
    with get_db_session() as session:
        config = session.execute(select(ConversationRecord.workbench_config).where(
            ConversationRecord.conversation_id == identifier, ConversationRecord.created_by == owner,
            ConversationRecord.delete_flag == "N",
        )).scalar_one()
        assert config.get("mode") in {"agent_create", "skill_create"}
        if action == "probe":
            return {"stage": redis.get(signal)}
        if action == "release":
            return {"released": bool(redis.set(release, "release", ex=120))}

    try:
        with get_db_session() as gate:
            gate.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:signal, 0))"), {"signal": signal})
            with get_db_session() as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(text(
                    f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ "
                    f"BEGIN PERFORM pg_advisory_xact_lock(hashtextextended('{signal}', 0)); RETURN NEW; END; $$"
                ))
                session.execute(text(
                    f"CREATE TRIGGER {name} BEFORE INSERT ON {table} FOR EACH ROW "
                    f"WHEN (NEW.conversation_id = {identifier:d} AND NEW.message_role = 'user') "
                    f"EXECUTE FUNCTION {function}()"
                ))
            assert redis.set(signal, "ready", ex=120, nx=True)
            blocked = False
            deadline = monotonic() + 90
            while monotonic() < deadline:
                if redis.get(release):
                    return {"history_write_blocked": blocked}
                if not blocked and gate.scalar(text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND NOT granted "
                    "AND pg_backend_pid() = ANY(pg_blocking_pids(pid)))"
                )):
                    blocked = True
                    redis.set(signal, "blocked", ex=120)
                sleep(0.1)
            raise AssertionError("The Creator history gate was not released")
    finally:
        redis.delete(signal, release)
        with get_db_session() as session:
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            session.execute(text(f"DROP TRIGGER IF EXISTS {name} ON {table}"))
            session.execute(text(f"DROP FUNCTION IF EXISTS {function}()"))


def workbench_finalization_gate(token, action, identifier):
    return history_gate(token, action, identifier, phase="workbench-finalization",
                        modes={"generic_chat"}, relation_lock="RowShareLock",
                        receipt="assistant_projection_blocked")


def replay_workbench_completion(token, identifier, old_run_id):
    if (identifier < 1 or UUID(hex=old_run_id).hex != old_run_id or POSTGRES_HOST not in POSTGRES_HOSTS
            or urlsplit(RUNTIME_STATE_REDIS_URL).hostname not in REDIS_HOSTS):
        raise ValueError("Completion replay requires the case-owned conversation and coordination stores")
    user = str(uuid5(token, "owner:user"))
    tenant = str(uuid5(token, "owner:tenant"))
    with get_db_session() as session:
        config = session.scalar(select(ConversationRecord.workbench_config).where(
            ConversationRecord.conversation_id == identifier, ConversationRecord.created_by == user,
            ConversationRecord.delete_flag == "N",
        ))
        assert config and config.get("mode") == "generic_chat"

    key = str(identifier)
    before = read_batch(token, (identifier,))["conversations"][key]
    old, current = before["reservations"]
    assert old["id"] == old_run_id and old["status"] == "completed"
    assert current["status"] == "running" and old["owner"] != current["owner"]
    assert old["agent_scope"] == current["agent_scope"] == "workbench_main"
    assert before["stream"]["generation"] == current["id"]

    old_identity = RunIdentity(tenant, user, identifier, old_run_id)
    old_journal = RunJournal(tenant, user, identifier, old_run_id)
    old_entries = runtime_state_service.client.xrange(old_journal.key)
    with patch("infrastructure.rdb.agent_execution.OWNER_ID", old["owner"]):
        for _ in range(2):
            assert not finish_execution(old_identity, "completed"), "Duplicate SQL settlement"
            old_journal.repair_terminal("completed")
            assert runtime_state_service.client.xrange(old_journal.key) == old_entries
        assert not finish_execution(RunIdentity(tenant, user, identifier, current["id"]), "completed")
    after = read_batch(token, (identifier,))["conversations"][key]
    assert after == before, "Late completion changed the active execution, history or stream"
    return {"duplicate_completions_ignored": 2, "wrong_owner_rejected": True,
            "old_execution_id": old_run_id, "surviving_execution_id": current["id"]}


def history_gate(token, action, identifier, *, phase, modes, relation_lock, receipt):
    if (action not in {"hold", "probe", "release"} or identifier < 1 or POSTGRES_HOST not in POSTGRES_HOSTS
            or urlsplit(RUNTIME_STATE_REDIS_URL).hostname not in REDIS_HOSTS):
        raise ValueError("The history gate requires the case-owned conversation and coordination stores")
    owner = str(uuid5(token, "owner:user"))
    redis = runtime_state_service.client
    signal = f"runtime-scaling-test:{token.hex}:{phase}:{identifier}"
    release = signal + ":release"
    with get_db_session() as session:
        statement = select(ConversationRecord.workbench_config).where(
            ConversationRecord.conversation_id == identifier, ConversationRecord.created_by == owner,
            ConversationRecord.delete_flag == "N",
        )
        config = session.execute(statement.with_for_update() if action == "hold" else statement).scalar_one()
        assert config.get("mode") in modes
        if action == "probe":
            stage = redis.get(signal)
            return {"stage": stage.decode() if isinstance(stage, bytes) else stage}
        if action == "release":
            return {"released": bool(redis.set(release, "release", ex=120))}

        assert redis.set(signal, "ready", ex=120, nx=True)
        blocked = False
        deadline = monotonic() + 90
        try:
            while monotonic() < deadline:
                if redis.get(release):
                    return {receipt: blocked}
                if not blocked:
                    waiters = session.scalars(HISTORY_WAITERS, {
                        "conversation_table": ConversationRecord.__table__.fullname,
                        "relation_lock": relation_lock,
                    }).all()
                    assert len(waiters) <= 1, "More than one worker waited for the owned conversation row"
                    if waiters:
                        blocked = True
                        redis.set(signal, "blocked", ex=120)
                sleep(0.1)
            raise AssertionError(f"The {phase} gate was not released before its deadline")
        finally:
            redis.delete(signal, release)


def main():
    raw_token, *ids = sys.argv[1:]
    token = UUID(hex=raw_token)
    if token.hex != raw_token or POSTGRES_HOST not in POSTGRES_HOSTS:
        raise RuntimeError("The admission probe requires the case-owned database")
    if ids == ["--agent-lane"]:
        print("SCALING_ADMISSION " + json.dumps(read_agent_lane(token)))
        return
    preparation_faults = {"--user-message-fault": set_user_message_fault}
    if ids and ids[0] in preparation_faults:
        option, action, identifier = ids
        print("SCALING_ADMISSION " + json.dumps(preparation_faults[option](token, action, int(identifier))))
        return
    gates = {"--creator-preparation": creator_preparation_gate, "--workbench-finalization": workbench_finalization_gate}
    if ids and ids[0] in gates:
        option, action, identifier = ids
        print("SCALING_ADMISSION " + json.dumps(gates[option](token, action, int(identifier))))
        return
    if ids[:1] == ["--workbench-replay-completion"]:
        _, identifier, execution_id = ids
        print("SCALING_ADMISSION " + json.dumps(replay_workbench_completion(token, int(identifier), execution_id)))
        return
    role = "foreign" if ids[:1] == ["--foreign"] else "owner"
    if role == "foreign":
        ids = ids[1:]
    conversation_ids = tuple(map(int, ids))
    if not 1 <= len(conversation_ids) <= 8 or min(conversation_ids) < 1:
        raise RuntimeError("The admission probe requires a bounded set of case-owned conversations")
    print("SCALING_ADMISSION " + json.dumps(read_batch(token, conversation_ids, role=role)))


if __name__ == "__main__":
    main()
