"""Unit tests for ``backend.database.memory_retrieval_hit_db`` (Phase 2)."""

import sys
import types
from datetime import datetime
from unittest.mock import MagicMock

import pytest


# Ensure backend imports resolve when running from project root.
sys.path.insert(
    0,
    __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."),
)


# Stub database.client
client_mod = types.ModuleType("database.client")
client_mod.get_db_session = MagicMock(name="get_db_session")
client_mod.filter_property = lambda data, _model: dict(data)
sys.modules["database.client"] = client_mod
sys.modules["backend.database.client"] = client_mod


# Stub SQLAlchemy
sqlalchemy_mod = types.ModuleType("sqlalchemy")


class _Integer:
    pass


sqlalchemy_mod.Integer = _Integer
sqlalchemy_mod.func = MagicMock(name="func")
sys.modules["sqlalchemy"] = sqlalchemy_mod


# Stub db_models
db_models_mod = types.ModuleType("database.db_models")


class _Column:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return ("eq", self.name, other)

    def isnot(self, other):
        return ("isnot", self.name, other)

    def desc(self):
        return self

    def asc(self):
        return self

    def __lt__(self, other):
        return ("lt", self.name, other)

    def __le__(self, other):
        return ("le", self.name, other)

    def __gt__(self, other):
        return ("gt", self.name, other)

    def __ge__(self, other):
        return ("ge", self.name, other)

    def label(self, _name):
        return self


class MemoryRetrievalHit:
    hit_id = _Column("hit_id")
    tenant_id = _Column("tenant_id")
    user_id = _Column("user_id")
    agent_id = _Column("agent_id")
    conversation_id = _Column("conversation_id")
    memory_id = _Column("memory_id")
    query_text = _Column("query_text")
    query_hash = _Column("query_hash")
    retrieval_score = _Column("retrieval_score")
    source = _Column("source")
    occurred_at = _Column("occurred_at")
    day = _Column("day")
    grounded = _Column("grounded")

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


db_models_mod.MemoryRetrievalHit = MemoryRetrievalHit
sys.modules["database.db_models"] = db_models_mod
sys.modules["backend.database.db_models"] = db_models_mod


from backend.database import memory_retrieval_hit_db


@pytest.fixture
def mock_session_ctx():
    session = MagicMock(name="session")
    ctx = MagicMock(name="ctx")
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    return session, ctx


