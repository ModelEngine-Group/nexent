# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import func, select

from contracts.constants.constants import ASSET_OWNER_ROLE, ASSET_OWNER_TENANT_ID, DEFAULT_TENANT_ID
from infrastructure.rdb.account_record import UserTenant
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_record import ConversationMessage, ConversationMessageUnit, ConversationRecord


def tenant_membership_matches(session, user_id: str, tenant_id: str) -> bool:
    """Verify the active tenant scope, including legacy empty-tenant accounts."""
    membership = session.execute(
        select(UserTenant.tenant_id, UserTenant.user_role)
        .where(UserTenant.user_id == user_id, UserTenant.delete_flag == "N")
        .limit(1)
    ).first()
    if membership is None:
        return False
    effective_tenant = membership.tenant_id
    if not effective_tenant:
        effective_tenant = (
            ASSET_OWNER_TENANT_ID if (membership.user_role or "").upper() == ASSET_OWNER_ROLE
            else DEFAULT_TENANT_ID
        )
    return effective_tenant == tenant_id


def conversation_belongs_to(conversation_id: int, *, user_id: str, tenant_id: str) -> bool:
    """Check the signed actor's active tenant membership and live conversation ownership."""
    with get_db_session() as session:
        if not tenant_membership_matches(session, user_id, tenant_id):
            return False
        return session.scalar(
            select(ConversationRecord.conversation_id)
            .where(
                ConversationRecord.conversation_id == conversation_id,
                ConversationRecord.created_by == user_id,
                ConversationRecord.delete_flag == "N",
            )
        ) is not None


def read_legacy_resume_state(conversation_id: int, user_id: str, tenant_id: str):
    """Read the persisted playback offset within the signed conversation scope."""
    message, unit = ConversationMessage, ConversationMessageUnit
    with get_db_session() as session:
        if not tenant_membership_matches(session, user_id, tenant_id):
            raise PermissionError("Conversation is not accessible to the current identity")
        conversation = session.execute(select(ConversationRecord.workbench_config).where(
            ConversationRecord.conversation_id == conversation_id,
            ConversationRecord.created_by == user_id,
            ConversationRecord.delete_flag == "N",
        )).one_or_none()
        if conversation is None:
            raise PermissionError("Conversation is not accessible to the current identity")

        last_unit = select(func.max(unit.unit_index)).where(
            unit.message_id == message.message_id, unit.delete_flag == "N",
        ).correlate(message).scalar_subquery()
        assistant = session.execute(select(message.status, last_unit).where(
            message.conversation_id == conversation_id, message.message_role == "assistant",
            message.delete_flag == "N",
        ).order_by(message.message_index.desc(), message.message_id.desc()).limit(1)).one_or_none()
        return bool(conversation.workbench_config), tuple(assistant) if assistant is not None else None


def fail_streaming_assistant_messages() -> list[dict]:
    """Mark assistant messages left streaming by a stopped runtime as failed.

    Returns the affected runtime identities so the caller can finish the
    corresponding short-lived Redis state with the existing runtime-state API.
    The conditional update makes repeated startup recovery idempotent.
    """
    from infrastructure.rdb.agent_execution import AgentExecution

    with get_db_session() as session:
        tracked_message = select(AgentExecution.run_id).where(
            AgentExecution.assistant_message_id == ConversationMessage.message_id,
            AgentExecution.delete_flag == "N",
        ).exists()
        rows = (
            session.query(
                ConversationMessage.message_id,
                ConversationMessage.conversation_id,
                ConversationMessage.created_by,
            )
            .filter(
                ConversationMessage.message_role == "assistant",
                ConversationMessage.status == "streaming",
                ConversationMessage.streaming_owner.is_distinct_from("management"),
                ConversationMessage.delete_flag == "N",
                ~tracked_message,
            )
            .with_for_update()
            .all()
        )
        if not rows:
            return []

        message_ids = [int(row.message_id) for row in rows]
        session.query(ConversationMessage).filter(
            ConversationMessage.message_id.in_(message_ids),
            ConversationMessage.status == "streaming",
            ConversationMessage.delete_flag == "N",
        ).update(
            {
                "status": "failed",
                "update_time": func.current_timestamp(),
            },
            synchronize_session=False,
        )
        return [
            {
                "message_id": int(row.message_id),
                "conversation_id": int(row.conversation_id),
                "user_id": row.created_by,
            }
            for row in rows
        ]
