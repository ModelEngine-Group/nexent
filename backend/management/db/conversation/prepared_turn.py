# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management-owned public conversation admission and projection markers."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, update

from contracts.agentos import AgentRunReference
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, RuntimeMetadataVersionConflict, WorkbenchConfigVersionConflict
from infrastructure.rdb.agent_admission import AdmissionScopeError, ConversationRunAdmission
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_record import ConversationMessage, ConversationRecord
from infrastructure.rdb.conversation_state import tenant_membership_matches
from management.db.conversation.repository import (
    _assert_workbench_topology, _enforce_conversation_turn_limit, _lock_conversation_limit_scope,
    _resolve_clarification_response,
    create_conversation, create_conversation_message,
)


class PreparedTurnConflict(ValueError):
    """The conversation changed before the prepared turn could be accepted."""


@dataclass(frozen=True)
class PreparedTurn:
    reference: AgentRunReference
    user_id: str
    tenant_id: str
    message_index: int
    assistant_message_id: int | None
    staged_at: datetime


def _owned(session, conversation_id, user_id, tenant_id, *, lock=False):
    if not tenant_membership_matches(session, user_id, tenant_id):
        return None
    statement = select(ConversationRecord).where(
        ConversationRecord.conversation_id == conversation_id,
        ConversationRecord.created_by == user_id,
        ConversationRecord.delete_flag == "N",
    )
    return session.scalar(statement.with_for_update() if lock else statement)


