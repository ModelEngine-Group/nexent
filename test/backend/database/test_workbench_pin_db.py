# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Personal conversation pin persistence with real SQLAlchemy expressions."""

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Update

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


def conversation(stamp=STAMP):
    return SimpleNamespace(conversation_id=42, conversation_title="History", agent_id=3,
                           workbench_pinned_at=stamp, created_by="user", update_time=STAMP)


def result_row(record):
    return record, 1234.9, 4567.8


def test_list_serializes_metadata_and_filters_owned_active_workbench_pins(session):
    session.execute.return_value = [result_row(conversation())]
    assert pins.list_workbench_pins("user", "tenant") == [{
        "conversation_id": 42, "conversation_title": "History", "agent_id": 3,
        "create_time": 1234, "update_time": 4567, "pinned_at": STAMP.isoformat(),
    }]
    query = sql(session.execute.call_args.args[0])
    for predicate in ("created_by = 'user'", "workbench_config IS NOT NULL",
                      "workbench_config != 'null'::jsonb", "delete_flag = 'N'",
                      "workbench_pinned_at IS NOT NULL"):
        assert predicate in query
    assert "JOIN" not in query and "conversation_workbench_pin_t" not in query
    assert "ORDER BY nexent.conversation_record_t.workbench_pinned_at DESC, nexent.conversation_record_t.conversation_id DESC" in query
    session.add.assert_not_called()


def test_empty_pin_list_is_empty_without_fake_metadata(session):
    session.execute.return_value = []
    assert pins.list_workbench_pins("user", "tenant") == []


@pytest.mark.parametrize("pinned,stamp", [(True, None), (True, STAMP), (False, STAMP), (False, None)])
def test_pin_transitions_are_idempotent_and_preserve_activity(session, pinned, stamp):
    record = conversation(stamp)
    changes = pinned != (stamp is not None)
    session.scalar.side_effect = [record, NEW_STAMP] if pinned and changes else [record]

    def execute(statement, parameters=None):
        if parameters is not None:
            return None
        if isinstance(statement, Update):
            values = statement.compile().params
            record.workbench_pinned_at = values["workbench_pinned_at"]
            assert "update_time=nexent.conversation_record_t.update_time" in sql(statement)
            assert "updated_by" not in str(statement)
            return None
        return [result_row(record)] if record.workbench_pinned_at is not None else []

    session.execute.side_effect = execute
    result = pins.set_workbench_pin(42, pinned, "user", "tenant")
    lock = session.execute.call_args_list[0]
    assert "pg_advisory_xact_lock(hashtextextended(:scope, 0))" in str(lock.args[0])
    assert json.loads(lock.args[1]["scope"].removeprefix("workbench-pins:")) == ["user"]
    ownership = sql(session.scalar.call_args_list[0].args[0])
    assert "conversation_id = 42" in ownership and "created_by = 'user'" in ownership
    assert "workbench_config IS NOT NULL" in ownership and "workbench_config != 'null'::jsonb" in ownership
    assert ownership.endswith("FOR UPDATE")
    writes = [c.args[0] for c in session.execute.call_args_list if isinstance(c.args[0], Update)]
    assert len(writes) == int(changes)
    if changes:
        assert "conversation_id = 42" in sql(writes[0]) and "created_by = 'user'" in sql(writes[0])
    if pinned and changes:
        clock = sql(session.scalar.call_args_list[1].args[0])
        assert "greatest(clock_timestamp()," in clock
        assert "max(nexent.conversation_record_t.workbench_pinned_at)" in clock
        assert "INTERVAL '1 microsecond'" in clock and "created_by = 'user'" in clock
    assert record.update_time == STAMP
    assert record.workbench_pinned_at == ((NEW_STAMP if changes else stamp) if pinned else None)
    assert ([item["pinned_at"] for item in result] == [record.workbench_pinned_at.isoformat()]) if pinned else result == []
    session.add.assert_not_called()


@pytest.mark.parametrize("pinned", [True, False])
def test_missing_or_inaccessible_conversation_never_writes(session, pinned):
    session.scalar.return_value = None
    with pytest.raises(ConversationNotFoundError):
        pins.set_workbench_pin(42, pinned, "user", "tenant")
    session.scalar.assert_called_once()
    assert session.execute.call_count == 1


def test_database_update_failure_propagates_without_returning_success(session):
    session.scalar.side_effect = [conversation(None), NEW_STAMP]
    session.execute.side_effect = [None, RuntimeError("controlled database failure")]
    with pytest.raises(RuntimeError, match="controlled database failure"):
        pins.set_workbench_pin(42, True, "user", "tenant")
    assert session.execute.call_count == 2
