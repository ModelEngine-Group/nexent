# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Pin query and transaction rules with real SQLAlchemy expressions and rows."""

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from consts.exceptions import ConversationNotFoundError
from database import workbench_pin_db as pins

STAMP = datetime(2026, 10, 1, tzinfo=timezone.utc)
NEW_STAMP = datetime(2026, 10, 2, tzinfo=timezone.utc)


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


@pytest.fixture
def session(monkeypatch):
    value = MagicMock()

    @contextmanager
    def get_session():
        yield value

    monkeypatch.setattr(pins, "get_db_session", get_session)
    return value


def existing_pin(deleted="N"):
    return pins.ConversationWorkbenchPin(
        pin_id=7, conversation_id=42, user_id="user", tenant_id="tenant",
        pinned_at=STAMP, delete_flag=deleted, created_by="original",
        create_time=STAMP, updated_by="original", update_time=STAMP,
    )


def result_row(pin):
    return (pin, SimpleNamespace(conversation_id=42, conversation_title="History", agent_id=3), 1234.9, 4567.8)


def test_list_serializes_metadata_and_scopes_active_owned_workbench_rows(session):
    session.execute.return_value = [result_row(existing_pin())]
    assert pins.list_workbench_pins("user", "tenant") == [{
        "conversation_id": 42, "conversation_title": "History", "agent_id": 3,
        "create_time": 1234, "update_time": 4567, "pinned_at": STAMP.isoformat(),
    }]
    query = sql(session.execute.call_args.args[0])
    for predicate in (
        "user_id = 'user'", "tenant_id = 'tenant'", "created_by = 'user'",
        "workbench_config IS NOT NULL", "workbench_config != 'null'::jsonb", "delete_flag = 'N'",
    ):
        assert predicate in query
    assert "JOIN nexent.conversation_record_t" in query
    assert "ORDER BY nexent.conversation_workbench_pin_t.pinned_at DESC, nexent.conversation_workbench_pin_t.pin_id DESC" in query
    session.add.assert_not_called()
    session.flush.assert_not_called()


def test_empty_pin_list_is_empty_without_fake_metadata(session):
    session.execute.return_value = []
    assert pins.list_workbench_pins("user", "tenant") == []


@pytest.mark.parametrize("pinned,deleted", [(True, None), (True, "Y"), (True, "N"), (False, "N"), (False, "Y"), (False, None)])
def test_pin_transitions_preserve_audit_identity_and_idempotency(session, pinned, deleted):
    pin = existing_pin(deleted) if deleted is not None else None
    timestamp_changes = pinned and (pin is None or deleted != "N")
    session.scalar.side_effect = [42, pin, NEW_STAMP] if timestamp_changes else [42, pin]

    def execute(_statement, parameters=None):
        if parameters is not None:
            return None
        current = pin if pin is not None else (session.add.call_args.args[0] if session.add.called else None)
        return [result_row(current)] if current is not None and current.delete_flag == "N" else []

    session.execute.side_effect = execute
    result = pins.set_workbench_pin(42, pinned, "user", "tenant")
    session.flush.assert_called_once_with()
    lock = session.execute.call_args_list[0]
    assert "pg_advisory_xact_lock(hashtextextended(:scope, 0))" in str(lock.args[0])
    assert json.loads(lock.args[1]["scope"].removeprefix("workbench-pins:")) == ["tenant", "user"]
    ownership_query = sql(session.scalar.call_args_list[0].args[0])
    assert "conversation_id = 42" in ownership_query and "created_by = 'user'" in ownership_query
    assert "workbench_config IS NOT NULL" in ownership_query and "workbench_config != 'null'::jsonb" in ownership_query
    assert ownership_query.endswith("FOR UPDATE")
    pin_query = sql(session.scalar.call_args_list[1].args[0])
    assert "user_id = 'user'" in pin_query and "tenant_id = 'tenant'" in pin_query
    assert "conversation_id = 42" in pin_query
    if timestamp_changes:
        clock_query = sql(session.scalar.call_args_list[2].args[0])
        assert "greatest(clock_timestamp()," in clock_query
        assert "max(nexent.conversation_workbench_pin_t.pinned_at)" in clock_query
        assert "INTERVAL '1 microsecond'" in clock_query
        assert "user_id = 'user'" in clock_query and "tenant_id = 'tenant'" in clock_query
        current = session.add.call_args.args[0] if pin is None else pin
        assert current.pinned_at == NEW_STAMP and current.delete_flag == "N"
        assert current.updated_by == "user" and str(current.update_time) == "now()"
        assert result[0]["pinned_at"] == NEW_STAMP.isoformat()
        if pin is None:
            session.add.assert_called_once()
            assert current.created_by == "user"
            assert (current.user_id, current.tenant_id, current.conversation_id) == ("user", "tenant", 42)
        else:
            session.add.assert_not_called()
    elif pinned:
        assert pin.pinned_at == STAMP and pin.updated_by == "original" and pin.update_time == STAMP
        assert result[0]["pinned_at"] == STAMP.isoformat()
    elif pin is not None:
        assert pin.delete_flag == "Y" and result == []
        if deleted == "N":
            assert pin.updated_by == "user" and str(pin.update_time) == "now()"
        else:
            assert pin.updated_by == "original" and pin.update_time == STAMP
    else:
        assert result == []
        session.add.assert_not_called()
    if pin is not None:
        assert pin.created_by == "original" and pin.create_time == STAMP and pin.pin_id == 7


@pytest.mark.parametrize("pinned", [True, False])
def test_missing_or_inaccessible_conversation_never_mutates_pin(session, pinned):
    session.scalar.return_value = None
    with pytest.raises(ConversationNotFoundError):
        pins.set_workbench_pin(42, pinned, "user", "tenant")
    session.scalar.assert_called_once()
    session.add.assert_not_called()
    session.flush.assert_not_called()


def test_database_flush_failure_propagates_without_returning_success(session):
    session.scalar.side_effect = [42, existing_pin()]
    session.flush.side_effect = RuntimeError("controlled database failure")
    with pytest.raises(RuntimeError, match="controlled database failure"):
        pins.set_workbench_pin(42, True, "user", "tenant")
    assert session.execute.call_count == 1
