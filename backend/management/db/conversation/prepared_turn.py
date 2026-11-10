# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management-owned public conversation admission and projection markers."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, update

from contracts.agent import WorkbenchSessionConfig
from contracts.agentos import AgentRunReference, WorkbenchSkillLookup, WorkbenchSkillMounts
from contracts.constants.environment import ENABLE_AGENT_WORKBENCH
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, RuntimeMetadataVersionConflict, WorkbenchConfigVersionConflict, WorkbenchError
from infrastructure.rdb.agent_admission import AdmissionScopeError, ConversationRunAdmission
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_record import ConversationMessage, ConversationRecord
from infrastructure.rdb.conversation_state import tenant_membership_matches
from management.db.conversation.models import ConversationMessageUnit
from management.db.conversation.projection_receipt import ConversationProjectionReceipt
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
    memory_agent_id: int | None = None


@dataclass(frozen=True)
class LegacyResumeReceipt:
    run_id: str
    assistant_message_id: int
    status: str


@dataclass(frozen=True)
class LegacyTerminalMessage:
    assistant_message_id: int
    status: str


NO_ASSISTANT_MESSAGE = "no_assistant_message"
_TERMINAL_RESUME_STATUSES = ("completed", "failed", "stopped")


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
        (row.prepared_user_turn or {}).get("memory_agent_id"),
    )


def _pending(*conditions):
    admission = ConversationRunAdmission
    return select(admission).where(
        admission.prepared_message_index.is_not(None), admission.delete_flag == "N", *conditions,
    )


def _pending_for_conversation(session, conversation_id, user_id, tenant_id):
    admission = ConversationRunAdmission
    return session.scalar(_pending(
        admission.conversation_id == conversation_id,
        admission.created_by == user_id, admission.tenant_id == tenant_id,
    ).limit(1))


def pending_turn(conversation_id: int, user_id: str, tenant_id: str) -> PreparedTurn | None:
    with get_db_session() as session:
        if _owned(session, conversation_id, user_id, tenant_id) is None:
            raise AdmissionScopeError
        row = _pending_for_conversation(session, conversation_id, user_id, tenant_id)
        return _view(row) if row is not None else None


def _latest_message_id(conversation_id):
    message = ConversationMessage
    return select(message.message_id).where(
        message.conversation_id == conversation_id, message.delete_flag == "N",
    ).order_by(message.message_index.desc(), message.message_id.desc()).limit(1).correlate(None).scalar_subquery()


def read_cursorless_resume(
    conversation_id: int, user_id: str, tenant_id: str,
) -> PreparedTurn | LegacyResumeReceipt | LegacyTerminalMessage | str | None:
    """Resolve a pending turn, terminal projection, or absence of an assistant."""
    admission, message = ConversationRunAdmission, ConversationMessage
    with get_db_session() as session:
        conversation = _owned(session, conversation_id, user_id, tenant_id, lock=True)
        if conversation is None:
            raise AdmissionScopeError
        if not ENABLE_AGENT_WORKBENCH and conversation.workbench_config:
            raise WorkbenchError("WORKBENCH_DISABLED", status_code=404)
        row = _pending_for_conversation(session, conversation_id, user_id, tenant_id)
        if row is not None:
            return _view(row)

        # Inspect the latest message before filtering so an earlier assistant cannot mask a newer turn.
        terminal = session.scalar(select(message.status).join(
            admission, admission.prepared_assistant_id == message.message_id,
        ).where(
            message.message_id == _latest_message_id(conversation_id), message.created_by == user_id,
            message.message_role == "assistant", message.streaming_owner == "management",
            message.status.in_(_TERMINAL_RESUME_STATUSES),
            admission.conversation_id == conversation_id, admission.created_by == user_id,
            admission.tenant_id == tenant_id, admission.delete_flag == "N",
            admission.status == "admitted", admission.prepared_message_index.is_(None),
        ).limit(1))
        if terminal is not None:
            return terminal

        receipt = ConversationProjectionReceipt
        legacy_message = (
            message.message_id == _latest_message_id(conversation_id), message.created_by == user_id,
            message.message_role == "assistant", message.streaming_owner.is_distinct_from("management"),
            message.status.in_(_TERMINAL_RESUME_STATUSES),
        )
        legacy = session.execute(select(receipt.run_id, message.message_id, message.status).join(
            message, message.message_id == receipt.message_id,
        ).where(
            *legacy_message, receipt.created_by == user_id,
            receipt.tenant_id == tenant_id, receipt.delete_flag == "N",
        ).limit(2)).all()
        if len(legacy) == 1:
            return LegacyResumeReceipt(*legacy[0])
        if not legacy:
            terminal_message = session.execute(select(message.message_id, message.status).where(*legacy_message)).one_or_none()
            if terminal_message is not None:
                return LegacyTerminalMessage(*terminal_message)
        assistant = session.scalar(select(message.message_id).where(
            message.conversation_id == conversation_id, message.delete_flag == "N", message.message_role == "assistant",
        ).limit(1))
        return NO_ASSISTANT_MESSAGE if assistant is None else None


