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
from database import conversation_agent_history_db as db


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
    assert "workbench_config IS NULL" in sql
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
    assert "created_by" in ordinary_sql and "workbench_config IS NULL" in ordinary_sql


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
    assert "created_by" in sql and "agent_id" in sql and "workbench_config IS NULL" in sql
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
    from database import conversation_db as history_db

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
