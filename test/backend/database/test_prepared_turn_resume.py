# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read the current resumable turn without reviving an older assistant message."""

import pytest
from sqlalchemy import JSON, MetaData, delete
from sqlalchemy.dialects.postgresql import JSONB

from contracts.agentos import AgentRunReference, WorkbenchSkillLookup
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from infrastructure.rdb.agent_admission import AdmissionScopeError, ConversationRunAdmission
from infrastructure.rdb.conversation_record import ConversationMessage, ConversationMessageUnit, ConversationRecord
from management.db.conversation import prepared_turn as store
from management.db.conversation.projection_receipt import ConversationProjectionReceipt
from test.backend.database.test_prepared_saved_user import database, saved, stage

REFERENCE = AgentRunReference(conversation_id=42, run_id="a" * 32)


@pytest.fixture
def receipt_table(database):
    metadata = MetaData()
    table = ConversationProjectionReceipt.__table__.to_metadata(metadata, schema=None)
    for column in table.c:
        if isinstance(column.type, JSONB):
            column.type = JSON()
    with database.sessions() as session:
        metadata.create_all(session.get_bind())


def add_assistant(session, *, owner=None, status="completed"):
    session.add(ConversationMessage(
        message_id=61, conversation_id=42, message_index=1, message_role="assistant",
        message_content="finished", status=status, streaming_owner=owner,
        created_by="actor", updated_by="actor", delete_flag="N",
    ))


def add_receipt(session, run_id, *, tenant="tenant", deleted="N"):
    session.add(ConversationProjectionReceipt(
        run_id=run_id, message_id=61, tenant_id=tenant, payload_sha256="f" * 64, unit_ids={},
        created_by="actor", updated_by="actor", delete_flag=deleted,
    ))


def test_cursorless_resume_prefers_open_turn_then_managed_terminal(database):
    turn = stage(saved())
    assert store.read_cursorless_resume(42, "actor", "tenant") == turn
    confirmed = store.confirm_turn(turn)
    store.close_turn(confirmed, failure_status="failed")
    assert store.read_cursorless_resume(42, "actor", "tenant") == "failed"


@pytest.mark.parametrize("receipts,expected", [
    ([], store.LegacyTerminalMessage(61, "completed")),
    ([("a", "tenant", "N")], store.LegacyResumeReceipt("a" * 32, 61, "completed")),
    ([("a", "other", "N"), ("b", "tenant", "Y")], store.LegacyTerminalMessage(61, "completed")),
    ([("a", "tenant", "N"), ("b", "tenant", "N")], None),
])
def test_cursorless_resume_requires_a_unique_owned_legacy_receipt(database, receipt_table, receipts, expected):
    with database.sessions() as session:
        add_assistant(session)
        for run, tenant, deleted in receipts:
            add_receipt(session, run * 32, tenant=tenant, deleted=deleted)
    assert store.read_cursorless_resume(42, "actor", "tenant") == expected


def test_cursorless_resume_does_not_return_an_assistant_behind_the_head(database, receipt_table):
    assert store.read_cursorless_resume(42, "actor", "tenant") == store.NO_ASSISTANT_MESSAGE
    with database.sessions() as session:
        add_assistant(session)
        add_receipt(session, "a" * 32)
        session.add(ConversationMessage(
            message_id=62, conversation_id=42, message_index=2, message_role="user",
            message_content="the next request", created_by="actor", delete_flag="N",
        ))
    assert store.read_cursorless_resume(42, "actor", "tenant") is None
    assert store.read_legacy_resume_index(42, 61, "actor", "tenant") is None


def test_cursorless_resume_enforces_ownership_and_workbench_feature(database, monkeypatch):
    with pytest.raises(AdmissionScopeError):
        store.read_cursorless_resume(42, "actor", "other")
    with pytest.raises(AdmissionScopeError):
        store.read_legacy_resume_index(42, 61, "other", "tenant")
    with database.sessions() as session:
        session.get(ConversationRecord, 42).workbench_config = {"mode": "generic_chat"}
    monkeypatch.setattr(store, "ENABLE_AGENT_WORKBENCH", False)
    with pytest.raises(store.WorkbenchError, match="WORKBENCH_DISABLED"):
        store.read_cursorless_resume(42, "actor", "tenant")


