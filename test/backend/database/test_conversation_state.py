# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from contracts.constants.constants import ASSET_OWNER_ROLE, ASSET_OWNER_TENANT_ID, DEFAULT_TENANT_ID
from infrastructure.rdb import conversation_state
from infrastructure.rdb.conversation_state import fail_streaming_assistant_messages


@pytest.fixture
def mock_session_ctx(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(conversation_state, "get_db_session", lambda: nullcontext(session))
    return session


@pytest.mark.parametrize(("membership", "tenant_id", "conversation_id", "owned"), [
    (None, "tenant-a", 10, False),
    (SimpleNamespace(tenant_id="tenant-b", user_role=None), "tenant-a", 10, False),
    (SimpleNamespace(tenant_id="tenant-a", user_role=None), "tenant-a", None, False),
    (SimpleNamespace(tenant_id="tenant-a", user_role=None), "tenant-a", 10, True),
    (SimpleNamespace(tenant_id="", user_role=ASSET_OWNER_ROLE), ASSET_OWNER_TENANT_ID, 10, True),
    (SimpleNamespace(tenant_id="", user_role=None), DEFAULT_TENANT_ID, 10, True),
])
def test_conversation_belongs_to_requires_membership_and_ownership(mock_session_ctx, membership, tenant_id, conversation_id, owned):
    session = mock_session_ctx
    session.execute.return_value.first.return_value = membership
    session.scalar.return_value = conversation_id

    assert conversation_state.conversation_belongs_to(10, user_id="actor", tenant_id=tenant_id) is owned
    membership_query = session.execute.call_args.args[0].compile()
    assert set(membership_query.params.values()) == {"actor", "N", 1}
    if membership is None or membership.tenant_id == "tenant-b":
        session.scalar.assert_not_called()
    else:
        ownership_query = session.scalar.call_args.args[0].compile()
        assert set(ownership_query.params.values()) == {10, "actor", "N"}
        assert "conversation_record_t.created_by" in str(ownership_query)


def test_fail_streaming_assistant_messages_returns_runtime_identities(
    mock_session_ctx
):
    """Startup recovery fails only the rows it locked as streaming."""
    session = mock_session_ctx
    query = MagicMock(name="query")
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.all.return_value = [
        SimpleNamespace(message_id=7, conversation_id=11, created_by="user-1"),
        SimpleNamespace(message_id=8, conversation_id=12, created_by="user-2"),
    ]
    query.update.return_value = 2
    session.query.return_value = query

    rows = fail_streaming_assistant_messages()

    assert rows == [
        {"message_id": 7, "conversation_id": 11, "user_id": "user-1"},
        {"message_id": 8, "conversation_id": 12, "user_id": "user-2"},
    ]
    updates = query.update.call_args.args[0]
    assert updates["status"] == "failed"
    assert query.with_for_update.called


def test_fail_streaming_assistant_messages_returns_empty_without_rows(
    mock_session_ctx
):
    session = mock_session_ctx
    query = MagicMock(name="query")
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.all.return_value = []
    session.query.return_value = query

    assert fail_streaming_assistant_messages() == []
    query.update.assert_not_called()
