# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit contracts for paginated Agent-chat history queries."""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from contracts.conversation import (
    decode_agent_conversation_cursor,
    decode_agent_group_cursor,
    encode_agent_conversation_cursor,
    encode_agent_group_cursor,
)
from management.db.identity import conversation_agent_history_db as db


@pytest.fixture
def session(monkeypatch):
    value = MagicMock()

    @contextmanager
    def sessions():
        yield value

    monkeypatch.setattr(db, "get_db_session", sessions)
    return value


def _group_row(agent_id, group_id, activity, name, available=True, matched=False):
    return SimpleNamespace(
        agent_id=agent_id,
        group_id=group_id,
        activity_time=activity,
        agent_name=name,
        agent_available=available,
        matched_conversation=matched,
    )


def _conversation_row(identity, activity):
    return SimpleNamespace(
        conversation_id=identity,
        conversation_title=f"History {identity}",
        agent_id=7,
        pinned_at=None,
        activity_time=activity,
        create_time=1_000,
        update_time=2_000,
        last_activity_time=3_000,
    )


def test_agent_group_cursor_round_trips_and_is_bound_to_search():
    activity = datetime(2026, 10, 26, 8, 30, tzinfo=timezone.utc)
    cursor = encode_agent_group_cursor(activity, 7, "  Budget  ")

    assert decode_agent_group_cursor(cursor, "budget") == (activity, 7)
    with pytest.raises(ValueError, match="Invalid agent group cursor"):
        decode_agent_group_cursor(cursor, "invoice")


def test_conversation_cursor_is_bound_to_group_and_search():
    activity = datetime(2026, 10, 26, 8, 30, tzinfo=timezone.utc)
    cursor = encode_agent_conversation_cursor(activity, 42, "agent:7", "notes")

    assert decode_agent_conversation_cursor(cursor, "agent:7", "notes") == (
        activity,
        42,
    )
    with pytest.raises(ValueError, match="Invalid agent conversation cursor"):
        decode_agent_conversation_cursor(cursor, "agent:8", "notes")


def test_group_page_orders_by_activity_and_keeps_pins_outside_ordinary_quota(session):
    activity = datetime(2026, 10, 26, 8, 30)
    pinned = [_group_row(99, 99, activity, "Pinned agent")]
    regular = [
        _group_row(7, 7, activity, "Agent Seven"),
        _group_row(None, -1, activity, None),
    ]
    session.execute.side_effect = [pinned, regular]

    result = db.get_agent_conversation_group_page(
        "owner", "tenant", limit=2, search=""
    )

    assert [item["agent_id"] for item in result["items"]] == [7, None]
    assert [item["agent_id"] for item in result["pinned_items"]] == [99]
    assert result["next_cursor"] is None
    assert session.execute.call_count == 2
    sql = str(session.execute.call_args_list[1].args[0].compile(dialect=postgresql.dialect()))
    assert "GROUP BY nexent.conversation_record_t.agent_id" in sql
    assert "NOT (nexent.conversation_record_t.workbench_config IS NOT NULL OR" in sql
    assert "ORDER BY anon_1.activity_time DESC, group_id DESC" in sql
    assert "created_by" in sql and "delete_flag" in sql


def test_group_page_rejects_invalid_limit_and_cursor_before_query(session):
    with pytest.raises(ValueError, match="Agent group limit"):
        db.get_agent_conversation_group_page("owner", "tenant", limit=0)
    with pytest.raises(ValueError, match="Invalid agent group cursor"):
        db.get_agent_conversation_group_page(
            "owner", "tenant", cursor="invalid-cursor"
        )
    session.execute.assert_not_called()