def read_legacy_resume_index(conversation_id: int, message_id: int, user_id: str, tenant_id: str) -> int | None:
    """Locate the last unit of the latest assistant message bound to the old run."""
    message, unit = ConversationMessage, ConversationMessageUnit
    with get_db_session() as session:
        if _owned(session, conversation_id, user_id, tenant_id) is None:
            raise AdmissionScopeError
        current = session.scalar(select(message.message_id).where(
            message.message_id == message_id, message.message_id == _latest_message_id(conversation_id),
            message.created_by == user_id, message.message_role == "assistant",
            message.streaming_owner.is_distinct_from("management"),
        ))
        if current is None:
            return None
        last = session.scalar(select(func.max(unit.unit_index)).where(
            unit.message_id == message_id, unit.conversation_id == conversation_id, unit.delete_flag == "N",
        ))
        return -1 if last is None else last


def read_workbench_skill_mounts(
    lookup: WorkbenchSkillLookup, user_id: str, tenant_id: str,
) -> WorkbenchSkillMounts | None:
    """Read only the overrides owned by a staged or confirmed Workbench turn."""
    admission, conversation = ConversationRunAdmission, ConversationRecord
    with get_db_session() as session:
        if not tenant_membership_matches(session, user_id, tenant_id):
            return None
        row = session.execute(select(
            admission.status, admission.prepared_user_turn, conversation.workbench_config,
            conversation.workbench_config_version,
        ).join(conversation, conversation.conversation_id == admission.conversation_id).where(
            admission.run_id == lookup.run_id, admission.conversation_id == lookup.conversation_id,
            admission.created_by == user_id, admission.tenant_id == tenant_id,
            admission.delete_flag == "N", admission.prepared_message_index.is_not(None),
            conversation.created_by == user_id, conversation.delete_flag == "N",
        )).one_or_none()
        if row is None:
            return None
        state = row.prepared_user_turn or {}
        if state.get("workbench_skill_root") != {"agent_id": lookup.agent_id, "version_no": lookup.agent_version}:
            return None
        config = None
        if row.status == "admitted" and row.workbench_config_version == lookup.workbench_version:
            config = row.workbench_config
        elif row.status == "dispatching":
            staged = state.get("workbench_update") or {}
            expected = lookup.workbench_version if state.get("new_conversation") else staged.get("expected_version")
            if staged.get("version") == lookup.workbench_version and row.workbench_config_version == expected:
                config = staged.get("config")
        if config is None:
            return None
        mounts = WorkbenchSessionConfig.model_validate(config).skill_mounts
        return WorkbenchSkillMounts(mounts=[mount.model_dump(mode="json") for mount in mounts])


def read_workbench_image_mounts(
    lookup: WorkbenchSkillLookup, user_id: str, tenant_id: str,
) -> dict[int, dict] | None:
    """Read current mounts for the conversation of an admitted image-producing run."""
    admission, conversation, message = ConversationRunAdmission, ConversationRecord, ConversationMessage
    with get_db_session() as session:
        if not tenant_membership_matches(session, user_id, tenant_id):
            return None
        config = session.scalar(select(conversation.workbench_config).select_from(conversation).join(
            admission, admission.conversation_id == conversation.conversation_id,
        ).join(message, message.message_id == admission.prepared_assistant_id).where(
            admission.run_id == lookup.run_id, admission.conversation_id == lookup.conversation_id,
            admission.created_by == user_id, admission.tenant_id == tenant_id, admission.status == "admitted",
            admission.delete_flag == "N", conversation.created_by == user_id, conversation.delete_flag == "N",
            conversation.workbench_config_version == lookup.workbench_version,
            message.conversation_id == conversation.conversation_id, message.created_by == user_id,
            message.message_role == "assistant", message.delete_flag == "N",
        ))
        if config is None:
            return None
        return {mount.skill_id: mount.config_values for mount in WorkbenchSessionConfig.model_validate(config).skill_mounts}


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
            row.prepared_user_turn = {
                key: user_turn[key] for key in ("memory_agent_id", "workbench_skill_root") if key in user_turn
            } or None
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
