# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Check journal isolation and replay retention for a case-owned Agent execution."""

import json
import sys
from time import monotonic, sleep
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from sqlalchemy import select

from contracts.constants.environment import POSTGRES_HOST, RUNTIME_STATE_REDIS_URL
from infrastructure.rdb.agent_execution import AgentExecution, RunIdentity, finish_execution
from infrastructure.rdb.client import get_db_session
from infrastructure.redis.agent_events import RunJournal
from infrastructure.redis.run_state import runtime_state_service


def fixture_host(host, service):
    return host in {service, f"{service}.nexent", f"{service}.nexent.svc", f"{service}.nexent.svc.cluster.local"}


def inspect_executions(identity):
    with get_db_session() as session:
        return dict(session.execute(select(AgentExecution.run_id, AgentExecution.status).where(
            AgentExecution.tenant_id == identity.tenant_id,
            AgentExecution.created_by == identity.user_id,
            AgentExecution.conversation_id == identity.conversation_id,
            AgentExecution.delete_flag == "N",
        )).all())


def observe(identity, action, arguments):
    journal = RunJournal(identity.tenant_id, identity.user_id, identity.conversation_id, identity.run_id)
    redis = runtime_state_service.client
    before = inspect_executions(identity)
    current = before[identity.run_id]
    entries = redis.xrange(journal.key)
    if action == "settled":
        return {"terminal_committed": current == "completed" and bool(entries)
                and entries[-1][1] == {"kind": "terminal", "status": "completed"}}
    if action == "expire":
        assert current == "completed" and entries[-1][1]["kind"] == "terminal"
        assert redis.pttl(journal.key) > 75 and redis.pexpire(journal.key, 75)
        deadline = monotonic() + 5
        while redis.exists(journal.key):
            assert monotonic() < deadline, "Retained replay data did not expire"
            sleep(0.02)
        assert inspect_executions(identity) == before
        return {"expired_stream_keys": 1}

    stale_id, = arguments
    assert UUID(hex=stale_id).hex == stale_id and before[stale_id] == "stopped" and current == "running"
    stale = RunIdentity(identity.tenant_id, identity.user_id, identity.conversation_id, stale_id)
    stale_journal = RunJournal(stale.tenant_id, stale.user_id, stale.conversation_id, stale_id)
    stale_entries = redis.xrange(stale_journal.key)
    assert stale_entries[-1][1] == {"kind": "terminal", "status": "stopped"}
    assert not finish_execution(stale, "completed")
    stale_journal.repair_terminal("completed")
    assert redis.xrange(stale_journal.key) == stale_entries
    assert redis.xrange(journal.key) == entries
    assert inspect_executions(identity) == before
    return {"stream_unchanged": True, "journal_unchanged": True, "completion_rejected": True}


def exercise_probe(raw_token, action, raw_identifier, run_id, *arguments):
    token = UUID(hex=raw_token)
    identifier = int(raw_identifier)
    if (token.hex != raw_token or identifier < 1 or UUID(hex=run_id).hex != run_id
            or not fixture_host(POSTGRES_HOST, "nexent-postgresql")
            or not fixture_host(urlsplit(RUNTIME_STATE_REDIS_URL).hostname, "nexent-redis")):
        raise ValueError("The stream probe requires test-owned stores and a case-owned execution")
    if (action, len(arguments)) not in {("settled", 0), ("expire", 0), ("late", 1)}:
        raise ValueError("Unknown stream probe operation")
    identity = RunIdentity(str(uuid5(token, "owner:tenant")), str(uuid5(token, "owner:user")), identifier, run_id)
    return observe(identity, action, arguments)


if __name__ == "__main__":
    print("SCALING_STREAM " + json.dumps(exercise_probe(*sys.argv[1:])))
