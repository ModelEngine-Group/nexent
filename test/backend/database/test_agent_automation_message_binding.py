# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Automation binding uses one caller-owned session and a stable lock order."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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


def _schedule_message(store, *, task_overrides=None, task_exists=True, lease_unexpired=True):
    session, _, _ = store
    scheduled = datetime(2026, 11, 26, tzinfo=timezone.utc)
    task = SimpleNamespace(
        lock_owner="scheduler", lock_until=scheduled + timedelta(minutes=1),
        status="ACTIVE", next_fire_at=scheduled,
    )
    for field, value in (task_overrides or {}).items():
        setattr(task, field, value)
    run = SimpleNamespace(status="RUNNING", user_message_id=None, scheduled_fire_at=scheduled)
    session.execute.side_effect = [
        Mock(scalar_one_or_none=Mock(return_value=value))
        for value in (task if task_exists else None, 1, run, None)
    ]
    session.scalar.return_value = lease_unexpired
    message = {"conversation_id": 1, "message_idx": 0, "role": "user", "content": "prompt"}
    return task, message


def test_scheduled_prompt_checks_database_clock_after_locking_owned_records(store):
    session, create, units = store
    task, message = _schedule_message(store)

    assert messages.create_run_message(7, message, "owner", "tenant", lease_owner="scheduler") == 42

    assert [entry[0] for entry in session.method_calls] == ["execute", "execute", "execute", "scalar", "execute"]
    locked_task = session.execute.call_args_list[0].args[0].compile(dialect=postgresql.dialect())
    assert str(locked_task).startswith("SELECT nexent.agent_automation_task_t.")
    assert str(locked_task).endswith("FOR UPDATE")
    assert set(locked_task.params.values()) == {7, "owner", "tenant", "N"}
    expiry = session.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "clock_timestamp() <" in str(expiry)
    assert list(expiry.params.values()) == [task.lock_until]
    create.assert_called_once_with(message, "owner", status="completed",
                                   message_source=messages.MessageSource.AUTOMATION, db_session=session)
    units.assert_called_once_with(42, 1, 0, "automation_prompt", "prompt", user_id="owner", db_session=session)


@pytest.mark.parametrize(
    ("task_exists", "task_overrides", "lease_unexpired", "reads", "check_clock"),
    [
        pytest.param(False, {}, True, 1, False, id="missing-task"),
        pytest.param(True, {"lock_owner": "replacement"}, True, 1, False, id="different-owner"),
        pytest.param(True, {"lock_until": None}, True, 1, False, id="released-lock"),
        pytest.param(True, {"status": "PAUSED"}, True, 3, False, id="paused-task"),
        pytest.param(True, {"next_fire_at": None}, True, 3, False, id="stale-occurrence"),
        pytest.param(True, {}, False, 3, True, id="expired-lock"),
    ],
)
def test_scheduled_prompt_rejects_a_stale_lease_without_writing(
    store, task_exists, task_overrides, lease_unexpired, reads, check_clock,
):
    session, create, units = store
    _, message = _schedule_message(
        store, task_exists=task_exists, task_overrides=task_overrides, lease_unexpired=lease_unexpired,
    )

    with pytest.raises(ValueError, match="Automation task lease is no longer owned"):
        messages.create_run_message(7, message, "owner", "tenant", lease_owner="scheduler")

    assert session.execute.call_count == reads
    assert session.scalar.called is check_clock
    create.assert_not_called()
    units.assert_not_called()