def test_group_conversation_page_returns_cursor_and_full_pin_snapshot(session):
    activity = datetime(2026, 10, 26, 8, 30)
    session.execute.side_effect = [
        [_conversation_row(41, activity), _conversation_row(40, activity)],
        [_conversation_row(5, activity)],
    ]

    result = db.get_agent_group_conversation_page(
        "owner", "agent:7", limit=1, search="history"
    )

    assert [item["conversation_id"] for item in result["items"]] == [41]
    assert [item["conversation_id"] for item in result["pinned_items"]] == [5]
    assert decode_agent_conversation_cursor(result["next_cursor"], "agent:7", "history") == (
        activity.replace(tzinfo=timezone.utc),
        41,
    )
    ordinary_sql = str(
        session.execute.call_args_list[0].args[0].compile(dialect=postgresql.dialect())
    )
    assert "conversation_title ILIKE" in ordinary_sql
    assert "ORDER BY activity_time DESC, nexent.conversation_record_t.conversation_id DESC" in ordinary_sql
    assert "created_by" in ordinary_sql and "NOT (nexent.conversation_record_t.workbench_config IS NOT NULL OR" in ordinary_sql


@pytest.mark.parametrize("group_key", ["", "agent:0", "agent:-1", "agent:01", "agent:nope"])
def test_group_conversation_page_rejects_invalid_group_keys(session, group_key):
    with pytest.raises(ValueError, match="Invalid agent conversation group"):
        db.get_agent_group_conversation_page("owner", group_key)
    session.execute.assert_not_called()


def test_agent_conversation_ids_are_scoped_to_owner_and_one_agent(session):
    session.scalars.return_value = [11, 12]

    assert db.list_agent_conversation_ids("owner", 7) == [11, 12]
    query = session.scalars.call_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "created_by" in sql and "agent_id" in sql and "NOT (nexent.conversation_record_t.workbench_config IS NOT NULL OR" in sql
    assert "delete_flag" in sql
    assert query.compile(dialect=postgresql.dialect()).params["created_by_1"] == "owner"
    assert query.compile(dialect=postgresql.dialect()).params["agent_id_1"] == 7


def test_agent_conversation_ids_reject_invalid_identity_before_query(session):
    with pytest.raises(ValueError, match="Invalid agent ID"):
        db.list_agent_conversation_ids("owner", True)
    session.scalars.assert_not_called()


@pytest.mark.parametrize("workbench_config", [None, {}, {"mode": "agent_create"}])
def test_detail_activity_is_added_only_to_agent_chat(monkeypatch, session, workbench_config):
    """Preserve the existing Workbench detail response while enriching Agent chat."""
    from management.db.conversation import repository as history_db

    @contextmanager
    def sessions():
        yield session

    session.execute.return_value.first.return_value = {
        "conversation_id": 7,
        "conversation_title": "History",
        "create_time": 1000,
        "last_activity_time": 9000,
        "workbench_config": workbench_config,
    }
    session.execute.return_value.all.return_value = []
    session.scalars.return_value.all.return_value = []
    monkeypatch.setattr(history_db, "get_db_session", sessions)
    monkeypatch.setattr(history_db, "as_dict", lambda record: record)

    result = history_db.get_conversation_history(7, "owner")

    assert result["create_time"] == 1000
    assert result["workbench_config"] == workbench_config
    assert result["message_records"] == []
    if workbench_config is None:
        assert result["last_activity_time"] == 9000
    else:
        assert "last_activity_time" not in result


@pytest.mark.parametrize("limit", [0, 101])
def test_conversation_page_rejects_invalid_limit(session, limit):
    with pytest.raises(ValueError, match="Conversation limit"):
        db.get_agent_group_conversation_page("owner", "agent:7", limit=limit)
    session.execute.assert_not_called()


