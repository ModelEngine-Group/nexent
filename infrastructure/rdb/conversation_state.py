# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import func, select

from contracts.constants.constants import ASSET_OWNER_ROLE, ASSET_OWNER_TENANT_ID, DEFAULT_TENANT_ID
from infrastructure.rdb.account_record import UserTenant
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_record import ConversationMessage, ConversationRecord


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
