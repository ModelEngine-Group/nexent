# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Database queries for paginated Agent-chat history groups."""

from typing import Any, Optional

from sqlalchemy import and_, case, desc, exists, false, func, or_, select

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.conversation import (
    conversation_time_as_utc,
    decode_agent_conversation_cursor,
    decode_agent_group_cursor,
    encode_agent_conversation_cursor,
    encode_agent_group_cursor,
)
from management.db.client import get_db_session
from management.db.agent.models import AgentInfo
from management.db.conversation.models import ConversationRecord


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _agent_group_name(agent_id, tenant_id: str):
    return (
        select(func.coalesce(AgentInfo.display_name, AgentInfo.name))
        .where(
            AgentInfo.agent_id == agent_id,
            AgentInfo.version_no == 0,
            AgentInfo.delete_flag == "N",
            AgentInfo.tenant_id.in_([tenant_id, ASSET_OWNER_TENANT_ID]),
        )
        .order_by(case((AgentInfo.tenant_id == tenant_id, 0), else_=1))
        .limit(1)
        .scalar_subquery()
    )


def _group_source(user_id: str):
    activity = func.coalesce(
        ConversationRecord.last_activity_time,
        ConversationRecord.create_time,
    )
    return (
        select(
            ConversationRecord.agent_id.label("agent_id"),
            func.max(activity).label("activity_time"),
        )
        .where(
            ConversationRecord.created_by == user_id,
            ConversationRecord.delete_flag == "N",
            ConversationRecord.workbench_config.is_(None),
        )
        .group_by(ConversationRecord.agent_id)
        .subquery()
    )


def _group_query(user_id: str, tenant_id: str, search: str):
    groups = _group_source(user_id)
    group_id = func.coalesce(groups.c.agent_id, -1).label("group_id")
    agent_name = _agent_group_name(groups.c.agent_id, tenant_id).label("agent_name")
    agent_available = exists(
        select(1).where(
            AgentInfo.agent_id == groups.c.agent_id,
            AgentInfo.version_no == 0,
            AgentInfo.delete_flag == "N",
            AgentInfo.enabled.is_(True),
            AgentInfo.current_version_no.is_not(None),
            AgentInfo.tenant_id.in_([tenant_id, ASSET_OWNER_TENANT_ID]),
        )
    ).label("agent_available")
    statement = select(
        groups.c.agent_id,
        group_id,
        groups.c.activity_time,
        agent_name,
        agent_available,
    )

    pinned_group = exists(
        select(1).where(
            ConversationRecord.created_by == user_id,
            ConversationRecord.delete_flag == "N",
            ConversationRecord.workbench_config.is_(None),
            ConversationRecord.workbench_pinned_at.is_not(None),
            ConversationRecord.agent_id.is_not_distinct_from(groups.c.agent_id),
        )
    )
    title_match = (
        exists(
            select(1).where(
                ConversationRecord.created_by == user_id,
                ConversationRecord.delete_flag == "N",
                ConversationRecord.workbench_config.is_(None),
                ConversationRecord.agent_id.is_not_distinct_from(groups.c.agent_id),
                ConversationRecord.conversation_title.ilike(
                    f"%{_escape_like(search)}%", escape="\\"
                ),
            )
        )
        if search
        else false()
    )
    statement = statement.add_columns(title_match.label("matched_conversation"))
    if search:
        statement = statement.where(
            or_(agent_name.ilike(f"%{_escape_like(search)}%", escape="\\"), title_match)
        )
    return statement, group_id, pinned_group


def _serialize_group(row) -> dict[str, Any]:
    agent_id = int(row.agent_id) if row.agent_id is not None else None
    return {
        "group_key": f"agent:{agent_id}" if agent_id is not None else "other",
        "agent_id": agent_id,
        "agent_name": row.agent_name,
        "agent_available": bool(row.agent_available) if agent_id is not None else True,
        "last_activity_time": int(conversation_time_as_utc(row.activity_time).timestamp() * 1000),
        "matched_conversation": bool(row.matched_conversation),
    }


def get_agent_conversation_group_page(
    user_id: str,
    tenant_id: str,
    limit: int = 10,
    cursor: Optional[str] = None,
    search: str = "",
    include_agent_ids: Optional[list[int]] = None,
    include_other: bool = False,
) -> dict[str, Any]:
    """Return a keyset page of Agent groups and out-of-page pinned groups."""
    if not 1 <= limit <= 100:
        raise ValueError("Agent group limit must be between 1 and 100")
    search = search.strip()
    boundary = decode_agent_group_cursor(cursor, search) if cursor else None
    statement, group_id, pinned_group = _group_query(user_id, tenant_id, search)
    regular = statement.order_by(desc(statement.selected_columns.activity_time), desc(group_id))
    if boundary:
        activity, identity = boundary
        group_activity = statement.selected_columns.activity_time
        regular = regular.where(or_(
            group_activity < activity.replace(tzinfo=None),
            and_(group_activity == activity.replace(tzinfo=None), group_id < identity),
        ))
    with get_db_session() as session:
        pinned_statement = statement.where(pinned_group).order_by(
            desc(statement.selected_columns.activity_time), desc(group_id)
        )
        pinned_rows = list(session.execute(pinned_statement))
        rows = list(session.execute(regular.limit(limit + 1)))
        included_rows = []
        include_conditions = []
        valid_agent_ids = [agent_id for agent_id in (include_agent_ids or []) if agent_id > 0]
        if valid_agent_ids:
            include_conditions.append(statement.selected_columns.agent_id.in_(valid_agent_ids))
        if include_other:
            include_conditions.append(statement.selected_columns.agent_id.is_(None))
        if include_conditions:
            included_statement = statement.where(or_(*include_conditions)).order_by(
                desc(statement.selected_columns.activity_time), desc(group_id)
            )
            included_rows = list(session.execute(included_statement))
        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        next_cursor = None
        if has_more and visible_rows:
            last = visible_rows[-1]
            next_cursor = encode_agent_group_cursor(
                last.activity_time,
                int(last.group_id),
                search,
            )
        regular_rows = visible_rows
    return {
        "items": [_serialize_group(row) for row in regular_rows],
        "pinned_items": [_serialize_group(row) for row in pinned_rows],
        "included_items": [_serialize_group(row) for row in included_rows],
        "next_cursor": next_cursor,
    }