def test_group_page_next_cursor_and_included_groups(session):
    activity = datetime(2026, 10, 26, 8, 30)
    session.execute.side_effect = [[], [
        _group_row(7, 7, activity, "Seven", matched=True),
        _group_row(6, 6, activity, "Six"),
    ], [_group_row(None, -1, activity, None)]]
    cursor = encode_agent_group_cursor(activity, 8, "budget")
    result = db.get_agent_conversation_group_page(
        "owner", "tenant", limit=1, cursor=cursor, search="budget",
        include_agent_ids=[7], include_other=True,
    )
    assert decode_agent_group_cursor(result["next_cursor"], "budget")[1] == 7
    assert result["items"][0]["matched_conversation"] is True
    assert result["included_items"][0]["group_key"] == "other"
    query = session.execute.call_args_list[1].args[0].compile(dialect=postgresql.dialect())
    assert " < " in str(query) and " = " in str(query)
    assert 8 in query.params.values()
    assert "%budget%" in query.params.values()


def test_other_group_terminal_page_and_pin_timestamp(session):
    activity = datetime(2026, 10, 26, 8, 30)
    row = _conversation_row(41, activity)
    row.agent_id = None
    row.pinned_at = activity
    session.execute.side_effect = [[row], [row]]
    cursor = encode_agent_conversation_cursor(activity, 42, "other", "")
    result = db.get_agent_group_conversation_page("owner", "other", cursor=cursor)
    assert result["next_cursor"] is None
    assert result["items"][0]["agent_id"] is None
    assert result["pinned_items"][0]["pinned_at"] == "2026-10-26T08:30:00+00:00"
    sql = str(session.execute.call_args_list[0].args[0].compile(dialect=postgresql.dialect()))
    assert "agent_id IS NULL" in sql and " < " in sql


def test_group_page_search_escapes_wildcards(session):
    session.execute.side_effect = [[], []]
    assert db.get_agent_conversation_group_page("owner", "tenant", search="%_\\")['items'] == []
    params = session.execute.call_args_list[1].args[0].compile(dialect=postgresql.dialect()).params
    assert "%\\%\\_\\\\%" in params.values()


@pytest.mark.parametrize("kind", ["group", "conversation"])
@pytest.mark.parametrize("payload", [None, {}, [], ["invalid-date", 1, "x"], [1, 1, "x"], ["2026-01-01", 1, "x"]])
def test_cursor_rejects_malformed_payloads(kind, payload):
    import base64
    import json

    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    with pytest.raises(ValueError, match="Invalid agent"):
        if kind == "group":
            decode_agent_group_cursor(cursor, "")
        else:
            decode_agent_conversation_cursor(cursor, "agent:7", "")


@pytest.mark.parametrize("kind", ["group", "conversation"])
@pytest.mark.parametrize("cursor", ["", "x" * 513, "%%%"])
def test_cursor_rejects_empty_oversized_and_invalid_base64(kind, cursor):
    with pytest.raises(ValueError, match="Invalid agent"):
        if kind == "group":
            decode_agent_group_cursor(cursor, "")
        else:
            decode_agent_conversation_cursor(cursor, "agent:7", "")


@pytest.mark.parametrize("kind", ["group", "conversation"])
@pytest.mark.parametrize("identity", [0, -2, True, "7"])
def test_cursor_rejects_invalid_identity(kind, identity):
    activity = datetime(2026, 10, 26, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="Invalid agent"):
        if kind == "group":
            decode_agent_group_cursor(encode_agent_group_cursor(activity, identity, ""), "")
        else:
            decode_agent_conversation_cursor(
                encode_agent_conversation_cursor(activity, identity, "agent:7", ""), "agent:7", "",
            )


@pytest.mark.parametrize("kind", ["group", "conversation"])
def test_cursor_rejects_naive_timestamp(kind):
    import base64
    import json
    from contracts.conversation import _search_fingerprint

    payload = ["2026-01-01T00:00:00", 7]
    if kind == "conversation":
        payload.append("agent:7")
    payload.append(_search_fingerprint(""))
    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    with pytest.raises(ValueError, match="Invalid agent"):
        if kind == "group":
            decode_agent_group_cursor(cursor, "")
        else:
            decode_agent_conversation_cursor(cursor, "agent:7", "")
