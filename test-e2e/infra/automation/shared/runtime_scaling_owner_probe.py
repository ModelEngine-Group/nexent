# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read test-owned durable executions, messages and actual Redis expiration."""

import json
import sys
from uuid import UUID, uuid5

from sqlalchemy import select

from contracts.constants.environment import POSTGRES_HOST, RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS, RUNTIME_RUN_TTL_SECONDS
from infrastructure.rdb.client import get_db_session
from infrastructure.redis.run_state import runtime_state_service
from management.db.conversation.models import ConversationMessage, ConversationRecord
from management.db.execution.models import ExecutionReservation


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
            reservations = list(session.execute(select(ExecutionReservation).where(
                ExecutionReservation.tenant_id == tenant, ExecutionReservation.user_id == owner,
                ExecutionReservation.execution_kind == "agent", ExecutionReservation.service_role == "runtime",
                ExecutionReservation.execution_key == f"conversation:{identifier}", ExecutionReservation.delete_flag == "N",
            ).order_by(ExecutionReservation.execution_id)).scalars())
            messages = list(session.execute(select(ConversationMessage).where(
                ConversationMessage.conversation_id == identifier, ConversationMessage.delete_flag == "N",
            ).order_by(ConversationMessage.message_index)).scalars())
            state[str(identifier)] = {
                "reservations": [{"id": row.execution_id, "status": row.status, "owner": row.owner_instance_id,
                                  "epoch": row.maintenance_epoch, "finished": row.finished_at is not None,
                                  "error_code": row.error_code} for row in reservations],
                "users": [row.message_content for row in messages if row.message_role == "user"],
                "assistants": [{"id": row.message_id, "status": row.status}
                               for row in messages if row.message_role == "assistant"],
                "state_pttl": runtime_state_service.client.pttl(runtime_state_service._run_key(owner, identifier)),
                "state": runtime_state_service.get_run_state(owner, identifier),
                "cancel_ids": [row.execution_id for row in reservations if runtime_state_service.client.exists(
                    runtime_state_service._execution_cancel_key(owner, identifier, row.execution_id),
                )],
            }
    return {"quota": RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS, "ttl_seconds": RUNTIME_RUN_TTL_SECONDS, "runs": state}


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
