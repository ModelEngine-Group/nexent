# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep old background identity and assistant-only history under Management."""

import pytest
from sqlalchemy import select

from contracts.agentos import AgentRunReference
from infrastructure.rdb.agent_admission import AdmissionScopeError
from infrastructure.rdb.conversation_record import ConversationMessage
from management.db.conversation import prepared_turn as store
from test.backend.database.test_prepared_saved_user import database

REFERENCE = AgentRunReference(conversation_id=42, run_id="a" * 32)


def stage(user="actor", tenant="tenant"):
    return store.stage_turn(
        "scope", REFERENCE, user, tenant, 8,
        {"query": "background question", "minio_files": None, "agent_id": 7, "chat_mode": "execution"},
        omitted_user=True, background_run=True,
    )


def test_background_without_a_proven_source_keeps_original_index_and_origin(database):
    turn = stage()
    confirmed = store.confirm_turn(turn)
    assert confirmed.message_index == 9 and confirmed.message_source == "AUTOMATION"
    restored = store.read_background_turn("scope", REFERENCE, "actor", "tenant")
    assert restored.assistant_message_id == confirmed.assistant_message_id == 61
    store.close_turn(confirmed)
    closed = store.read_background_turn("scope", REFERENCE, "actor", "tenant")
    assert closed.message_index == 9 and closed.assistant_message_id == 61
    with database.sessions() as session:
        rows = session.scalars(select(ConversationMessage).order_by(ConversationMessage.message_id)).all()
        assert [(row.message_role, row.message_index, row.message_source) for row in rows] == [
            ("user", 0, "CHAT"), ("assistant", 9, "AUTOMATION"),
        ]
    assert len(database.creates) == 1
    database.quota.assert_not_called()
    database.clarification.assert_not_called()


@pytest.mark.parametrize("user,tenant", [("other", "tenant"), ("actor", "other")])
def test_background_cannot_stage_or_read_another_actors_conversation(database, user, tenant):
    with pytest.raises(AdmissionScopeError):
        stage(user, tenant)
    with pytest.raises(AdmissionScopeError):
        store.read_background_turn("scope", REFERENCE, user, tenant)
    assert not database.creates


def test_fixed_background_claim_keeps_the_original_id_and_rejects_changed_request(database, mocker):
    from infrastructure.rdb import agent_admission as claims

    mocker.patch.object(claims, "get_db_session", database.sessions)
    mocker.patch.object(claims, "tenant_membership_matches", return_value=True)
    first = claims.claim_conversation_run("background", "body", "actor", "tenant", requested_run_id="b" * 32)
    again = claims.claim_conversation_run("background", "body", "actor", "tenant", requested_run_id="b" * 32)
    assert first.run_id == again.run_id == "b" * 32 and first.acquired and not again.acquired
    for fingerprint, run_id in [("changed", "b" * 32), ("body", "c" * 32)]:
        with pytest.raises(claims.AdmissionRequestConflict):
            claims.claim_conversation_run("background", fingerprint, "actor", "tenant", requested_run_id=run_id)


@pytest.mark.parametrize("bound", [False, True])
def test_automation_memory_enqueue_requires_the_matching_background_admission(database, mocker, bound):
    from sqlalchemy import JSON, MetaData
    from sqlalchemy.dialects.postgresql import JSONB
    from infrastructure.rdb.agent_admission import ConversationRunAdmission
    from management.db.conversation import memory_completion, repository
    from management.db.conversation.projection_receipt import ConversationProjectionReceipt

    turn = store.stage_turn("scope", REFERENCE, "actor", "tenant", 8,
                            {"query": "hello", "minio_files": None, "agent_id": 7, "chat_mode": "execution",
                             "memory_agent_id": 7}, omitted_user=True, background_run=True)
    store.confirm_turn(turn)
    metadata = MetaData()
    copied = ConversationProjectionReceipt.__table__.to_metadata(metadata, schema=None)
    for column in copied.c:
        if isinstance(column.type, JSONB):
            column.type = JSON()
    with database.sessions() as session:
        metadata.create_all(session.get_bind())
        if not bound:
            session.get(ConversationRunAdmission, "scope").prepared_user_turn = None
    mocker.patch.object(repository, "get_db_session", database.sessions)
    mocker.patch("infrastructure.rdb.conversation_state.tenant_membership_matches", return_value=True)
    mocker.patch.object(repository, "_lock_projection_conversation")
    mocker.patch.object(repository, "persist_assistant_run_batch")
    enqueue = mocker.patch.object(memory_completion, "enqueue")
    arguments = dict(projection_run_id=REFERENCE.run_id, conversation_id=42, message_index=9,
                     message_source="AUTOMATION", user_id="actor", tenant_id="tenant", assistant_message_id=61,
                     memory_agent_id=7, terminal_status="completed", message_content="answer")
    if bound:
        assert repository.persist_prepared_assistant_projection(**arguments) == 61
        assert enqueue.call_args.args[1:] == (REFERENCE.run_id, 7, "actor", "completed", "answer")
        assert enqueue.call_args.kwargs == {"source_message_id": None}
    else:
        with pytest.raises(ValueError, match="original prompt"):
            repository.persist_prepared_assistant_projection(**arguments)
        enqueue.assert_not_called()
