# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Ordinary quota, trusted provenance and atomic activity unit contracts."""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert, Update

from consts.exceptions import AppException
from consts.model import AgentRequest
from contracts.conversation import MessageSource, decode_activity_cursor, encode_activity_cursor
from database import conversation_db as db


@pytest.fixture
def session(monkeypatch):
    value = MagicMock()
    value.scalar.return_value = 100
    value.execute.return_value.scalar.return_value = 123

    @contextmanager
    def sessions():
        yield value

    monkeypatch.setattr(db, "get_db_session", sessions)
    monkeypatch.setattr(db, "MAX_CONVERSATION_TURNS", 100)
    return value


def message(**changes):
    return {"conversation_id": 1, "message_idx": 200, "role": "user", "content": "hello", **changes}


def test_ordinary_quota_excludes_automation_and_rejects_before_inserting(session):
    with pytest.raises(AppException, match="maximum 100 turns") as error:
        db.create_conversation_message(message(message_source="AUTOMATION"), "owner")
    assert error.value.details["current_count"] == 100
    query = session.scalar.call_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "message_source = 'CHAT'" in sql
    assert "message_role = 'user'" in sql and "delete_flag = 'N'" in sql
    assert not any(isinstance(call.args[0], Insert) for call in session.execute.call_args_list)


def test_automation_at_ordinary_limit_inserts_and_touches_with_one_session(session):
    assert db.create_conversation_message(message(), "owner", message_source=MessageSource.AUTOMATION) == 123
    session.scalar.assert_not_called()
    insert, touch = [call.args[0] for call in session.execute.call_args_list]
    assert isinstance(insert, Insert) and isinstance(touch, Update)
    assert insert.compile().params["message_source"] == "AUTOMATION"
    compiled = str(touch.compile(dialect=postgresql.dialect()))
    assert "greatest(" in compiled and "clock_timestamp()" in compiled
    assert "created_by" in compiled and "last_activity_time" in compiled


@pytest.mark.parametrize("source", ["CHAT", "AUTOMATION"])
def test_ordinary_below_limit_and_message_source_are_persisted(session, source):
    session.scalar.return_value = 99
    db.create_conversation_message(message(), "owner", message_source=source)
    inserts = [call.args[0] for call in session.execute.call_args_list if isinstance(call.args[0], Insert)]
    assert inserts[0].compile().params["message_source"] == source


def test_streaming_placeholder_does_not_touch_activity(session):
    db.create_conversation_message(message(role="assistant", content=""), "owner", status="streaming")
    assert len(session.execute.call_args_list) == 1


def test_invalid_internal_source_rejected_without_database_write(session):
    with pytest.raises(ValueError):
        db.create_conversation_message(message(), "owner", message_source="untrusted")
    session.execute.assert_not_called()


def test_serialized_agent_request_cannot_override_private_source():
    request = AgentRequest(query="hello", agent_id=1, _message_source="AUTOMATION", message_source="AUTOMATION")
    assert request._message_source == "CHAT"
    assert "message_source" not in request.model_dump()
    assert "_message_source" not in request.model_dump()


def test_activity_cursor_round_trip_preserves_microseconds():
    moment = datetime(2026, 10, 20, 8, 2, 3, 123456, tzinfo=timezone.utc)
    assert decode_activity_cursor(encode_activity_cursor(moment, 42)) == (moment, 42)


@pytest.mark.parametrize("cursor", ["", "garbage", "W10", "e30", "WyJ4IiwxXQ", "a" * 513])
def test_invalid_activity_cursors_are_rejected(cursor):
    with pytest.raises(ValueError, match="Invalid conversation activity cursor"):
        decode_activity_cursor(cursor)
