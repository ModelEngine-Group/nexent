"""Unit tests for ``backend.database.memory_retrieval_hit_db`` (Phase 2)."""

import sys
import types
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