@pytest.mark.parametrize("advance", [False, True])
def test_confirmation_applies_metadata_at_the_staged_version(database, advance):
    with database.sessions() as session:
        conversation = session.get(ConversationRecord, 42)
        conversation.runtime_metadata = {"phase": "initial"}
        conversation.runtime_metadata_version = 3
    turn = store.stage_turn(
        "scope", REFERENCE, "actor", "tenant", 0,
        {
            "query": "hello", "minio_files": [{"name": "file.txt"}], "agent_id": 7, "chat_mode": "planning",
            "metadata_update": {"expected_version": 3, "value": {"phase": "next", "_mcp_headers": {}}},
            "knowledge_update": {"expected": None, "value": {"local": {"mode": "disabled"}}},
            "automation": {"task_id": 5},
        }, saved_user=saved(),
    )
    if advance:
        with database.sessions() as session:
            conversation = session.get(ConversationRecord, 42)
            conversation.runtime_metadata_version = 4
        with pytest.raises(store.RuntimeMetadataVersionConflict):
            store.confirm_turn(turn)
        assert database.creates == []
    else:
        confirmed = store.confirm_turn(turn)
        assert store.automation_source(confirmed) == {
            "task_id": 5, "source_message_id": 23, "user_message": "hello",
        }
    with database.sessions() as session:
        conversation = session.get(ConversationRecord, 42)
        admission = session.get(ConversationRunAdmission, "scope")
        assert conversation.runtime_metadata_version == 4
        assert conversation.runtime_metadata == {"phase": "initial" if advance else "next"}
        if advance:
            assert conversation.knowledge_scope is None
            assert admission.prepared_assistant_id is None
        else:
            assert conversation.knowledge_scope == {"local": {"mode": "disabled"}}
            assert admission.prepared_assistant_id == 61


@pytest.mark.parametrize("consumer", ["cursorless", "automation", "background", "sweep"])
def test_admission_recovery_reads_the_same_staged_turn(database, consumer):
    turn = store.stage_turn(
        "scope", REFERENCE, "actor", "tenant", 0,
        {"query": "hello", "minio_files": [{"name": "file.txt"}], "agent_id": 7,
         "chat_mode": "execution", "automation": {"task_id": 9}},
        saved_user=saved(),
    )
    if consumer == "cursorless":
        pending = store.read_cursorless_resume(42, "actor", "tenant")
    elif consumer == "automation":
        pending = store.automation_turn(REFERENCE, "actor", "tenant")
        assert store.automation_turn(REFERENCE, "actor", "other") is None
        assert store.automation_source(turn) is None
    elif consumer == "background":
        pending = store.read_background_turn("scope", REFERENCE, "actor", "tenant")
        assert store.read_background_turn("different-scope", REFERENCE, "actor", "tenant") is None
    else:
        assert store.pending_turns(REFERENCE.run_id, 4) == []
        pending, = store.pending_turns("", 4)
    assert pending == turn


@pytest.mark.parametrize("version,owner", [(2, "actor"), (3, "actor"), (3, "other")])
def test_image_mounts_are_visible_only_at_admitted_conversation_revision(database, version, owner):
    config = {"mode": "generic_chat", "skill_mounts": [{"skill_id": 45, "config_values": {"size": "large"}}]}
    with database.sessions() as session:
        conversation = session.get(ConversationRecord, 42)
        conversation.workbench_config = config
        conversation.workbench_config_version = 3
    store.confirm_turn(stage(saved()))
    lookup = WorkbenchSkillLookup(
        **REFERENCE.model_dump(), agent_id=7, agent_version=1, workbench_version=version,
    )
    assert store.read_workbench_image_mounts(lookup, owner, "tenant") == (
        {45: {"size": "large"}} if version == 3 and owner == "actor" else None
    )


@pytest.mark.parametrize("race", [None, "new-head", "knowledge-scope", "workbench-version"])
def test_confirm_only_persists_new_messages_if_staged_scope_still_matches(database, mocker, race):
    state = {"schema_version": 4, "mode": "generic_chat"}
    with database.sessions() as session:
        conversation = session.get(ConversationRecord, 42)
        conversation.workbench_config = state
        conversation.workbench_config_version = 2
    turn = store.stage_turn(
        "scope", REFERENCE, "actor", "tenant", 2,
        {
            "query": "next", "minio_files": [], "agent_id": 7, "chat_mode": "execution",
            "annotations": [{"text": "quoted"}],
            "workbench_update": {"expected_version": 2, "version": 3, "config": {**state, "requested_output_tokens": 512}},
            "knowledge_update": {"expected": None, "value": {"local": {"mode": "disabled"}}},
        },
    )
    create = mocker.patch.object(store, "create_conversation_message", side_effect=[24, 61])
    if race == "new-head":
        with database.sessions() as session:
            add_assistant(session)
            session.get(ConversationMessage, 23).message_index = 2
    elif race == "knowledge-scope":
        with database.sessions() as session:
            session.get(ConversationRecord, 42).knowledge_scope = {"local": {"mode": "inherit"}}
    elif race == "workbench-version":
        with database.sessions() as session:
            session.get(ConversationRecord, 42).workbench_config_version = 3
    if race:
        conflict = store.WorkbenchConfigVersionConflict if race == "workbench-version" else store.PreparedTurnConflict
        with pytest.raises(conflict):
            store.confirm_turn(turn)
        create.assert_not_called()
    else:
        assert store.confirm_turn(turn).assistant_message_id == 61
        user, assistant = create.call_args_list
        assert user.args[0] == {
            "conversation_id": 42, "message_idx": 2, "role": "user", "content": "next",
            "minio_files": [], "annotations": [{"text": "quoted"}],
        }
        assert assistant.args[0]["message_idx"] == 3
        with database.sessions() as session:
            conversation = session.get(ConversationRecord, 42)
            assert conversation.workbench_config_version == 3
            assert conversation.workbench_config["requested_output_tokens"] == 512
            assert conversation.knowledge_scope == {"local": {"mode": "disabled"}}


