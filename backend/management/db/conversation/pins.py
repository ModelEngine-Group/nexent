# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Personal conversation pin timestamps, independent of conversation activity."""

import json
from typing import Any

from sqlalchemy import case, func, select, text, update

from contracts.errors.exceptions import ConversationNotFoundError
from contracts.conversation import conversation_time_as_utc
from management.db.client import get_db_session
from management.db.models import ConversationRecord
from management.db.conversation.classification import is_workbench_history


def _owned_conversations(user_id: str):
    return (
        ConversationRecord.created_by == user_id,
        ConversationRecord.delete_flag == "N",
    )


def _list_pins(session, user_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(
            ConversationRecord,
            func.extract("epoch", ConversationRecord.create_time) * 1000,
            func.extract("epoch", ConversationRecord.update_time) * 1000,
            case(
                (is_workbench_history(), "workbench"),
                else_="agent_chat",
            ),
        )
        .where(*_owned_conversations(user_id), ConversationRecord.workbench_pinned_at.is_not(None))
        .order_by(ConversationRecord.workbench_pinned_at.desc(), ConversationRecord.conversation_id.desc())
    )
    return [
        {
            "conversation_id": conversation.conversation_id,
            "conversation_title": conversation.conversation_title,
            "agent_id": conversation.agent_id,
            "conversation_type": conversation_type,
            "create_time": int(created_ms),
            "update_time": int(updated_ms),
            "last_activity_time": (
                int(conversation_time_as_utc(conversation.last_activity_time).timestamp() * 1000)
                if conversation.last_activity_time is not None else int(created_ms)
            ),
            "pinned_at": conversation_time_as_utc(conversation.workbench_pinned_at).isoformat(),
        }
        for conversation, created_ms, updated_ms, conversation_type in rows
    ]


def list_workbench_pins(user_id: str, tenant_id: str) -> list[dict[str, Any]]:
    """Identity is authenticated by the service; preferences follow personal ownership."""
    with get_db_session() as session:
        return _list_pins(session, user_id)


def set_workbench_pin(conversation_id: int, pinned: bool, user_id: str, tenant_id: str) -> list[dict[str, Any]]:
    """Serialize personal pin writers without changing conversation activity/audit."""
    with get_db_session() as session:
        scope = json.dumps([user_id], separators=(",", ":"))
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"workbench-pins:{scope}"},
        )
        conversation = session.scalar(
            select(ConversationRecord)
            .where(
                ConversationRecord.conversation_id == conversation_id,
                *_owned_conversations(user_id),
            ).with_for_update()
        )
        if conversation is None:
            raise ConversationNotFoundError("Conversation not found")

        if pinned != (conversation.workbench_pinned_at is not None):
            pinned_at = None
            if pinned:
                newest = select(func.max(ConversationRecord.workbench_pinned_at)).where(
                    *_owned_conversations(user_id),
                ).scalar_subquery()
                pinned_at = session.scalar(select(func.greatest(
                    func.timezone("UTC", func.clock_timestamp()), newest + text("INTERVAL '1 microsecond'"),
                )))
            session.execute(
                update(ConversationRecord)
                .where(
                    ConversationRecord.conversation_id == conversation_id,
                    *_owned_conversations(user_id),
                ).values(
                    workbench_pinned_at=pinned_at,
                    # Explicitly suppress TableBase.onupdate for a personal preference.
                    update_time=ConversationRecord.update_time,
                )
            )
        return _list_pins(session, user_id)
