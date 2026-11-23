# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise consent and source-message retention through the real admission transaction."""

from datetime import datetime, timedelta, timezone

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


@pytest.mark.parametrize("withdrawn,expired,eligible", [(False, False, True), (True, False, False), (False, True, False)])
def test_retry_respects_original_grant_and_deadline(database, withdrawn, expired, eligible):
    store.evolution_setting(42, "actor", "tenant", True)
    until = datetime.now(timezone.utc) + timedelta(days=-1 if expired else 1)
    with database.sessions() as session:
        session.add(ConversationRunAdmission(
            scope_sha256="original", run_id="b" * 32, request_sha256="c" * 64, tenant_id="tenant",
            conversation_id=42, created_by="actor", updated_by="actor", delete_flag="N",
            evolution_source_message_id=23, evolution_grant_epoch=0, evolution_valid_until=until,
        ))
    store.evolution_setting(42, "actor", "tenant", False, revoke=withdrawn)
    store.evolution_setting(42, "actor", "tenant", True)
    store.close_turn(store.confirm_turn(stage(saved())))
    with database.sessions() as session:
        retry = session.get(ConversationRunAdmission, "scope")
        assert retry.evolution_source_message_id == (23 if eligible else None)
        if eligible:
            assert retry.evolution_valid_until.replace(tzinfo=timezone.utc) == until


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
