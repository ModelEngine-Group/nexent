# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Atomic creation of an automation message and its run reference."""

from datetime import datetime, timezone

from sqlalchemy import select, update

from contracts.conversation import MessageSource
from management.db.automation.models import AgentAutomationRun
from management.db.client import get_db_session
from management.db.conversation import repository as conversation_db
from management.db.conversation.models import ConversationMessage, ConversationRecord
from management.utils.audit_fields import add_update_tracking


def create_run_message(
    run_id: int, message_data: dict, user_id: str, tenant_id: str,
) -> int:
    """Serialize with deletion and cancellation; commit both records or neither."""
    role = message_data["role"]
    if role not in {"user", "assistant"}:
        raise ValueError("Unsupported automation message role")
    conversation_id = int(message_data["conversation_id"])
    field = "user_message_id" if role == "user" else "assistant_message_id"
    with get_db_session() as session:
        # All message writers lock the conversation before messages. The run
        # lock prevents creation after cancellation and serializes retries.
        conversation = session.execute(select(ConversationRecord.conversation_id).where(
            ConversationRecord.conversation_id == conversation_id,
            ConversationRecord.created_by == user_id,
            ConversationRecord.delete_flag == "N",
        ).with_for_update()).scalar_one_or_none()
        if conversation is None:
            raise ValueError("Automation conversation is unavailable")
        run = session.execute(select(AgentAutomationRun).where(
            AgentAutomationRun.run_id == run_id,
            AgentAutomationRun.conversation_id == conversation_id,
            AgentAutomationRun.tenant_id == tenant_id,
            AgentAutomationRun.user_id == user_id,
            AgentAutomationRun.delete_flag == "N",
        ).with_for_update()).scalar_one_or_none()
        if run is None or run.status != "RUNNING":
            raise ValueError("Automation run is no longer active")
        message_id = getattr(run, field)
        if message_id is not None:
            existing = session.execute(select(ConversationMessage).where(
                ConversationMessage.message_id == message_id,
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.created_by == user_id,
                ConversationMessage.message_role == role,
                ConversationMessage.message_source == MessageSource.AUTOMATION.value,
                ConversationMessage.delete_flag == "N",
            )).scalar_one_or_none()
            if existing is None or (role == "user" and existing.message_content != message_data["content"]):
                raise ValueError("Automation message reference conflicts with this execution")
            return message_id
        if role == "assistant":
            prompt_index = session.execute(select(ConversationMessage.message_index).where(
                ConversationMessage.message_id == run.user_message_id,
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.created_by == user_id,
                ConversationMessage.message_role == "user",
                ConversationMessage.message_source == MessageSource.AUTOMATION.value,
                ConversationMessage.delete_flag == "N",
            )).scalar_one_or_none()
            if prompt_index is None:
                raise ValueError("Automation prompt is unavailable")
            message_data = {**message_data, "message_idx": prompt_index + 1}
        message_id = conversation_db.create_conversation_message(
            message_data, user_id, status="completed" if role == "user" else "streaming",
            message_source=MessageSource.AUTOMATION, db_session=session,
        )
        values = {field: message_id, "update_time": datetime.now(timezone.utc)}
        if role == "user":
            conversation_db.create_message_unit(
                message_id, conversation_id, 0, "automation_prompt", message_data["content"],
                user_id=user_id, db_session=session,
            )
            values["generated_prompt"] = message_data["content"]
        session.execute(update(AgentAutomationRun).where(
            AgentAutomationRun.run_id == run_id,
        ).values(**add_update_tracking(values, user_id)))
        return message_id