def _next_index(session, conversation_id):
    last = session.scalar(select(func.max(ConversationMessage.message_index)).where(
        ConversationMessage.conversation_id == conversation_id, ConversationMessage.delete_flag == "N",
    ))
    return 0 if last is None else 2 * (last // 2 + 1)


def allocate_conversation_id() -> int:
    """Reserve a sequence value without exposing a conversation before compilation."""
    sequence = ConversationRecord.__table__.c.conversation_id.default
    with get_db_session() as session:
        return session.scalar(select(sequence.next_value()))


def next_message_index(conversation_id: int, user_id: str, tenant_id: str) -> int:
    with get_db_session() as session:
        if _owned(session, conversation_id, user_id, tenant_id) is None:
            raise AdmissionScopeError
        return _next_index(session, conversation_id)


def _view(row, *, message_index=None):
    return PreparedTurn(
        AgentRunReference(conversation_id=row.conversation_id, run_id=row.run_id),
        row.created_by, row.tenant_id,
        row.prepared_message_index if message_index is None else message_index, row.prepared_assistant_id,
        row.update_time.replace(tzinfo=timezone.utc) if row.update_time.tzinfo is None else row.update_time,
    )


def _pending(*conditions):
    admission = ConversationRunAdmission
    return select(admission).where(
        admission.prepared_message_index.is_not(None), admission.delete_flag == "N", *conditions,
    )


def pending_turn(conversation_id: int, user_id: str, tenant_id: str) -> PreparedTurn | None:
    admission = ConversationRunAdmission
    with get_db_session() as session:
        if _owned(session, conversation_id, user_id, tenant_id) is None:
            raise AdmissionScopeError
        row = session.scalar(_pending(admission.conversation_id == conversation_id,
                                      admission.created_by == user_id, admission.tenant_id == tenant_id).limit(1))
        return _view(row) if row is not None else None


def _require_metadata_version(conversation: ConversationRecord, expected: int) -> None:
    current = conversation.runtime_metadata_version or 0
    if current != expected:
        raise RuntimeMetadataVersionConflict(current)


def _require_workbench_version(conversation: ConversationRecord, expected: int, config: dict) -> None:
    current = conversation.workbench_config_version or 0
    if current != expected:
        raise WorkbenchConfigVersionConflict(current, deepcopy(conversation.workbench_config))
    _assert_workbench_topology(conversation, config)


def stage_turn(
    scope: str, reference: AgentRunReference, user_id: str, tenant_id: str, message_index: int, user_turn: dict,
    *, initial_title: str | None = None,
) -> PreparedTurn:
    admission = ConversationRunAdmission
    workbench = user_turn.get("workbench_update")
    knowledge = user_turn.get("knowledge_update")
    clarification = user_turn.get("clarification_response")
    with get_db_session() as session:
        if initial_title is None:
            if _owned(session, reference.conversation_id, user_id, tenant_id) is None:
                raise AdmissionScopeError
            # Keep the legacy order of quota lock followed by conversation row.
            _enforce_conversation_turn_limit(session, reference.conversation_id, "user", user_id)
            conversation = _owned(session, reference.conversation_id, user_id, tenant_id, lock=True)
            if conversation is None:
                raise AdmissionScopeError
            if (session.scalar(_pending(admission.conversation_id == reference.conversation_id).limit(1)) is not None
                    or _next_index(session, reference.conversation_id) != message_index):
                raise PreparedTurnConflict
            if workbench is not None:
                _require_workbench_version(conversation, workbench["expected_version"], workbench["config"])
            if knowledge is not None and conversation.knowledge_scope != knowledge["expected"]:
                raise PreparedTurnConflict
            if (metadata_update := user_turn.get("metadata_update")) is not None:
                _require_metadata_version(conversation, metadata_update["expected_version"])
            if clarification is not None:
                resolved = _resolve_clarification_response(
                    session, reference.conversation_id, user_id, "user", clarification,
                )
                source_id = resolved.pop("source_message_id")
                user_turn = {
                    **user_turn, "clarification_response": resolved, "clarification_source_id": source_id,
                }
        elif clarification is not None:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Clarification requires an existing conversation")
        elif not tenant_membership_matches(session, user_id, tenant_id):
            raise AdmissionScopeError
        row = session.scalar(select(admission).where(
            admission.scope_sha256 == scope, admission.run_id == reference.run_id,
            admission.created_by == user_id, admission.tenant_id == tenant_id,
            admission.delete_flag == "N", admission.status == "pending",
        ).with_for_update())
        if row is None or row.conversation_id is not None:
            raise AdmissionScopeError
        if initial_title is not None:
            if message_index != 0:
                raise PreparedTurnConflict
            create_conversation(
                initial_title, user_id, agent_id=user_turn["agent_id"], chat_mode=user_turn["chat_mode"],
                workbench_config=workbench["config"] if workbench is not None else None,
                knowledge_scope=(workbench["config"].get("knowledge_scope") if workbench is not None
                                 else knowledge["value"] if knowledge is not None else None),
                reserved_conversation_id=reference.conversation_id, db_session=session,
            )
        row.status = "dispatching"
        row.conversation_id = reference.conversation_id
        row.prepared_automation_context = user_turn.get("automation")
        row.prepared_user_turn = {
            **{key: value for key, value in user_turn.items() if key != "automation"},
            "new_conversation": initial_title is not None,
        }
        row.prepared_message_index = message_index + 1
        row.update_time = datetime.now(timezone.utc).replace(tzinfo=None)
        return _view(row)


def _turn_scope(turn):
    admission = ConversationRunAdmission
    return (
        admission.run_id == turn.reference.run_id, admission.conversation_id == turn.reference.conversation_id,
        admission.created_by == turn.user_id, admission.tenant_id == turn.tenant_id, admission.delete_flag == "N",
    )


def confirm_turn(turn: PreparedTurn) -> PreparedTurn | None:
    conversation_id = turn.reference.conversation_id
    with get_db_session() as session:
        _lock_conversation_limit_scope(session, f"conversation-turn-limit:{conversation_id}")
        conversation = _owned(session, conversation_id, turn.user_id, turn.tenant_id, lock=True)
        if conversation is None:
            raise AdmissionScopeError
        row = session.scalar(select(ConversationRunAdmission).where(*_turn_scope(turn)).with_for_update())
        if row is None or (row.prepared_assistant_id is None and row.prepared_message_index is None):
            return None
        if row.prepared_message_index is None:
            return _view(row, message_index=turn.message_index)
        if row.prepared_assistant_id is None:
            if _next_index(session, conversation_id) != row.prepared_message_index - 1:
                raise PreparedTurnConflict
            user_turn = row.prepared_user_turn
            workbench = user_turn.get("workbench_update")
            knowledge = user_turn.get("knowledge_update")
            metadata_update = user_turn.get("metadata_update")
            if knowledge is not None:
                expected = knowledge["value"] if user_turn["new_conversation"] else knowledge["expected"]
                if conversation.knowledge_scope != expected:
                    raise PreparedTurnConflict
            if workbench is not None:
                config = workbench["config"]
                config_version = workbench["version"] if user_turn["new_conversation"] else workbench["expected_version"]
                _require_workbench_version(conversation, config_version, config)
            if metadata_update is not None:
                metadata_version = metadata_update["expected_version"]
                _require_metadata_version(conversation, metadata_version)

            if workbench is not None and (config != conversation.workbench_config or metadata_update is not None):
                conversation.workbench_config = config
                conversation.workbench_config_version = workbench["version"]
                conversation.knowledge_scope = config.get("knowledge_scope")
                conversation.updated_by = turn.user_id
                conversation.update_time = func.now()
            if knowledge is not None and conversation.knowledge_scope != knowledge["value"]:
                conversation.knowledge_scope = knowledge["value"]
                conversation.updated_by = turn.user_id
                conversation.update_time = func.now()
            if metadata_update is not None:
                conversation.runtime_metadata = metadata_update["value"]
                conversation.runtime_metadata_version = metadata_version + 1
                conversation.updated_by = turn.user_id
                conversation.update_time = func.now()
            user_message = {
                "conversation_id": conversation_id, "message_idx": row.prepared_message_index - 1,
                "role": "user", "content": user_turn["query"], "minio_files": user_turn["minio_files"],
            }
            clarification = user_turn.get("clarification_response")
            options = {}
            if clarification is not None:
                user_message["clarification_response"] = clarification
                options["expected_clarification_source_id"] = user_turn["clarification_source_id"]
            try:
                source_message_id = create_conversation_message(user_message, turn.user_id, db_session=session, **options)
            except AppException as exc:
                if clarification is None or exc.error_code != ErrorCode.COMMON_VALIDATION_ERROR:
                    raise
                raise PreparedTurnConflict from exc
            row.prepared_assistant_id = create_conversation_message({
                "conversation_id": conversation_id, "message_idx": row.prepared_message_index,
                "role": "assistant", "content": "",
            }, turn.user_id, status="streaming", streaming_owner="management", db_session=session)
            conversation.chat_mode = user_turn["chat_mode"]
            if workbench is None:
                conversation.agent_id = user_turn["agent_id"]
            row.prepared_user_turn = None
            if row.prepared_automation_context is not None:
                row.prepared_automation_context = {
                    **row.prepared_automation_context, "source_message_id": source_message_id,
                }
            row.status = "admitted"
            row.journal_available = True
        return _view(row)


def close_turn(turn: PreparedTurn, *, failure_status: str | None = None) -> None:
    with get_db_session() as session:
        conversation_id = turn.reference.conversation_id
        conversation = _owned(session, conversation_id, turn.user_id, turn.tenant_id, lock=True)
        row = session.scalar(_pending(*_turn_scope(turn)).with_for_update())
        if row is None:
            return
        if row.prepared_assistant_id is None:
            row.status = "rejected"
            row.journal_available = False
            if (conversation is not None and (row.prepared_user_turn or {}).get("new_conversation")
                    and _next_index(session, conversation_id) == 0):
                conversation.delete_flag = "Y"
                conversation.updated_by = turn.user_id
                row.conversation_id = None
        elif failure_status is not None and conversation is not None:
            message = ConversationMessage
            session.execute(update(message).where(
                message.message_id == row.prepared_assistant_id, message.conversation_id == conversation_id,
                message.created_by == turn.user_id, message.message_role == "assistant",
                message.streaming_owner == "management", message.status == "streaming", message.delete_flag == "N",
            ).values(status=failure_status, updated_by=turn.user_id, update_time=func.now()))
        row.prepared_user_turn = None
        row.prepared_automation_context = None
        row.prepared_message_index = None


def pending_turns(after_run_id: str, limit: int) -> list[PreparedTurn]:
    admission = ConversationRunAdmission
    with get_db_session() as session:
        rows = session.scalars(
            _pending(admission.run_id > after_run_id).order_by(admission.run_id).limit(limit)
        )
        return [_view(row) for row in rows]

def automation_turn(reference: AgentRunReference, user_id: str, tenant_id: str) -> PreparedTurn | None:
    admission = ConversationRunAdmission
    with get_db_session() as session:
        if _owned(session, reference.conversation_id, user_id, tenant_id) is None:
            return None
        row = session.scalar(_pending(
            admission.run_id == reference.run_id, admission.conversation_id == reference.conversation_id,
            admission.created_by == user_id, admission.tenant_id == tenant_id,
            admission.prepared_automation_context.is_not(None),
        ))
        return _view(row) if row is not None else None


def automation_source(turn: PreparedTurn) -> dict | None:
    with get_db_session() as session:
        if _owned(session, turn.reference.conversation_id, turn.user_id, turn.tenant_id) is None:
            return None
        row = session.scalar(_pending(*_turn_scope(turn)))
        if row is None or row.status != "admitted" or not row.prepared_automation_context:
            return None
        context = row.prepared_automation_context
        message = session.scalar(select(ConversationMessage).where(
            ConversationMessage.message_id == context["source_message_id"],
            ConversationMessage.conversation_id == turn.reference.conversation_id,
            ConversationMessage.created_by == turn.user_id, ConversationMessage.message_role == "user",
            ConversationMessage.message_index == row.prepared_message_index - 1,
            ConversationMessage.status == "completed", ConversationMessage.delete_flag == "N",
        ))
        return {**context, "user_message": message.message_content} if message is not None else None
