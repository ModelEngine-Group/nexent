# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Confirm an existing prompt by its owned message head despite index gaps."""

import pytest
from sqlalchemy import select

from infrastructure.rdb.agent_admission import AdmissionScopeError
from infrastructure.rdb.conversation_record import ConversationMessage
from management.db.conversation import prepared_turn as store
from test.backend.database.test_prepared_saved_user import database


FILES = [{"name": "file.txt"}]


def read(user="actor", tenant="tenant", query="hello", files=FILES):
    return store.read_saved_user_turn_head(42, user, tenant, query, files)


def test_saved_head_uses_actual_index_without_appending_or_consuming_quota(database):
    with database.sessions() as session:
        source = session.get(ConversationMessage, 23)
        source.message_index = 12
        source.message_source = "AUTOMATION"
    assert read() == store.SavedUserTurn(23, 12, "AUTOMATION")
    with database.sessions() as session:
        assert list(session.scalars(select(ConversationMessage.message_id))) == [23]
    assert database.creates == []
    database.quota.assert_not_called()
    database.clarification.assert_not_called()


@pytest.mark.parametrize("invalid", ["assistant", "other-user", "unfinished", "unordered", "content", "files"])
def test_unprovable_head_cannot_be_adopted(database, invalid):
    if invalid in {"content", "files"}:
        with pytest.raises(store.PreparedTurnConflict):
            read(query="different" if invalid == "content" else "hello", files=[] if invalid == "files" else FILES)
    else:
        with database.sessions() as session:
            session.add(ConversationMessage(
                message_id=24, conversation_id=42, message_index=None if invalid == "unordered" else 2,
                message_role="assistant" if invalid == "assistant" else "user",
                status="streaming" if invalid == "unfinished" else "completed", message_content="hello",
                created_by="other" if invalid == "other-user" else "actor", message_source="AUTOMATION", delete_flag="N",
            ))
        with pytest.raises(store.PreparedTurnConflict):
            read()
    assert database.creates == []


@pytest.mark.parametrize("user,tenant", [("other", "tenant"), ("actor", "other")])
def test_saved_head_requires_current_user_and_tenant_membership(database, user, tenant):
    with pytest.raises(AdmissionScopeError):
        read(user=user, tenant=tenant)