@pytest.mark.parametrize("failed", [False, True])
def test_staged_clarification_keeps_the_original_prompt_through_confirmation(database, mocker, failed):
    clarification = {"form": {"schema_version": 1}, "answers": [{"questionId": "goal", "value": "answer"}]}
    database.clarification.side_effect = None
    database.clarification.return_value = {"source_message_id": 23, **clarification}
    turn = store.stage_turn(
        "scope", REFERENCE, "actor", "tenant", 2,
        {"query": "next", "minio_files": [], "agent_id": 7, "chat_mode": "execution",
         "clarification_response": clarification},
    )
    create = mocker.patch.object(store, "create_conversation_message", side_effect=(
        AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Clarification source changed") if failed else [24, 61]
    ))
    if failed:
        with pytest.raises(store.PreparedTurnConflict):
            store.confirm_turn(turn)
        create.assert_called_once()
        assert store.pending_turn(42, "actor", "tenant") == turn
    else:
        assert store.confirm_turn(turn).assistant_message_id == 61
        assert create.call_count == 2
    call = create.call_args_list[0]
    assert call.args[0]["clarification_response"] == clarification
    assert call.kwargs["expected_clarification_source_id"] == 23


def test_closed_unstarted_new_conversation_never_creates_history(database, mocker):
    with database.sessions() as session:
        session.execute(delete(ConversationMessage))
        session.execute(delete(ConversationRecord))

    def create(title, user, *, reserved_conversation_id, db_session, **kwargs):
        assert (title, user) == ("A new conversation", "actor")
        assert kwargs["selected_model_id"] == 11
        assert kwargs["model_parameter_preferences"] == {"11": {"temperature": 0}}
        db_session.add(ConversationRecord(conversation_id=reserved_conversation_id, created_by=user, delete_flag="N"))
        db_session.flush()

    mocker.patch.object(store, "create_conversation", side_effect=create)
    turn = store.stage_turn(
        "scope", REFERENCE, "actor", "tenant", 0,
        {"query": "question", "minio_files": [], "agent_id": 7, "chat_mode": "execution"},
        initial_title="A new conversation", selected_model_id=11, model_parameter_preferences={"11": {"temperature": 0}},
    )
    store.close_turn(turn)
    store.close_turn(turn)
    with database.sessions() as session:
        conversation = session.get(ConversationRecord, 42)
        admission = session.get(ConversationRunAdmission, "scope")
        assert conversation.delete_flag == "Y"
        assert (admission.status, admission.conversation_id, admission.journal_available) == ("rejected", None, False)
    assert database.creates == []


def test_legacy_resume_cursor_reads_only_live_units_of_the_latest_owned_assistant(database):
    definitions = MetaData()
    ConversationMessageUnit.__table__.to_metadata(definitions, schema=None)
    with database.sessions() as session:
        definitions.create_all(session.get_bind())
        add_assistant(session)
    assert store.read_legacy_resume_index(42, 61, "actor", "tenant") == -1
    with database.sessions() as session:
        for unit_id, conversation_id, index, deleted in [(1, 42, 4, "N"), (2, 42, 9, "Y"), (3, 43, 8, "N")]:
            session.add(ConversationMessageUnit(
                unit_id=unit_id, message_id=61, conversation_id=conversation_id, unit_index=index, delete_flag=deleted,
            ))
    assert store.read_legacy_resume_index(42, 61, "actor", "tenant") == 4
    assert store.next_message_index(42, "actor", "tenant") == 2
    with pytest.raises(AdmissionScopeError):
        store.next_message_index(42, "actor", "other")
