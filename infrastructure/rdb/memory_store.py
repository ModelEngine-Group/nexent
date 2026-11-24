# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorized and serialized persistence for Agent short-term Memory writes."""

import json
from collections.abc import Callable

from sqlalchemy import select, text

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_record import ConversationRecord
from infrastructure.rdb.conversation_state import tenant_membership_matches
from infrastructure.rdb.memory_record import MemoryRecord
from infrastructure.rdb.orm import as_dict
from infrastructure.rdb.tenant_config_record import TenantConfig


class MemoryStoreScopeError(Exception):
    """The caller cannot address the requested Agent or conversation."""


class MemoryStoreConflictError(Exception):
    """An idempotency key has already been assigned to a different scope."""


def _require_scope(session, tenant_id: str, user_id: str, agent_id: int, conversation_id: int | None) -> None:
    if not tenant_membership_matches(session, user_id, tenant_id):
        raise MemoryStoreScopeError
    if conversation_id is not None and session.scalar(select(ConversationRecord.conversation_id).where(
        ConversationRecord.conversation_id == conversation_id,
        ConversationRecord.created_by == user_id,
        ConversationRecord.delete_flag == "N",
    )) is None:
        raise MemoryStoreScopeError
    agent = session.execute(text("""
        SELECT agent_id FROM nexent.ag_tenant_agent_t
        WHERE agent_id = :agent_id AND delete_flag <> 'Y'
          AND (tenant_id = :tenant_id OR (tenant_id = :platform_tenant AND version_no > 0))
        LIMIT 1
    """), {"agent_id": agent_id, "tenant_id": tenant_id, "platform_tenant": ASSET_OWNER_TENANT_ID}).scalar()
    if agent is None:
        raise MemoryStoreScopeError


def _find(session, tenant_id: str, key: str, user_id: str, agent_id: int) -> MemoryRecord | None:
    row = session.scalar(select(MemoryRecord).where(
        MemoryRecord.tenant_id == tenant_id,
        MemoryRecord.idempotency_key == key,
        MemoryRecord.delete_flag == "N",
    ).order_by(MemoryRecord.memory_id).limit(1))
    if row is not None and (row.user_id, row.agent_id, row.layer, row.memory_type) != (
        user_id, str(agent_id), "agent", "short_term",
    ):
        raise MemoryStoreConflictError
    return row


def _lock(session, tenant_id: str, key: str) -> None:
    lock_key = json.dumps(["agent-memory", tenant_id, key], ensure_ascii=False, separators=(",", ":"))
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock_key})


def find_existing_memory(
    tenant_id: str, user_id: str, agent_id: int, conversation_id: int | None, key: str, content: str,
) -> int | None:
    with get_db_session() as session:
        _require_scope(session, tenant_id, user_id, agent_id, conversation_id)
        row = _find(session, tenant_id, key, user_id, agent_id)
        return row.memory_id if row is not None and row.content == content else None


def write_agent_memory(
    tenant_id: str, user_id: str, agent_id: int, conversation_id: int | None, key: str, content: str, index_name: str,
) -> tuple[int, str]:
    with get_db_session() as session:
        _lock(session, tenant_id, key)
        _require_scope(session, tenant_id, user_id, agent_id, conversation_id)
        row = _find(session, tenant_id, key, user_id, agent_id)
        if row is not None:
            if row.content == content:
                return row.memory_id, "UNCHANGED"
            row.content = content
            row.es_index_name = index_name
            row.updated_by = user_id
            return row.memory_id, "UPDATE"
        row = MemoryRecord(
            tenant_id=tenant_id, user_id=user_id, agent_id=str(agent_id),
            conversation_id=str(conversation_id) if conversation_id is not None else None,
            idempotency_key=key, content=content, es_index_name=index_name, layer="agent", memory_type="short_term",
            status="active", delete_flag="N", created_by=user_id, updated_by=user_id, concept_tags=[],
        )
        session.add(row)
        session.flush()
        return row.memory_id, "ADD"


def mirror_current_memory(
    tenant_id: str, key: str, memory_id: int, content: str, index_name: str, publish: Callable[[dict], bool],
) -> bool:
    with get_db_session() as session:
        _lock(session, tenant_id, key)
        row = session.scalar(select(MemoryRecord).where(
            MemoryRecord.memory_id == memory_id,
            MemoryRecord.tenant_id == tenant_id,
            MemoryRecord.idempotency_key == key,
            MemoryRecord.content == content,
            MemoryRecord.es_index_name == index_name,
            MemoryRecord.delete_flag == "N",
        ))
        if row is None:
            return False
        return publish(as_dict(row))


def read_memory_embedding_model_id(tenant_id: str) -> int | None:
    with get_db_session() as session:
        value = session.scalar(select(TenantConfig.config_value).where(
            TenantConfig.tenant_id == tenant_id,
            TenantConfig.config_key == "EMBEDDING_ID",
            TenantConfig.delete_flag == "N",
        ).order_by(TenantConfig.tenant_config_id.desc()).limit(1))
    try:
        model_id = int(value)
    except (TypeError, ValueError):
        return None
    return model_id if model_id > 0 else None
