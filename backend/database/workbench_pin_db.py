"""Transactional account-scoped Workbench pin persistence."""

import json
from typing import Any

from sqlalchemy import func, select, text

from consts.exceptions import ConversationNotFoundError
from database.client import get_db_session
from database.db_models import ConversationRecord, ConversationWorkbenchPin


def _list_pins(session, user_id: str, tenant_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(
            ConversationWorkbenchPin, ConversationRecord,
            func.extract("epoch", ConversationRecord.create_time) * 1000,
            func.extract("epoch", ConversationRecord.update_time) * 1000,
        )
        .join(ConversationRecord, ConversationRecord.conversation_id == ConversationWorkbenchPin.conversation_id)
        .where(
            ConversationWorkbenchPin.user_id == user_id,
            ConversationWorkbenchPin.tenant_id == tenant_id,
            ConversationWorkbenchPin.delete_flag == "N",
            ConversationRecord.created_by == user_id,
            ConversationRecord.delete_flag == "N",
            ConversationRecord.workbench_config.is_not(None),
            ConversationRecord.workbench_config != text("'null'::jsonb"),
        )
        .order_by(ConversationWorkbenchPin.pinned_at.desc(), ConversationWorkbenchPin.pin_id.desc())
    )
    return [
        {
            "conversation_id": conversation.conversation_id,
            "conversation_title": conversation.conversation_title,
            "agent_id": conversation.agent_id,
            "create_time": int(created_ms),
            "update_time": int(updated_ms),
            "pinned_at": pin.pinned_at.isoformat(),
        }
        for pin, conversation, created_ms, updated_ms in rows
    ]


def list_workbench_pins(user_id: str, tenant_id: str) -> list[dict[str, Any]]:
    with get_db_session() as session:
        return _list_pins(session, user_id, tenant_id)


def set_workbench_pin(conversation_id: int, pinned: bool, user_id: str, tenant_id: str) -> list[dict[str, Any]]:
    """Serialize scope writers and return the committed canonical ordering."""
    with get_db_session() as session:
        scope = json.dumps([tenant_id, user_id], separators=(",", ":"))
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"workbench-pins:{scope}"},
        )
        conversation = session.scalar(
            select(ConversationRecord.conversation_id).where(
                ConversationRecord.conversation_id == conversation_id,
                ConversationRecord.created_by == user_id,
                ConversationRecord.delete_flag == "N",
                ConversationRecord.workbench_config.is_not(None),
                ConversationRecord.workbench_config != text("'null'::jsonb"),
            ).with_for_update()
        )
        if conversation is None:
            raise ConversationNotFoundError("Workbench conversation not found")

        pin = session.scalar(
            select(ConversationWorkbenchPin).where(
                ConversationWorkbenchPin.user_id == user_id,
                ConversationWorkbenchPin.tenant_id == tenant_id,
                ConversationWorkbenchPin.conversation_id == conversation_id,
            ).order_by(ConversationWorkbenchPin.pin_id.desc())
        )
        if pinned and (pin is None or pin.delete_flag != "N"):
            newest = select(func.max(ConversationWorkbenchPin.pinned_at)).where(
                ConversationWorkbenchPin.user_id == user_id,
                ConversationWorkbenchPin.tenant_id == tenant_id,
            ).scalar_subquery()
            pinned_at = session.scalar(select(func.greatest(
                func.clock_timestamp(), newest + text("INTERVAL '1 microsecond'"),
            )))
            if pin is None:
                pin = ConversationWorkbenchPin(
                    user_id=user_id, tenant_id=tenant_id, conversation_id=conversation_id,
                    created_by=user_id,
                )
                session.add(pin)
            pin.pinned_at = pinned_at
            pin.delete_flag = "N"
            pin.updated_by = user_id
            pin.update_time = func.now()
        elif not pinned and pin is not None and pin.delete_flag == "N":
            pin.delete_flag = "Y"
            pin.updated_by = user_id
            pin.update_time = func.now()
        session.flush()
        return _list_pins(session, user_id, tenant_id)
