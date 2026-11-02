# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Automation binding uses one caller-owned session and a stable lock order."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy.dialects import postgresql

from management.db.automation import messages


@pytest.fixture
def store(monkeypatch):
    session = MagicMock()

    @contextmanager
    def sessions():
        yield session

    monkeypatch.setattr(messages, "get_db_session", sessions)
    create = MagicMock(return_value=42)
    units = MagicMock()
    monkeypatch.setattr(messages.conversation_db, "create_conversation_message", create)
    monkeypatch.setattr(messages.conversation_db, "create_message_unit", units)
    return session, create, units


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_creation_and_reference_share_transaction_and_conversation_first_lock(store, role):
    session, create, units = store
    run = SimpleNamespace(status="RUNNING", user_message_id=None if role == "user" else 21,
                          assistant_message_id=None)
    results = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
    for result, value in zip(results, [1, run, 8, None]):
        result.scalar_one_or_none.return_value = value
    session.execute.side_effect = results
    assert messages.create_run_message(7, dict(conversation_id=1, message_idx=0,
        role=role, content="prompt"), "owner", "tenant") == 42
    assert create.call_args.kwargs["db_session"] is session
    assert create.call_args.kwargs["message_source"].value == "AUTOMATION"
    if role == "user":
        assert units.call_args.kwargs["db_session"] is session
    else:
        assert create.call_args.args[0]["message_idx"] == 9
        units.assert_not_called()
    statements = [str(call.args[0].compile(dialect=postgresql.dialect())) for call in session.execute.call_args_list]
    assert "conversation_record_t" in statements[0] and "FOR UPDATE" in statements[0]
    assert "agent_automation_run_t" in statements[1] and "FOR UPDATE" in statements[1]
    assert statements[-1].startswith("UPDATE")
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.parametrize("run_status", ["CANCELED", "TIMEOUT", "SUCCEEDED", "FAILED"])
def test_terminal_run_cannot_create_message(store, run_status):
    session, create, units = store
    session.execute.side_effect = [MagicMock(scalar_one_or_none=lambda: 1),
                                  MagicMock(scalar_one_or_none=lambda: SimpleNamespace(status=run_status))]
    with pytest.raises(ValueError, match="no longer active"):
        messages.create_run_message(7, dict(conversation_id=1, message_idx=0,
            role="user", content="prompt"), "owner", "tenant")
    create.assert_not_called()
    units.assert_not_called()


def test_unsupported_role_is_rejected_before_database_access(store):
    session, create, _ = store
    with pytest.raises(ValueError, match="Unsupported"):
        messages.create_run_message(7, {"role": "system"}, "owner", "tenant")
    session.execute.assert_not_called()


@pytest.mark.parametrize("role", ["user", "assistant"])
@pytest.mark.parametrize("conflict", [False, True])
def test_retry_reuses_owned_message_and_rejects_stale_reference(store, role, conflict):
    session, create, units = store
    run = SimpleNamespace(status="RUNNING", user_message_id=42,
                          assistant_message_id=42 if role == "assistant" else None)
    existing = None if conflict else SimpleNamespace(message_content="prompt")
    session.execute.side_effect = [MagicMock(scalar_one_or_none=Mock(return_value=value)) for value in [1, run, existing]]
    args = (7, dict(conversation_id=1, message_idx=0, role=role, content="prompt"), "owner", "tenant")
    if conflict:
        with pytest.raises(ValueError, match="conflicts"):
            messages.create_run_message(*args)
    else:
        assert messages.create_run_message(*args) == 42
    create.assert_not_called()
    units.assert_not_called()


@pytest.mark.parametrize("boundary", ["conversation", "run", "prompt"])
def test_missing_relationship_rejects_before_inserting(store, boundary):
    session, create, units = store
    run = SimpleNamespace(status="RUNNING", user_message_id=21, assistant_message_id=None)
    values = [None] if boundary == "conversation" else [1, None] if boundary == "run" else [1, run, None]
    session.execute.side_effect = [MagicMock(scalar_one_or_none=Mock(return_value=value)) for value in values]
    with pytest.raises(ValueError, match="unavailable|no longer active"):
        messages.create_run_message(7, dict(conversation_id=1, message_idx=0,
            role="assistant", content=""), "owner", "tenant")
    create.assert_not_called()
    units.assert_not_called()
