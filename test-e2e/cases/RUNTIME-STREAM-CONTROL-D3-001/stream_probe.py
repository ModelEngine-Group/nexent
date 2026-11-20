# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise delayed producer writes and replay expiry for a disposable conversation."""

import json
import re
import sys
from time import monotonic, sleep
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from sqlalchemy import select

from contracts.constants.environment import POSTGRES_HOST, RUNTIME_STATE_REDIS_URL
from infrastructure.rdb.client import get_db_session
from infrastructure.redis.run_state import runtime_state_service as state
from management.db.conversation.models import ConversationRecord
from management.db.execution.models import ExecutionReservation
from management.services.execution_coordination import transition_runtime_execution


def fixture_host(host, service):
    return host in {service, f"{service}.nexent", f"{service}.nexent.svc", f"{service}.nexent.svc.cluster.local"}


def owned_reservations(session, tenant, owner, identifier):
    session.execute(select(ConversationRecord.conversation_id).where(
        ConversationRecord.conversation_id == identifier,
        ConversationRecord.created_by == owner,
        ConversationRecord.delete_flag == "N",
    )).scalar_one()
    row = ExecutionReservation
    return {record.execution_id: record for record in session.execute(select(
        row.execution_id, row.owner_instance_id, row.maintenance_epoch, row.status, row.update_time, row.finished_at,
    ).where(
        row.tenant_id == tenant,
        row.user_id == owner,
        row.execution_key == f"conversation:{identifier}",
        row.execution_kind == "agent",
        row.service_role == "runtime",
        row.delete_flag == "N",
    ))}


def execution_number(generation):
    match = re.fullmatch(r"execution:([1-9][0-9]{0,9})", generation)
    if match is None:
        raise ValueError("The fixture requires an exact Agent execution generation")
    return int(match[1])


def observed_state(owner, identifier, execution_id):
    return (state.get_run_state(owner, identifier), state.read_execution_stream(owner, identifier, execution_id),
            state.get_stream_status(owner, identifier), state.read_stream_events(owner, identifier))


def inject_stale_completion(session, owner, identifier, generation, stale_generation, current, stale):
    assert current.status == "RUNNING" and stale.status == "STOPPED"
    assert stale.execution_id < current.execution_id and stale.maintenance_epoch == current.maintenance_epoch
    before = observed_state(owner, identifier, current.execution_id)
    run, stream, done, entries = before
    assert run["generation"] == stream["generation"] == generation and run["status"] == "running"
    assert stream["checkpoint"] and not stream["incomplete"] and not done and entries
    sentinel = {"type": "final_answer", "content": "stale-producer-event-must-not-appear"}
    sequence = int(state.client.hget(state._replay_key(owner, identifier), "sequence")) + 1
    assert state.append_stream_event(
        owner, identifier, f"data: {json.dumps(sentinel)}\n\n", generation=stale_generation,
        replay_update={"slot": len(stream["checkpoint"]["entries"]), "payload": sentinel, "append": False,
                       "sequence": sequence},
    ) is None
    state.mark_stream_completed(owner, identifier, "completed", generation=stale_generation, event_count=1)
    state.mark_run_finished(owner, identifier, "completed", generation=stale_generation)
    assert transition_runtime_execution(stale.execution_id, stale.owner_instance_id, "COMPLETED",
                                        db_session=session) is False
    assert observed_state(owner, identifier, current.execution_id) == before
    return {"stream_unchanged": True, "checkpoint_unchanged": True, "completion_rejected": True}


def expire_retained_stream(owner, identifier, generation, current):
    assert current.status == "COMPLETED"
    run, stream, done, entries = observed_state(owner, identifier, current.execution_id)
    assert run["generation"] == stream["generation"] == generation and run["status"] == "completed"
    assert stream["checkpoint"] and stream["terminal_status"] == done["status"] == "completed" and entries
    keys = (state._run_key(owner, identifier), state._stream_key(owner, identifier),
            state._stream_done_key(owner, identifier), state._replay_key(owner, identifier))
    shortened = state.client.eval("""
        if redis.call('HGET', KEYS[1], 'generation') ~= ARGV[1]
            or redis.call('HGET', KEYS[1], 'status') ~= 'completed'
            or redis.call('HGET', KEYS[3], 'status') ~= 'completed' then return 0 end
        for pos = 2, #KEYS do
            if redis.call('PTTL', KEYS[pos]) <= tonumber(ARGV[2]) then return 0 end
        end
        for pos = 2, #KEYS do redis.call('PEXPIRE', KEYS[pos], ARGV[2]) end
        return #KEYS - 1
    """, len(keys), *keys, generation, 75)
    assert shortened == len(keys) - 1, "Only the completed generation's retained stream may be expired"
    deadline = monotonic() + 5
    while state.client.exists(*keys[1:]):
        assert monotonic() < deadline, "Retained replay data did not expire in Redis"
        sleep(0.02)
    assert state.get_run_state(owner, identifier)["generation"] == generation
    assert state.read_execution_stream(owner, identifier, current.execution_id)["checkpoint"] is None
    return {"expired_stream_keys": shortened}


def exercise_probe(raw_token, action, raw_identifier, generation, *extra):
    token = UUID(hex=raw_token)
    identifier = int(raw_identifier)
    if (token.hex != raw_token or identifier < 1 or not fixture_host(POSTGRES_HOST, "nexent-postgresql")
            or not fixture_host(urlsplit(RUNTIME_STATE_REDIS_URL).hostname, "nexent-redis")):
        raise ValueError("The stream probe requires test-owned coordination stores and a case-owned conversation")
    if (action, len(extra)) not in {("settled", 0), ("expire", 0), ("late", 1)}:
        raise ValueError("Unknown stream probe operation")
    owner = str(uuid5(token, "owner:user"))
    tenant = str(uuid5(token, "owner:tenant"))
    with get_db_session() as session:
        before = owned_reservations(session, tenant, owner, identifier)
        current = before[execution_number(generation)]
        assert current.execution_id == max(before), "The fixture must address the latest owned generation"
        if action == "settled":
            stream = state.read_execution_stream(owner, identifier, current.execution_id)
            return {"terminal_committed": current.status == "COMPLETED" and stream is not None
                    and stream["generation"] == generation and stream["terminal_status"] == "completed"
                    and stream["checkpoint"] is not None and not stream["incomplete"]}
        if action == "expire":
            result = expire_retained_stream(owner, identifier, generation, current)
        else:
            stale_generation, = extra
            stale = before[execution_number(stale_generation)]
            result = inject_stale_completion(session, owner, identifier, generation, stale_generation, current, stale)
        assert owned_reservations(session, tenant, owner, identifier) == before
    return result


if __name__ == "__main__":
    print("SCALING_STREAM " + json.dumps(exercise_probe(*sys.argv[1:])))
