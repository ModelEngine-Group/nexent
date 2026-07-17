"""Unit tests for ``backend.database.memory_record_db`` (Phase 2)."""

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


# Stub SQLAlchemy ``and_``
sqlalchemy_mod = types.ModuleType("sqlalchemy")
sqlalchemy_mod.and_ = lambda *args, **kwargs: ("and_", args, kwargs)
sys.modules["sqlalchemy"] = sqlalchemy_mod


# Stub db_models with column-level mocks so SQLAlchemy expressions can be
# compared without instantiating the real ORM.
db_models_mod = types.ModuleType("database.db_models")


class _Column:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return ("eq", self.name, other)

    def __ne__(self, other):
        return ("ne", self.name, other)

    def isnot(self, other):
        return ("isnot", self.name, other)


class MemoryRecord:
    # Class-level ``_Column`` references for SQLAlchemy query expressions.
    memory_id = _Column("memory_id")
    tenant_id = _Column("tenant_id")
    user_id = _Column("user_id")
    agent_id = _Column("agent_id")
    conversation_id = _Column("conversation_id")
    layer = _Column("layer")
    memory_type = _Column("memory_type")
    status = _Column("status")
    content = _Column("content")
    concept_tags = _Column("concept_tags")
    es_index_name = _Column("es_index_name")
    delete_flag = _Column("delete_flag")
    idempotency_key = _Column("idempotency_key")
    recall_count = _Column("recall_count")
    daily_count = _Column("daily_count")
    grounded_count = _Column("grounded_count")
    last_recalled_at = _Column("last_recalled_at")
    query_hashes = _Column("query_hashes")
    recall_days = _Column("recall_days")
    light_hits = _Column("light_hits")
    rem_hits = _Column("rem_hits")
    last_light_at = _Column("last_light_at")
    last_rem_at = _Column("last_rem_at")
    update_time = _Column("update_time")

    # ``__init__`` accepting arbitrary kwargs so that
    # ``MemoryRecord(**payload)`` from tests works (the real ORM accepts it too).
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


db_models_mod.MemoryRecord = MemoryRecord
sys.modules["database.db_models"] = db_models_mod
sys.modules["backend.database.db_models"] = db_models_mod


from backend.database import memory_record_db


@pytest.fixture
def mock_session_ctx():
    session = MagicMock(name="session")

    # Auto-assign ``memory_id`` on every ``session.add(row)`` so that
    # ``row.memory_id`` reflects the DB-assigned serial value after commit.
    _next_id = iter(range(1, 9999))

    def _auto_add(row):
        if hasattr(row, "memory_id") and getattr(row, "memory_id", None) is None:
            try:
                row.memory_id = next(_next_id)
            except StopIteration:
                pass

    session.add.side_effect = _auto_add
    ctx = MagicMock(name="ctx")
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    return session, ctx


def test_generate_memory_id_is_noop():
    # ``memory_id`` is now allocated by PostgreSQL ``serial4``; the helper
    # is preserved for API compatibility but always returns ``None``.
    assert memory_record_db.generate_memory_id() is None


def test_insert_memory_record_success(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    class _StubRow:
        memory_id = 42

    def _add(row):
        # Simulate SQLAlchemy flushing a row that picks up the serial PK.
        row.memory_id = _StubRow.memory_id

    session.add.side_effect = _add

    mid = memory_record_db.insert_memory_record(
        {
            "tenant_id": "t1",
            "user_id": "u1",
            "layer": "user",
            "content": "hello",
            "idempotency_key": "k1",
        }
    )

    assert mid == 42
    session.add.assert_called_once()
    session.commit.assert_called_once()


def test_insert_memory_record_failure(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.add.side_effect = Exception("boom")
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    mid = memory_record_db.insert_memory_record(
        {
            "tenant_id": "t1",
            "user_id": "u1",
            "layer": "user",
            "content": "hello",
            "idempotency_key": "k1",
        }
    )

    assert mid is None
    session.rollback.assert_called_once()


def test_upsert_memory_record_insert_path(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    # No existing record: ensure INSERT path runs.
    session.query.return_value.filter.return_value.first.return_value = None

    class _StubRow:
        memory_id = 7

    def _add(row):
        row.memory_id = _StubRow.memory_id

    session.add.side_effect = _add

    mid = memory_record_db.upsert_memory_record_by_idempotency(
        {
            "tenant_id": "t1",
            "user_id": "u1",
            "layer": "user",
            "content": "hi",
            "idempotency_key": "k1",
        }
    )

    assert mid == 7
    session.add.assert_called_once()
    session.commit.assert_called_once()


def test_upsert_memory_record_update_path(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx

    existing = MemoryRecord()
    existing.memory_id = 1
    existing.content = "old"
    existing.memory_type = "long_term"
    existing.es_index_name = None
    existing.concept_tags = []

    session.query.return_value.filter.return_value.first.return_value = existing
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    mid = memory_record_db.upsert_memory_record_by_idempotency(
        {
            "tenant_id": "t1",
            "user_id": "u1",
            "layer": "user",
            "content": "updated",
            "idempotency_key": "k1",
            "memory_type": "long_term",
        }
    )

    assert mid == 1
    assert existing.content == "updated"
    session.commit.assert_called_once()


def test_soft_delete_memory_record(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    query_chain = MagicMock()
    query_chain.update.return_value = 1
    session.query.return_value.filter.return_value = query_chain
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ok = memory_record_db.soft_delete_memory_record(1, "t1", updated_by="u1")

    assert ok is True
    query_chain.update.assert_called_once()
    session.commit.assert_called_once()


def test_list_memory_records_filters(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx

    query = MagicMock()
    session.query.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.all.return_value = []

    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    rows = memory_record_db.list_memory_records(
        "t1", user_id="u1", layer="agent", limit=10, offset=0
    )

    assert rows == []
    query.filter.assert_called()  # tenant + user + layer + status + delete_flag


def test_increment_recall_stats(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx

    record = MemoryRecord()
    record.memory_id = 1
    record.recall_count = 0
    record.daily_count = 0
    record.grounded_count = 0
    record.query_hashes = []
    record.recall_days = []

    session.query.return_value.filter.return_value.first.return_value = record
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ok = memory_record_db.increment_recall_stats(
        1, "t1", query_hash="qh", day="2026-07-13", grounded=True
    )

    assert ok is True
    assert record.recall_count == 1
    assert record.grounded_count == 1
    assert "qh" in record.query_hashes
    assert "2026-07-13" in record.recall_days


def test_apply_dreaming_phase_light(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    record = MemoryRecord()
    record.memory_id = 1
    record.light_hits = 0
    session.query.return_value.filter.return_value.first.return_value = record
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ok = memory_record_db.apply_dreaming_phase(1, "t1", phase="light")

    assert ok is True
    assert record.light_hits == 1
    assert record.last_light_at is not None


def test_apply_dreaming_phase_invalid(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    # ``apply_dreaming_phase`` catches ``Exception`` internally and returns
    # ``False`` for unknown phases (ValueError is swallowed), so we verify
    # the non-raising behaviour rather than expecting a raised ValueError.
    ok = memory_record_db.apply_dreaming_phase(1, "t1", phase="invalid")
    assert ok is False