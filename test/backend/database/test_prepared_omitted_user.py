# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep legacy assistant-only new conversations across admission and recovery."""

import pytest
from sqlalchemy import delete, select

from contracts.agentos import AgentRunReference
from infrastructure.rdb.conversation_record import ConversationMessage, ConversationRecord
from management.db.conversation import prepared_turn as store
from test.backend.database.test_prepared_saved_user import database


def empty_conversation(database, mocker):
    with database.sessions() as session:
        session.execute(delete(ConversationMessage))
        session.execute(delete(ConversationRecord))

    def create(title, user, *, reserved_conversation_id, db_session, **options):
        db_session.add(ConversationRecord(
            conversation_id=reserved_conversation_id, created_by=user, delete_flag="N",
        ))
        db_session.flush()

    mocker.patch.object(store, "create_conversation", side_effect=create)


def stage(index=0, *, memory=False, **options):
    return store.stage_turn(
        "scope", AgentRunReference(conversation_id=42, run_id="a" * 32), "actor", "tenant", index,
        {"query": "hello", "minio_files": None, "agent_id": 7, "chat_mode": "execution",
         **({"memory_agent_id": 7} if memory else {})},
        omitted_user=True, **options,
    )


@pytest.mark.parametrize("prior_users", [0, 4])
def test_only_assistant_is_confirmed_at_the_original_history_index(database, mocker, prior_users):
    empty_conversation(database, mocker)
    turn = stage(prior_users * 2, initial_title="Conversation")
    # Recover from the persisted marker rather than any request-local flag.
    restored = store.pending_turn(42, "actor", "tenant")
    first = store.confirm_turn(restored)
    again = store.confirm_turn(turn)
    assert first.assistant_message_id == again.assistant_message_id == 61
    assert first.message_index == prior_users * 2 + 1
    with database.sessions() as session:
        rows = session.scalars(select(ConversationMessage)).all()
        assert [(row.message_role, row.message_index) for row in rows] == [("assistant", prior_users * 2 + 1)]
    assert len(database.creates) == 1
    database.quota.assert_not_called()
    database.clarification.assert_not_called()


def test_existing_conversation_cannot_omit_a_user(database):
    with pytest.raises(store.PreparedTurnConflict):
        stage()
    assert not database.creates


@pytest.mark.parametrize("changed", [None, "agent", "tenant", "assistant", "lease"])
def test_memory_source_survives_projection_close_without_a_user_message(database, mocker, changed):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import JSON, MetaData
    from sqlalchemy.dialects.postgresql import JSONB
    from infrastructure.rdb.agent_admission import ConversationRunAdmission
    from management.db.conversation import memory_completion as queue
    from management.db.conversation.projection_receipt import ConversationProjectionReceipt

    empty_conversation(database, mocker)
    confirmed = store.confirm_turn(stage(initial_title="Conversation", memory=True))
    store.close_turn(confirmed)
    metadata = MetaData()
    for model in (queue.MemoryCompletion, ConversationProjectionReceipt):
        copied = model.__table__.to_metadata(metadata, schema=None)
        for column in copied.c:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    with database.sessions() as session:
        metadata.create_all(session.get_bind())
        session.get(ConversationMessage, 61).status = "completed"
        session.add(ConversationProjectionReceipt(
            run_id="a" * 32, message_id=61, tenant_id="tenant", payload_sha256="f" * 64, unit_ids={},
            created_by="actor", updated_by="actor", delete_flag="N",
        ))
        session.add(queue.MemoryCompletion(
            job_id="a" * 32 + ":final_answer", run_id="a" * 32, job_type="final_answer", agent_id=7,
            lease_token="b" * 32, next_attempt_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            created_by="actor", updated_by="actor", delete_flag="N",
        ))
        admission = session.get(ConversationRunAdmission, "scope")
        if changed == "agent":
            admission.prepared_user_turn = {**(admission.prepared_user_turn or {}), "memory_agent_id": 8}
        elif changed == "tenant":
            admission.tenant_id = "other"
        elif changed == "assistant":
            admission.prepared_assistant_id = 62
        elif changed == "lease":
            session.get(queue.MemoryCompletion, "a" * 32 + ":final_answer").lease_token = "c" * 32
    mocker.patch.object(queue, "get_db_session", database.sessions)
    mocker.patch.object(queue, "tenant_membership_matches", return_value=True)
    job = queue.MemoryJob("a" * 32, queue.FINAL_ANSWER, 7, "b" * 32, 1, None)
    source = queue.read_source(job)
    if changed is None:
        assert source is not None and source.query == "hello" and source.message_id == 61
    else:
        assert source is None


def test_new_message_before_confirmation_prevents_assistant_creation(database, mocker):
    empty_conversation(database, mocker)
    turn = stage(initial_title="Conversation")
    with database.sessions() as session:
        session.add(ConversationMessage(
            message_id=24, conversation_id=42, message_index=0, message_role="user", status="completed",
            message_content="another turn", created_by="actor", delete_flag="N",
        ))
    with pytest.raises(store.PreparedTurnConflict):
        store.confirm_turn(turn)
    assert not database.creates
