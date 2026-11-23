# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise consent and source-message retention through the real admission transaction."""

import pytest
from sqlalchemy import delete

from infrastructure.rdb.agent_admission import AdmissionScopeError, ConversationRunAdmission
from infrastructure.rdb.conversation_record import ConversationMessage
from management.db.conversation import prepared_turn as store
from test.backend.database.test_prepared_saved_user import database, saved, stage
from contracts.agentos import AgentRunReference


def test_owner_can_change_only_their_consent(database):
    assert store.evolution_setting(42, "actor", "tenant") == {"enabled": False, "effective_at": None}
    enabled = store.evolution_setting(42, "actor", "tenant", True)
    assert enabled["enabled"] and enabled["effective_at"]
    assert store.evolution_setting(42, "actor", "tenant", True)["enabled"]
    for conversation, user, tenant in [(41, "actor", "tenant"), (42, "other", "tenant"), (42, "actor", "other")]:
        with pytest.raises(AdmissionScopeError):
            store.evolution_setting(conversation, user, tenant, False)
    assert store.evolution_setting(42, "actor", "tenant")["enabled"]


def test_retry_cannot_backfill_message_when_enabled_later(database):
    store.evolution_setting(42, "actor", "tenant", True)
    accepted = store.confirm_turn(stage(saved()))
    store.close_turn(accepted)
    with database.sessions() as session:
        assert session.get(ConversationRunAdmission, "scope").evolution_source_message_id is None


def test_setting_is_captured_when_turn_is_staged(database, monkeypatch):
    with database.sessions() as session:
        session.execute(delete(ConversationMessage))
    create_assistant = store.create_conversation_message

    def create_message(message, user, *, db_session, **options):
        if message["role"] == "assistant":
            return create_assistant(message, user, db_session=db_session, **options)
        db_session.add(ConversationMessage(
            message_id=24, conversation_id=42, message_role="user", message_index=0,
            message_content=message["content"], created_by=user, delete_flag="N",
        ))
        db_session.flush()
        return 24

    monkeypatch.setattr(store, "create_conversation_message", create_message)
    store.evolution_setting(42, "actor", "tenant", True)
    staged = store.stage_turn(
        "scope", AgentRunReference(conversation_id=42, run_id="a" * 32), "actor", "tenant", 0,
        {"query": "hello", "minio_files": [], "agent_id": 7, "chat_mode": "execution"},
    )
    store.evolution_setting(42, "actor", "tenant", False)
    store.close_turn(store.confirm_turn(staged))
    with database.sessions() as session:
        assert session.get(ConversationRunAdmission, "scope").evolution_source_message_id == 24
