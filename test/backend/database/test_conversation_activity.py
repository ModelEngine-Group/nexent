# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Ordinary quota, trusted provenance and atomic activity unit contracts."""

import base64
import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert, Update

from contracts.errors.exceptions import AppException
from contracts.agent import AgentRequest
from contracts.conversation import MessageSource, decode_activity_cursor, encode_activity_cursor
from management.db.conversation import repository as db


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


def test_message_without_user_touches_activity_without_changing_audit_owner(session):
    assert db.create_conversation_message(message()) == 123

    session.scalar.assert_not_called()
    insert, touch = [call.args[0] for call in session.execute.call_args_list]
    assert isinstance(insert, Insert) and isinstance(touch, Update)
    assert "created_by" not in insert.compile().params
    compiled = str(touch.compile(dialect=postgresql.dialect()))
    assert "last_activity_time=greatest(" in compiled
    assert "conversation_id" in compiled and "delete_flag" in compiled
    assert "created_by" not in compiled and "updated_by" not in compiled


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


@pytest.mark.parametrize("offset_hours", [0, 8, -5])
def test_activity_cursor_round_trip_preserves_instant_and_microseconds(offset_hours):
    moment = datetime(2026, 10, 20, 8, 2, 3, 123456, tzinfo=timezone(timedelta(hours=offset_hours)))
    decoded, identity = decode_activity_cursor(encode_activity_cursor(moment, 42))
    assert decoded == moment.astimezone(timezone.utc)
    assert decoded.tzinfo is timezone.utc
    assert decoded.microsecond == 123456 and identity == 42


@pytest.mark.parametrize("cursor", ["", "garbage", "W10", "e30", "WyJ4IiwxXQ", "a" * 513])
def test_invalid_activity_cursors_are_rejected(cursor):
    with pytest.raises(ValueError, match="Invalid conversation activity cursor"):
        decode_activity_cursor(cursor)


@pytest.mark.parametrize(
    "payload",
    [
        ["2026-10-20T08:00:00", 42],
        ["2026-10-20T08:00:00+00:00", True],
        ["2026-10-20T08:00:00+00:00", "42"],
        ["2026-10-20T08:00:00+00:00", 42.0],
        ["2026-10-20T08:00:00+00:00", 0],
        ["2026-10-20T08:00:00+00:00", -1],
    ],
    ids=["naive-time", "boolean-id", "string-id", "float-id", "zero-id", "negative-id"],
)
def test_activity_cursor_rejects_invalid_time_or_identity(payload):
    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    with pytest.raises(ValueError, match="Invalid conversation activity cursor"):
        decode_activity_cursor(cursor)


def test_activity_cursor_cannot_be_combined_with_offset(session):
    cursor = encode_activity_cursor(datetime(2026, 10, 20, tzinfo=timezone.utc), 42)
    with pytest.raises(ValueError, match="cursor cannot be combined with offset"):
        db.get_conversation_list_page("owner", 2000, 1000, limit=2, offset=1, cursor=cursor)
    session.execute.assert_not_called()


def _activity_row(identity, moment):
    return SimpleNamespace(
        conversation_id=identity, conversation_title=f"History {identity}",
        agent_id=None, chat_mode=None, activity_time=moment,
        create_time=1000, update_time=2000, last_activity_time=moment.timestamp() * 1000,
        total=30, today=3, last_7_days=7, older=20,
    )


@pytest.mark.parametrize("conversation_type", [None, "workbench", "agent_chat"])
def test_activity_page_uses_time_and_id_boundary_and_last_visible_cursor(session, conversation_type):
    moment = datetime(2026, 10, 20, 8, 2, 3, 123456, tzinfo=timezone.utc)
    session.execute.return_value = [_activity_row(identity, moment) for identity in (41, 40, 39)]

    result = db.get_conversation_list_page(
        "owner", 2000, 1000, limit=2, conversation_type=conversation_type,
        cursor=encode_activity_cursor(moment, 42),
    )

    assert [item["conversation_id"] for item in result["items"]] == [41, 40]
    assert result["metadata"] == {"total": 30, "today": 3, "last_7_days": 7, "older": 20}
    assert decode_activity_cursor(result["next_cursor"]) == (moment, 40)
    assert result["items"][0]["last_activity_time"] == int(moment.timestamp() * 1000)
    assert result["items"][0]["chat_mode"] == "execution"
    session.execute.assert_called_once()
    compiled = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "anon_1.activity_time < %(activity_time_1)s" in sql
    assert "anon_1.activity_time = %(activity_time_2)s AND anon_1.conversation_id < %(conversation_id_1)s" in sql
    assert "ORDER BY anon_1.activity_time DESC, anon_1.conversation_id DESC" in sql
    assert compiled.params["activity_time_1"] == compiled.params["activity_time_2"] == moment.replace(tzinfo=None)
    assert compiled.params["conversation_id_1"] == 42
    assert compiled.params["created_by_1"] == "owner" and compiled.params["delete_flag_1"] == "N"
    limit_parameter = re.search(r"LIMIT %\((\w+)\)s", sql).group(1)
    assert compiled.params[limit_parameter] == 3
    if conversation_type:
        predicate = "IS NOT NULL" if conversation_type == "workbench" else "IS NULL"
        assert f"workbench_config {predicate}" in sql


def test_exhausted_activity_cursor_retains_scope_counts_without_another_cursor(session):
    moment = datetime(2026, 10, 20, tzinfo=timezone.utc)
    counts = MagicMock()
    counts.one.return_value = SimpleNamespace(total=30, today=3, last_7_days=7, older=20)
    session.execute.side_effect = [[], counts]

    result = db.get_conversation_list_page(
        "owner", 2000, 1000, limit=2, cursor=encode_activity_cursor(moment, 42),
    )

    assert result == {
        "items": [], "next_cursor": None,
        "metadata": {"total": 30, "today": 3, "last_7_days": 7, "older": 20},
    }
    assert session.execute.call_count == 2
    sql = str(session.execute.call_args_list[1].args[0].compile(dialect=postgresql.dialect()))
    assert "created_by" in sql and "delete_flag" in sql
    assert "activity_time <" not in sql and "LIMIT" not in sql


def test_activity_storage_clock_and_fallback_are_naive_utc(session):
    assert db.ConversationRecord.last_activity_time.type.timezone is False
    db.create_conversation_message(message(), "owner", message_source=MessageSource.AUTOMATION)
    touch = session.execute.call_args_list[-1].args[0].compile(dialect=postgresql.dialect())
    assert "greatest(" in str(touch) and "timezone(" in str(touch)
    assert "UTC" in touch.params.values()
    fallback = str(db._activity_time_expression().compile(dialect=postgresql.dialect()))
    assert "coalesce(" in fallback and "create_time" in fallback and "timezone(" not in fallback


def test_naive_utc_cursor_never_uses_the_process_timezone():
    class StoredTime(datetime):
        def astimezone(self, tz=None):
            assert self.tzinfo is not None, "Naive storage time must be assigned UTC first"
            return super().astimezone(tz)

    moment = StoredTime(2026, 10, 21, 2, 3, 4, 123456)
    assert decode_activity_cursor(encode_activity_cursor(moment, 42)) == (
        datetime(2026, 10, 21, 2, 3, 4, 123456, tzinfo=timezone.utc), 42,
    )
