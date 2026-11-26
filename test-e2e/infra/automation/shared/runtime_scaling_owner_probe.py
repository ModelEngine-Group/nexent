# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read test-owned durable executions, messages and actual Redis expiration."""

import json
import sys
from uuid import UUID, uuid5

from sqlalchemy import func, select

from contracts.constants.environment import POSTGRES_HOST, RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS, RUNTIME_STREAM_TTL_SECONDS
from infrastructure.rdb.agent_execution import ACTIVE, AgentExecution
from infrastructure.rdb.client import get_db_session
from infrastructure.redis.agent_events import RunJournal
from infrastructure.redis.run_state import runtime_state_service
from infrastructure.rdb.conversation_record import ConversationMessage, ConversationRecord


def read_owned_runs(token, identifiers):
    owner = str(uuid5(token, "owner:user"))
    tenant = str(uuid5(token, "owner:tenant"))
    state = {}
    with get_db_session() as session:
        for identifier in identifiers:
            session.execute(select(ConversationRecord.conversation_id).where(
                ConversationRecord.conversation_id == identifier, ConversationRecord.created_by == owner,
                ConversationRecord.delete_flag == "N",
            )).scalar_one()
            reservations = session.scalars(select(AgentExecution).where(
                AgentExecution.tenant_id == tenant, AgentExecution.created_by == owner,
                AgentExecution.conversation_id == identifier, AgentExecution.delete_flag == "N",
            ).order_by(AgentExecution.create_time, AgentExecution.run_id)).all()
            latest = reservations[-1] if reservations else None
            journal = RunJournal(tenant, owner, identifier, latest.run_id) if latest else None
            ttl = runtime_state_service.client.pttl(journal.key) if journal else -2
            journal_state = journal.run_state() if ttl > 0 else None
            now = session.scalar(select(func.clock_timestamp()))
            messages = list(session.execute(select(ConversationMessage).where(
                ConversationMessage.conversation_id == identifier, ConversationMessage.delete_flag == "N",
            ).order_by(ConversationMessage.message_index)).scalars())
            state[str(identifier)] = {
                "reservations": [{"id": row.run_id, "status": row.status, "owner": row.owner_id,
                                  "finished": row.status not in ACTIVE} for row in reservations],
                "users": [row.message_content for row in messages if row.message_role == "user"],
                "assistants": [{"id": row.message_id, "status": row.status}
                               for row in messages if row.message_role == "assistant"],
                "state_pttl": ttl,
                "state": {"generation": latest.run_id, "status": journal_state[1]} if journal_state else {},
                "lease_expired": bool(latest and latest.lease_until and latest.lease_until <= now),
                "cancel_ids": [row.run_id for row in reservations if row.status in ACTIVE and row.cancellation_requested],

            }
    return {"quota": RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS, "ttl_seconds": RUNTIME_STREAM_TTL_SECONDS, "runs": state}


if __name__ == "__main__":
    raw_token, *raw_ids = sys.argv[1:]
    token = UUID(hex=raw_token)
    identifiers = tuple(map(int, raw_ids))
    if token.hex != raw_token or len(identifiers) not in (1, 2) or min(identifiers) < 1 or POSTGRES_HOST not in {
        "nexent-postgresql", "nexent-postgresql.nexent", "nexent-postgresql.nexent.svc",
        "nexent-postgresql.nexent.svc.cluster.local",
    }:
        raise RuntimeError("The owner-loss probe requires case-owned conversations and database")
    print("SCALING_OWNER_LOSS " + json.dumps(read_owned_runs(token, identifiers)))
