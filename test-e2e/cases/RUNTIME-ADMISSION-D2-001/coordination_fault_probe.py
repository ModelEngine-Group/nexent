# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Induce a bounded admission-only failure in each case-owned coordination store."""

import json
import sys
from time import monotonic, sleep
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from redis.exceptions import NoPermissionError
from sqlalchemy import select, text

from contracts.constants.environment import POSTGRES_HOST, RUNTIME_STATE_REDIS_URL
from infrastructure.rdb.agent_execution import ACTIVE, AgentExecution
from infrastructure.rdb.client import get_db_session
from infrastructure.redis.run_state import runtime_state_service
from infrastructure.rdb.conversation_record import ConversationRecord


POSTGRES_HOSTS = {"nexent-postgresql", "nexent-postgresql.nexent", "nexent-postgresql.nexent.svc",
                  "nexent-postgresql.nexent.svc.cluster.local"}
REDIS_HOSTS = {"nexent-redis", "nexent-redis.nexent", "nexent-redis.nexent.svc", "nexent-redis.nexent.svc.cluster.local"}
WAITING_ADMISSION = text("""
    SELECT pending.pid
    FROM pg_locks AS pending
    WHERE NOT pending.granted AND pg_backend_pid() = ANY(pg_blocking_pids(pending.pid))
      AND pending.locktype = 'advisory'
""")


def cancel_postgres_admission(session, redis, signal, tenant, agent_id):
    scope = json.dumps(("nexent:runtime:agentos-admission", tenant, f"agent:{agent_id}"))
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"), {"scope": scope})
    assert redis.set(signal, "awaiting-admission", nx=True, ex=90)
    try:
        deadline = monotonic() + 60
        while monotonic() < deadline:
            waiting = session.scalars(WAITING_ADMISSION).all()
            if waiting:
                waiter, = waiting
                assert session.scalar(text("SELECT pg_cancel_backend(:waiter)"), {"waiter": waiter}) is True
                return {"scoped_waiter_observed": True, "query_canceled": True}
            sleep(0.1)
        raise AssertionError("No Runtime admission query waited on the case-owned Agent scope")
    finally:
        redis.delete(signal)


def default_redis_acl(redis):
    rule, = (rule for rule in redis.acl_list() if rule.startswith("user default "))
    return rule


def deny_redis_xadd(redis, signal):
    rule = default_redis_acl(redis)
    assert {"on", "nopass"} <= set(rule.split())
    assert [permission for permission in rule.split() if permission.startswith(("+", "-"))] == ["+@all"]
    assert redis.ping() and redis.set(signal, rule, nx=True, ex=180)
    try:
        redis.execute_command("ACL", "SETUSER", "default", "-xadd")
        try:
            redis.xadd(f"{signal}:check", {"probe": "1"})
        except NoPermissionError:
            return {"journal_xadd_denied": True}
        redis.delete(f"{signal}:check")
        raise AssertionError("The real Redis server did not reject the no-longer-authorized XADD")
    except BaseException:
        restore_redis_xadd(redis, signal)
        raise


def restore_redis_xadd(redis, signal):
    original = redis.get(signal)
    if original is None:
        return {"acl_restored": False}
    redis.execute_command("ACL", "SETUSER", "default", "-@all", "+@all")
    assert redis.ping() and default_redis_acl(redis) == original
    assert redis.delete(signal) == 1
    return {"acl_restored": True}


def run_fault_probe(raw_token, action, raw_identifier, raw_agent_id=None):
    token = UUID(hex=raw_token)
    identifier = int(raw_identifier)
    if (token.hex != raw_token or identifier < 1 or POSTGRES_HOST not in POSTGRES_HOSTS
            or urlsplit(RUNTIME_STATE_REDIS_URL).hostname not in REDIS_HOSTS):
        raise ValueError("Fault injection requires the case-owned PostgreSQL and Redis services")
    tenant, user = str(uuid5(token, "owner:tenant")), str(uuid5(token, "owner:user"))
    redis = runtime_state_service.client
    pg_signal = f"runtime-admission-probe:{token.hex}:{identifier}:postgres"
    redis_signal = f"runtime-admission-probe:{token.hex}:{identifier}:redis"
    with get_db_session() as session:
        conversation = select(ConversationRecord.conversation_id).where(
            ConversationRecord.conversation_id == identifier, ConversationRecord.created_by == user,
            ConversationRecord.delete_flag == "N",
        )
        session.execute(conversation).scalar_one()
        if action == "restore-redis":
            return restore_redis_xadd(redis, redis_signal)
        assert session.scalar(select(AgentExecution.run_id).where(
            AgentExecution.tenant_id == tenant, AgentExecution.created_by == user,
            AgentExecution.conversation_id == identifier, AgentExecution.delete_flag == "N",
            AgentExecution.status.in_(ACTIVE),
        ).limit(1)) is None
        if action == "deny-redis":
            return deny_redis_xadd(redis, redis_signal)
        if action == "cancel-postgres":
            agent_id = int(raw_agent_id)
            assert agent_id > 0
            return cancel_postgres_admission(session, redis, pg_signal, tenant, agent_id)
        if action == "postgres-ready":
            return {"locked": redis.get(pg_signal) == "awaiting-admission"}
    raise ValueError("Unexpected coordination fault action")


if __name__ == "__main__":
    print("SCALING_COORDINATION_FAULT " + json.dumps(run_fault_probe(*sys.argv[1:])))