def _group_filter(group_key: str):
    if group_key == "other":
        return ConversationRecord.agent_id.is_(None)
    if not group_key.startswith("agent:"):
        raise ValueError("Invalid agent conversation group")
    try:
        agent_id = int(group_key[6:])
    except ValueError as exc:
        raise ValueError("Invalid agent conversation group") from exc
    if agent_id <= 0 or str(agent_id) != group_key[6:]:
        raise ValueError("Invalid agent conversation group")
    return ConversationRecord.agent_id == agent_id


def _conversation_item(row) -> dict[str, Any]:
    return {
        "conversation_id": int(row.conversation_id),
        "conversation_title": row.conversation_title,
        "agent_id": int(row.agent_id) if row.agent_id is not None else None,
        "create_time": int(row.create_time),
        "update_time": int(row.update_time),
        "last_activity_time": int(row.last_activity_time),
        "pinned_at": conversation_time_as_utc(row.pinned_at).isoformat()
        if row.pinned_at is not None
        else None,
    }


def _conversation_statement(user_id: str, group_key: str, search: str):
    activity = func.coalesce(
        ConversationRecord.last_activity_time,
        ConversationRecord.create_time,
    )
    statement = select(
        ConversationRecord.conversation_id,
        ConversationRecord.conversation_title,
        ConversationRecord.agent_id,
        ConversationRecord.workbench_pinned_at.label("pinned_at"),
        activity.label("activity_time"),
        (func.extract("epoch", ConversationRecord.create_time) * 1000).label("create_time"),
        (func.extract("epoch", ConversationRecord.update_time) * 1000).label("update_time"),
        (func.extract("epoch", activity) * 1000).label("last_activity_time"),
    ).where(
        ConversationRecord.created_by == user_id,
        ConversationRecord.delete_flag == "N",
        ConversationRecord.workbench_config.is_(None),
        _group_filter(group_key),
    )
    if search:
        statement = statement.where(
            ConversationRecord.conversation_title.ilike(f"%{_escape_like(search)}%", escape="\\")
        )
    return statement


def get_agent_group_conversation_page(
    user_id: str,
    group_key: str,
    limit: int = 10,
    cursor: Optional[str] = None,
    search: str = "",
) -> dict[str, Any]:
    """Return a conversation page and all pinned history in one Agent group."""
    if not 1 <= limit <= 100:
        raise ValueError("Conversation limit must be between 1 and 100")
    search = search.strip()
    boundary = decode_agent_conversation_cursor(cursor, group_key, search) if cursor else None
    statement = _conversation_statement(user_id, group_key, search)
    regular = statement.order_by(
        desc(statement.selected_columns.activity_time),
        desc(statement.selected_columns.conversation_id),
    )
    if boundary:
        activity, identity = boundary
        activity_expr = statement.selected_columns.activity_time
        id_expr = statement.selected_columns.conversation_id
        regular = regular.where(or_(
            activity_expr < activity.replace(tzinfo=None),
            and_(activity_expr == activity.replace(tzinfo=None), id_expr < identity),
        ))
    pinned = _conversation_statement(user_id, group_key, search).where(
        ConversationRecord.workbench_pinned_at.is_not(None)
    ).order_by(
        desc(ConversationRecord.workbench_pinned_at),
        desc(ConversationRecord.conversation_id),
    )
    with get_db_session() as session:
        rows = list(session.execute(regular.limit(limit + 1)))
        pinned_rows = list(session.execute(pinned))
    has_more = len(rows) > limit
    visible = rows[:limit]
    next_cursor = None
    if has_more and visible:
        last = visible[-1]
        next_cursor = encode_agent_conversation_cursor(
            last.activity_time,
            int(last.conversation_id),
            group_key,
            search,
        )
    return {
        "items": [_conversation_item(row) for row in visible],
        "pinned_items": [_conversation_item(row) for row in pinned_rows],
        "next_cursor": next_cursor,
    }


def list_agent_conversation_ids(user_id: str, agent_id: int) -> list[int]:
    """Return every active Agent-chat history ID for one Agent only."""
    if type(agent_id) is not int or agent_id <= 0:
        raise ValueError("Invalid agent ID")
    with get_db_session() as session:
        rows = session.scalars(
            select(ConversationRecord.conversation_id)
            .where(
                ConversationRecord.created_by == user_id,
                ConversationRecord.delete_flag == "N",
                ConversationRecord.workbench_config.is_(None),
                ConversationRecord.agent_id == agent_id,
            )
            .order_by(desc(ConversationRecord.conversation_id))
        )
        return [int(conversation_id) for conversation_id in rows]
