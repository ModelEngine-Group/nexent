# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Ingest a Runtime Memory record with Management-owned provider settings."""

from contracts.agentos import AgentMemoryStored
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.conversation_state import conversation_belongs_to
from management.db.memory.record import get_memory_record
from management.services.memory.provider import _fanout_external_ingest
from nexent.core.concurrency import run_blocking


def _read_owned_memory(notice: AgentMemoryStored, actor: ServicePrincipal) -> dict | None:
    if not conversation_belongs_to(notice.conversation_id, user_id=actor.user_id, tenant_id=actor.tenant_id):
        return None
    record = get_memory_record(notice.memory_id, actor.tenant_id)
    if record is None or (
        record["tenant_id"], record["user_id"], record["agent_id"],
        record["layer"], record["memory_type"], record["status"],
    ) != (actor.tenant_id, actor.user_id, str(notice.agent_id), "agent", "short_term", "active"):
        return None
    return {**record, "conversation_id": str(notice.conversation_id)}


async def ingest_stored_agent_memory(notice: AgentMemoryStored, actor: ServicePrincipal) -> bool:
    record = await run_blocking(
        "agentos-read-stored-memory", _read_owned_memory, notice, actor, lane="control-io", owner="management.memory",
    )
    if record is None:
        return False
    await _fanout_external_ingest(record, {"memory_id": notice.memory_id})
    return True
