# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json

from contracts.constants.constants import ASSET_OWNER_ROLE, ASSET_OWNER_TENANT_ID, DEFAULT_TENANT_ID
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

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


def load_execution_result_record(user_id: str, tenant_id: str, conversation_id: int,
                                 message_id: int, unit_index: int) -> dict:
    """Read one real execution unit under the current identity and conversation."""
    message, unit, conversation = ConversationMessage, ConversationMessageUnit, ConversationRecord
    membership = select(UserTenant.user_id).where(
        UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id, UserTenant.delete_flag == "N",
    ).exists()
    statement = select(unit.unit_type, unit.unit_content, unit.tool_call_id, unit.invocation_id).join(
        message, message.message_id == unit.message_id,
    ).join(conversation, conversation.conversation_id == message.conversation_id).where(
        membership, conversation.created_by == user_id, conversation.conversation_id == conversation_id,
        conversation.delete_flag == "N", message.message_id == message_id,
        message.message_role == "assistant", message.delete_flag == "N",
        unit.conversation_id == conversation_id, unit.unit_index == unit_index,
        unit.unit_type.in_(["execution_result", "tool_result"]), unit.delete_flag == "N",
    )
    with get_db_session() as session:
        rows = session.execute(statement).mappings().all()
    if not rows:
        raise PermissionError("Execution result is unavailable or not authorized")
    if len(rows) != 1:
        raise ValueError("Ambiguous execution result reference")
    row = rows[0]
    return {"record_type": row["unit_type"], "content": row["unit_content"],
            "tool_call_id": row["tool_call_id"], "invocation_id": row["invocation_id"]}


def list_checkpoint_execution_results(user_id, tenant_id, conversation_id, checkpoint_unit_id,
                                      covered_message_id, offset=0):
    """Page original result candidates only inside an authorized, loaded checkpoint."""
    message, unit, conversation = ConversationMessage, ConversationMessageUnit, ConversationRecord
    with get_db_session() as session:
        membership = select(UserTenant.user_id).where(
            UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id, UserTenant.delete_flag == "N",
        ).exists()
        checkpoint = session.execute(select(message.message_index, unit.unit_content).join(
            unit, unit.message_id == message.message_id,
        ).join(conversation, conversation.conversation_id == message.conversation_id).where(
            membership, conversation.conversation_id == conversation_id, conversation.created_by == user_id,
            conversation.delete_flag == "N", message.conversation_id == conversation_id,
            message.message_id == covered_message_id, message.message_role == "assistant",
            message.status == "completed", message.delete_flag == "N", unit.unit_id == checkpoint_unit_id,
            unit.conversation_id == conversation_id, unit.unit_type == "history_summary",
            unit.unit_status == "completed", unit.delete_flag == "N",
        )).one_or_none()
        try:
            payload = json.loads(checkpoint.unit_content) if checkpoint is not None else None
        except (TypeError, ValueError):
            payload = None
        if (not isinstance(payload, dict) or not isinstance(payload.get("summary"), dict)
                or payload.get("covered_through_message_id") != covered_message_id):
            raise PermissionError("History checkpoint is unavailable or not authorized")
        call = aliased(ConversationMessageUnit, name="source_call")
        duplicate_call = aliased(ConversationMessageUnit, name="matching_call")
        duplicate_result = aliased(ConversationMessageUnit, name="matching_result")

        def call_match(candidate):
            return and_(unit.unit_type == "tool_result", candidate.conversation_id == conversation_id,
                candidate.message_id == unit.message_id,
                candidate.unit_type == "tool", candidate.unit_status == "completed", candidate.delete_flag == "N",
                candidate.invocation_id.is_(None), candidate.tool_call_id == unit.tool_call_id,
                candidate.unit_index < unit.unit_index)

        call_count = select(func.count()).select_from(duplicate_call).where(
            call_match(duplicate_call)).correlate(unit).scalar_subquery()
        result_count = select(func.count()).select_from(duplicate_result).where(
            duplicate_result.conversation_id == conversation_id, duplicate_result.message_id == unit.message_id,
            duplicate_result.unit_index == unit.unit_index, duplicate_result.delete_flag == "N",
            duplicate_result.unit_type.in_(["execution_result", "tool_result"]),
        ).correlate(unit).scalar_subquery()
        rows = session.execute(select(
            unit.message_id, message.message_index, unit.unit_index, unit.unit_type,
            unit.tool_call_id, unit.invocation_id, call.unit_content.label("call_content"),
        ).join(message, message.message_id == unit.message_id).outerjoin(call, call_match(call)).where(
            message.conversation_id == conversation_id, message.message_role == "assistant",
            message.status == "completed", message.delete_flag == "N",
            message.message_index <= checkpoint.message_index,
            unit.conversation_id == conversation_id, unit.delete_flag == "N", unit.unit_status == "completed",
            unit.invocation_id.is_(None), unit.unit_type.in_(["execution_result", "tool_result"]),
            or_(unit.unit_type == "execution_result", call_count == 1), result_count == 1,
        ).order_by(message.message_index, unit.unit_index, unit.unit_id).offset(offset).limit(32)).all()
        return [{"message_id": row.message_id, "message_index": row.message_index, "unit_index": row.unit_index,
                 "record_type": row.unit_type, "tool_call_id": row.tool_call_id,
                 "invocation_id": row.invocation_id, "call_content": row.call_content}
                for row in rows], len(rows) == 32


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


def fail_streaming_assistant_messages(*, db_session=None) -> list[dict]:
    """Mark assistant messages left streaming by a stopped runtime as failed.

    Returns the affected runtime identities so the caller can finish the
    corresponding short-lived Redis state with the existing runtime-state API.
    The conditional update makes repeated startup recovery idempotent.
    """
    from infrastructure.rdb.agent_execution import AgentExecution

    with get_db_session(db_session) as session:
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
