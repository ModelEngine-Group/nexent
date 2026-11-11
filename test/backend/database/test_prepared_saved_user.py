# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserve an owned saved user turn while Management accepts its execution."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import JSON, DefaultClause, MetaData, create_engine, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from contracts.agentos import AgentRunReference
from infrastructure.rdb.agent_admission import AdmissionScopeError, ConversationRunAdmission
from infrastructure.rdb.conversation_record import ConversationMessage, ConversationRecord
from management.db.conversation import prepared_turn as store


@pytest.fixture
def database(mocker):
    schema = ConversationMessage.__table__.schema
    engine = create_engine("sqlite://", execution_options={"schema_translate_map": {schema: None}})
    metadata = MetaData()
    for model in (ConversationRecord, ConversationMessage, ConversationRunAdmission):
        copied = model.__table__.to_metadata(metadata, schema=None)
        for column in copied.c:
            if isinstance(column.type, JSONB):
                column.type = JSON()
                if column.server_default is not None:
                    column.server_default = DefaultClause(text(str(column.server_default.arg).replace("::jsonb", "")))
    metadata.create_all(engine)

    @contextmanager
    def sessions():
        with Session(engine) as session, session.begin():
            yield session

    mocker.patch.object(store, "get_db_session", sessions)
    mocker.patch.object(store, "tenant_membership_matches", side_effect=lambda session, user, tenant: (user, tenant) == ("actor", "tenant"))
    quota = mocker.patch.object(store, "_enforce_conversation_turn_limit")
    mocker.patch.object(store, "_lock_conversation_limit_scope")
    clarification = mocker.patch.object(store, "_resolve_clarification_response", side_effect=AssertionError("saved twice"))
    creates = []

    def create(message, user, *, db_session, status, streaming_owner, message_source="CHAT"):
        assert message["role"] == "assistant" and status == "streaming" and streaming_owner == "management"
        creates.append(message)
        db_session.add(ConversationMessage(
            message_id=61, conversation_id=message["conversation_id"], message_index=message["message_idx"],
            message_role="assistant", message_content="", message_source=message_source, status=status,
            streaming_owner=streaming_owner, created_by=user, updated_by=user, delete_flag="N",
        ))
        db_session.flush()
        return 61

    mocker.patch.object(store, "create_conversation_message", side_effect=create)
    with sessions() as session:
        session.add(ConversationRecord(conversation_id=42, created_by="actor", delete_flag="N"))
        session.add(ConversationMessage(
            message_id=23, conversation_id=42, message_index=0, message_role="user", status="completed",
            message_content="hello", minio_files=json.dumps([{"name": "file.txt"}]), message_source="CHAT",
            created_by="actor", updated_by="actor", delete_flag="N",
        ))
        session.add(ConversationRunAdmission(
            scope_sha256="scope", run_id="a" * 32, request_sha256="fingerprint", status="pending",
            created_by="actor", updated_by="actor", tenant_id="tenant", delete_flag="N",
        ))
    yield SimpleNamespace(sessions=sessions, creates=creates, quota=quota, clarification=clarification)
    engine.dispose()


def saved():
    return store.read_saved_user_turn(42, "actor", "tenant", 0, "hello", [{"name": "file.txt"}])


def stage(source):
    return store.stage_turn(
        "scope", AgentRunReference(conversation_id=42, run_id="a" * 32), "actor", "tenant", 0,
        {"query": "hello", "minio_files": [{"name": "file.txt"}], "agent_id": 7, "chat_mode": "execution",
         "clarification_response": {"already": "persisted"}}, saved_user=source,
    )


@pytest.mark.parametrize("source", ["CHAT", "AUTOMATION"])
def test_confirm_saved_user_creates_one_adjacent_assistant_and_is_idempotent(database, source):
    with database.sessions() as session:
        session.get(ConversationMessage, 23).message_source = source
    original = saved()
    assert (original.message_id, original.message_index, original.message_source) == (23, 0, source)
    turn = stage(original)
    first = store.confirm_turn(turn)
    second = store.confirm_turn(turn)
    assert first.assistant_message_id == second.assistant_message_id == 61
    assert first.message_index == 1
    with database.sessions() as session:
        rows = session.scalars(select(ConversationMessage).order_by(ConversationMessage.message_index)).all()
        assert [(row.message_id, row.message_role, row.message_source) for row in rows] == [
            (23, "user", source), (61, "assistant", source),
        ]
    assert len(database.creates) == 1
    database.quota.assert_not_called()
    database.clarification.assert_not_called()
    # Retrying the signed request can still locate its already answered source.
    assert saved() == original


@pytest.mark.parametrize("user,tenant", [("other", "tenant"), ("actor", "other")])
def test_foreign_saved_turn_is_rejected_before_staging(database, user, tenant):
    with pytest.raises(AdmissionScopeError):
        store.read_saved_user_turn(42, user, tenant, 0, "hello", [{"name": "file.txt"}])
    assert database.creates == []


@pytest.mark.parametrize("change", ["text", "files", "source", "deleted", "position", "assistant"])
def test_saved_user_changes_before_confirmation_never_create_an_assistant(database, change):
    turn = stage(saved())
    with database.sessions() as session:
        row = session.get(ConversationMessage, 23)
        if change == "text":
            row.message_content = "changed"
        elif change == "files":
            row.minio_files = "[]"
        elif change == "source":
            row.message_source = "AUTOMATION"
        elif change == "deleted":
            row.delete_flag = "Y"
        elif change == "position":
            row.message_index = 2
        else:
            session.add(ConversationMessage(
                message_id=60, conversation_id=42, message_index=1, message_role="assistant",
                created_by="actor", delete_flag="N",
            ))
    with pytest.raises(store.PreparedTurnConflict):
        store.confirm_turn(turn)
    assert database.creates == []


@pytest.mark.parametrize("query,files", [("changed", [{"name": "file.txt"}]), ("hello", [])])
def test_mismatched_saved_input_is_rejected(database, query, files):
    with pytest.raises(store.PreparedTurnConflict):
        store.read_saved_user_turn(42, "actor", "tenant", 0, query, files)
    assert database.creates == []


def test_same_saved_user_cannot_stage_two_runs(database):
    source = saved()
    first = stage(source)
    with pytest.raises(store.PreparedTurnConflict):
        stage(source)
    assert store.confirm_turn(first).assistant_message_id == 61
    assert len(database.creates) == 1
