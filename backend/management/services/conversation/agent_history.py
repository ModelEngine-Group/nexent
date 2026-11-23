# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Service boundary for Agent-chat history group queries."""

from database.conversation_agent_history_db import (
    get_agent_conversation_group_page,
    get_agent_group_conversation_page,
    list_agent_conversation_ids,
)


def list_agent_groups(
    user_id: str,
    tenant_id: str,
    limit: int = 10,
    cursor: str | None = None,
    search: str = "",
    include_agent_ids: list[int] | None = None,
    include_other: bool = False,
) -> dict:
    if not user_id or not tenant_id:
        raise ValueError("Authenticated user and tenant are required")
    return get_agent_conversation_group_page(
        user_id,
        tenant_id,
        limit,
        cursor,
        search,
        include_agent_ids,
        include_other,
    )


def list_agent_group_conversations(
    user_id: str,
    group_key: str,
    limit: int = 10,
    cursor: str | None = None,
    search: str = "",
) -> dict:
    if not user_id:
        raise ValueError("Authenticated user is required")
    return get_agent_group_conversation_page(user_id, group_key, limit, cursor, search)


def list_agent_group_conversation_ids(user_id: str, agent_id: int) -> dict:
    if not user_id:
        raise ValueError("Authenticated user is required")
    return {"items": list_agent_conversation_ids(user_id, agent_id)}