def test_insert_retrieval_hits_appends_rows(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    monkeypatch.setattr(
        "backend.database.memory_retrieval_hit_db.get_db_session", lambda: ctx
    )

    rows = [
        {
            "tenant_id": "t1",
            "user_id": "u1",
            "agent_id": "a1",
            "memory_id": "m1",
            "query_text": "hi",
            "query_hash": "qh",
            "retrieval_score": 0.9,
        },
        {
            "tenant_id": "t1",
            "user_id": "u1",
            "agent_id": "a1",
            "memory_id": "m2",
            "query_text": "hi",
            "query_hash": "qh",
            "retrieval_score": 0.85,
        },
    ]

    count = memory_retrieval_hit_db.insert_retrieval_hits(rows)

    assert count == 2
    session.add_all.assert_called_once()
    session.commit.assert_called_once()


def test_insert_retrieval_hits_empty(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    monkeypatch.setattr(
        "backend.database.memory_retrieval_hit_db.get_db_session", lambda: ctx
    )

    count = memory_retrieval_hit_db.insert_retrieval_hits([])

    assert count == 0
    session.add_all.assert_not_called()


def test_count_hits_since(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    query = MagicMock()
    query.filter.return_value = query
    query.scalar.return_value = 7
    session.query.return_value = query

    monkeypatch.setattr(
        "backend.database.memory_retrieval_hit_db.get_db_session", lambda: ctx
    )

    count = memory_retrieval_hit_db.count_hits_since("t1", user_id="u1")

    assert count == 7


def test_delete_hits_before(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    query = MagicMock()
    query.filter.return_value = query
    query.delete.return_value = 3
    session.query.return_value = query
    monkeypatch.setattr(
        "backend.database.memory_retrieval_hit_db.get_db_session", lambda: ctx
    )

    from datetime import datetime

    n = memory_retrieval_hit_db.delete_hits_before(datetime(2026, 1, 1))
    assert n == 3
    session.commit.assert_called_once()


def test_insert_retrieval_hits_defaults_and_rolls_back_on_error(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.add_all.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(
        "backend.database.memory_retrieval_hit_db.get_db_session", lambda: ctx
    )

    count = memory_retrieval_hit_db.insert_retrieval_hits(
        [{"tenant_id": "t1", "occurred_at": None}]
    )

    assert count == 0
    session.rollback.assert_called_once()
    inserted = session.add_all.call_args.args[0][0]
    assert inserted.source == "nexent"
    assert inserted.grounded is False
    assert inserted.day
    assert inserted.occurred_at is not None


def test_count_hits_since_applies_all_filters(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    query = MagicMock()
    query.filter.return_value = query
    query.scalar.return_value = None
    session.query.return_value = query
    monkeypatch.setattr(
        "backend.database.memory_retrieval_hit_db.get_db_session", lambda: ctx
    )

    from datetime import datetime

    count = memory_retrieval_hit_db.count_hits_since(
        "t1", user_id="u1", agent_id="a1", since=datetime(2026, 1, 1)
    )

    assert count == 0
    assert query.filter.call_count == 4


def test_count_hits_since_rolls_back_on_error(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(
        "backend.database.memory_retrieval_hit_db.get_db_session", lambda: ctx
    )

    assert memory_retrieval_hit_db.count_hits_since("t1") == 0
    session.rollback.assert_called_once()


def _make_hit(**overrides):
    values = {
        "hit_id": 1,
        "tenant_id": "t1",
        "user_id": "u1",
        "agent_id": "a1",
        "conversation_id": "c1",
        "memory_id": 7,
        "query_text": "hello",
        "query_hash": "hash",
        "retrieval_score": 0.75,
        "source": "nexent",
        "occurred_at": None,
        "day": "2026-01-01",
        "grounded": 1,
    }
    values.update(overrides)
    return MemoryRetrievalHit(**values)


def test_list_hits_for_memory_with_since_serializes_rows(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.all.return_value = [_make_hit()]
    session.query.return_value = query
    monkeypatch.setattr(
        "backend.database.memory_retrieval_hit_db.get_db_session", lambda: ctx
    )

    from datetime import datetime

    rows = memory_retrieval_hit_db.list_hits_for_memory(
        7, since=datetime(2026, 1, 1), limit=10
    )

    assert rows[0]["memory_id"] == 7
    assert rows[0]["retrieval_score"] == 0.75
    assert rows[0]["grounded"] is True
    assert query.filter.call_count == 2
    query.limit.assert_called_once_with(10)


def test_list_hits_for_memory_rolls_back_on_error(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(
        "backend.database.memory_retrieval_hit_db.get_db_session", lambda: ctx
    )

    assert memory_retrieval_hit_db.list_hits_for_memory(7) == []
    session.rollback.assert_called_once()


def test_list_hits_for_user_with_since(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.all.return_value = [_make_hit()]
    session.query.return_value = query
    monkeypatch.setattr(
        "backend.database.memory_retrieval_hit_db.get_db_session", lambda: ctx
    )

    from datetime import datetime

    rows = memory_retrieval_hit_db.list_hits_for_user(
        "t1", "u1", since=datetime(2026, 1, 1), limit=20
    )

    assert rows[0]["tenant_id"] == "t1"
    assert query.filter.call_count == 2
    query.limit.assert_called_once_with(20)


def test_list_hits_for_user_rolls_back_on_error(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(
        "backend.database.memory_retrieval_hit_db.get_db_session", lambda: ctx
    )

    assert memory_retrieval_hit_db.list_hits_for_user("t1", "u1") == []
    session.rollback.assert_called_once()


def test_aggregate_memory_stats_applies_scope_and_collects_dimensions(
    monkeypatch, mock_session_ctx
):
    session, ctx = mock_session_ctx
    query = MagicMock()
    query.filter.return_value = query
    query.group_by.return_value = query
    query.all.return_value = [(7, 3, 2), (None, 1, 1)]
    session.query.return_value = query
    monkeypatch.setattr(
        "backend.database.memory_retrieval_hit_db.get_db_session", lambda: ctx
    )
    monkeypatch.setattr(
        memory_retrieval_hit_db,
        "list_hits_for_memory",
        MagicMock(
            return_value=[
                {"day": "2026-01-01", "query_hash": "hash-1"},
                {"day": "2026-01-02", "query_hash": None},
                {"day": None, "query_hash": "hash-2"},
            ]
        ),
    )

    from datetime import datetime

    stats = memory_retrieval_hit_db.aggregate_memory_stats(
        "t1", user_id="u1", agent_id="a1", since=datetime(2026, 1, 1)
    )

    assert stats == [
        {
            "memory_id": 7,
            "hit_count": 3,
            "grounded_count": 2,
            "days": {"2026-01-01", "2026-01-02"},
            "query_hashes": {"hash-1", "hash-2"},
        }
    ]
    assert query.filter.call_count == 4


def test_aggregate_memory_stats_rolls_back_on_error(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(
        "backend.database.memory_retrieval_hit_db.get_db_session", lambda: ctx
    )

    assert memory_retrieval_hit_db.aggregate_memory_stats("t1") == []
    session.rollback.assert_called_once()


def test_delete_hits_before_rolls_back_on_error(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(
        "backend.database.memory_retrieval_hit_db.get_db_session", lambda: ctx
    )

    assert memory_retrieval_hit_db.delete_hits_before(object()) == 0
    session.rollback.assert_called_once()


def test_ac078_aggregate_dreaming_stats_filters_and_accumulates(monkeypatch):
    newer = datetime(2026, 1, 3)
    older = datetime(2026, 1, 2)
    monkeypatch.setattr(
        memory_retrieval_hit_db,
        "list_hits_for_user",
        MagicMock(return_value=[
            {"agent_id": "other", "memory_id": 1},
            {"agent_id": "a1", "memory_id": None},
            {
                "agent_id": "a1", "memory_id": 64, "grounded": True,
                "day": "2026-01-02", "query_hash": "q1",
                "retrieval_score": 0.4, "occurred_at": older,
            },
            {
                "agent_id": "a1", "memory_id": "64", "grounded": False,
                "day": "2026-01-03", "query_hash": "q2",
                "retrieval_score": 0.6, "occurred_at": newer,
            },
        ]),
    )

    result = memory_retrieval_hit_db.aggregate_dreaming_stats(
        "t1", "u1", "a1", since=datetime(2026, 1, 1)
    )

    assert result == [{
        "memory_id": 64,
        "hit_count": 2,
        "grounded_count": 1,
        "days": {"2026-01-02", "2026-01-03"},
        "query_hashes": {"q1", "q2"},
        "total_retrieval_score": 1.0,
        "last_recalled_at": newer,
    }]
