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
sqlalchemy_mod.String = str
sqlalchemy_mod.cast = lambda value, target: value
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

    def label(self, _name):
        return self

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

    def in_(self, values):
        return ("in_", self.name, list(values))


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


class AgentInfo:
    agent_id = _Column("agent_id")
    version_no = _Column("version_no")
    display_name = _Column("display_name")
    name = _Column("name")
    delete_flag = _Column("delete_flag")


class ConversationRecord:
    conversation_id = _Column("conversation_id")
    conversation_title = _Column("conversation_title")
    delete_flag = _Column("delete_flag")


db_models_mod.MemoryRecord = MemoryRecord
db_models_mod.AgentInfo = AgentInfo
db_models_mod.ConversationRecord = ConversationRecord
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
    query.outerjoin.return_value = query
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


def test_list_memory_records_enriches_agent_and_conversation(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    record = MemoryRecord(
        memory_id=1,
        tenant_id="t1",
        user_id="u1",
        agent_id="7",
        conversation_id="9",
        layer="agent",
        memory_type="short_term",
        status="active",
        content="remember this",
        concept_tags=[],
        es_index_name=None,
        create_time=None,
        update_time=None,
        created_by="u1",
        updated_by="u1",
        delete_flag="N",
        idempotency_key="key",
        recall_count=0,
        daily_count=0,
        grounded_count=0,
        last_recalled_at=None,
        query_hashes=[],
        recall_days=[],
        light_hits=0,
        rem_hits=0,
        last_light_at=None,
        last_rem_at=None,
    )
    query = MagicMock()
    session.query.return_value = query
    query.outerjoin.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.all.return_value = [(record, "Agent Seven", "agent-seven", "Source chat")]
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    rows = memory_record_db.list_memory_records(
        "t1", user_id="u1", layer="agent", status=""
    )

    assert rows[0]["agent_name"] == "Agent Seven"
    assert rows[0]["conversation_title"] == "Source chat"


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


def test_upsert_memory_record_requires_tenant_id(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    with pytest.raises(ValueError):
        memory_record_db.upsert_memory_record_by_idempotency(
            {"tenant_id": "", "idempotency_key": "k1"}
        )

    with pytest.raises(ValueError):
        memory_record_db.upsert_memory_record_by_idempotency(
            {"tenant_id": "t1", "idempotency_key": ""}
        )

    with pytest.raises(ValueError):
        memory_record_db.upsert_memory_record_by_idempotency(
            {"idempotency_key": "k1"}
        )


def test_upsert_memory_record_failure(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.return_value.filter.return_value.first.side_effect = Exception(
        "boom"
    )
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    mid = memory_record_db.upsert_memory_record_by_idempotency(
        {"tenant_id": "t1", "idempotency_key": "k1"}
    )
    assert mid is None
    session.rollback.assert_called()


def test_update_memory_record_success(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    query_chain = MagicMock()
    query_chain.update.return_value = 1
    session.query.return_value.filter.return_value = query_chain
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ok = memory_record_db.update_memory_record(
        1, "t1", {"content": "new", "updated_by": "u1"}
    )
    assert ok is True
    query_chain.update.assert_called_once()
    session.commit.assert_called_once()


def test_update_memory_record_not_found(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    query_chain = MagicMock()
    query_chain.update.return_value = 0
    session.query.return_value.filter.return_value = query_chain
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ok = memory_record_db.update_memory_record(999, "t1", {"content": "x"})
    assert ok is False


def test_update_memory_record_failure(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.return_value.filter.return_value.update.side_effect = Exception(
        "boom"
    )
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ok = memory_record_db.update_memory_record(1, "t1", {"content": "x"})
    assert ok is False
    session.rollback.assert_called()


def test_soft_delete_memory_record_not_found(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    query_chain = MagicMock()
    query_chain.update.return_value = 0
    session.query.return_value.filter.return_value = query_chain
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ok = memory_record_db.soft_delete_memory_record(999, "t1")
    assert ok is False


def test_soft_delete_memory_record_failure(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.return_value.filter.return_value.update.side_effect = Exception(
        "boom"
    )
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ok = memory_record_db.soft_delete_memory_record(1, "t1")
    assert ok is False
    session.rollback.assert_called()


def test_get_memory_record_success(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    record = MemoryRecord(
        memory_id=1,
        tenant_id="t1",
        user_id="u1",
        agent_id="a1",
        conversation_id="c1",
        layer="user",
        memory_type="long_term",
        status="active",
        content="hello",
        concept_tags=["tag"],
        es_index_name=None,
        create_time=None,
        update_time=None,
        created_by="u1",
        updated_by="u1",
        delete_flag="N",
        idempotency_key="key",
        query_hashes=[],
        recall_days=[],
        recall_count=0,
        daily_count=0,
        grounded_count=0,
        light_hits=0,
        rem_hits=0,
        last_recalled_at=None,
        last_light_at=None,
        last_rem_at=None,
    )
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = record
    session.query.return_value = query
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    row = memory_record_db.get_memory_record(1, "t1")
    assert row is not None
    assert row["memory_id"] == 1
    assert row["content"] == "hello"


def test_get_memory_record_not_found(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = None
    session.query.return_value = query
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    row = memory_record_db.get_memory_record(999, "t1")
    assert row is None


def test_get_memory_record_include_deleted(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    record = MemoryRecord(
        memory_id=2,
        tenant_id="t1",
        user_id="u1",
        agent_id=None,
        conversation_id=None,
        layer="user",
        memory_type="long_term",
        status="archived",
        content="x",
        concept_tags=[],
        es_index_name=None,
        create_time=None,
        update_time=None,
        created_by="u1",
        updated_by="u1",
        delete_flag="Y",
        idempotency_key="k",
        query_hashes=[],
        recall_days=[],
        recall_count=0,
        daily_count=0,
        grounded_count=0,
        light_hits=0,
        rem_hits=0,
        last_recalled_at=None,
        last_light_at=None,
        last_rem_at=None,
    )
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = record
    session.query.return_value = query
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    row = memory_record_db.get_memory_record(2, "t1", include_deleted=True)
    assert row is not None
    assert row["delete_flag"] == "Y"


def test_get_memory_record_exception(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.return_value.filter.side_effect = Exception("boom")
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    row = memory_record_db.get_memory_record(1, "t1")
    assert row is None
    session.rollback.assert_called()


def test_list_memory_records_normalizes_empty_filters(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    query = MagicMock()
    session.query.return_value = query
    query.outerjoin.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.all.return_value = []
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    # Pass empty-string filters so the normalization branches run.
    rows = memory_record_db.list_memory_records(
        "t1",
        user_id="",
        agent_id="",
        conversation_id="",
        layer="",
        memory_type="",
        status="archived",
        include_deleted=True,
    )
    assert rows == []
    query.filter.assert_called()


def test_list_memory_records_with_status_filter(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    query = MagicMock()
    session.query.return_value = query
    query.outerjoin.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.all.return_value = []
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    rows = memory_record_db.list_memory_records(
        "t1",
        user_id="u1",
        agent_id="a1",
        conversation_id="c1",
        layer="agent",
        memory_type="short_term",
        status="archived",
    )
    assert rows == []
    query.filter.assert_called()


def test_list_memory_records_exception(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.return_value.outerjoin.side_effect = Exception("boom")
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    rows = memory_record_db.list_memory_records("t1")
    assert rows == []
    session.rollback.assert_called()


def test_list_active_memory_ids_by_layer(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    query = MagicMock()
    query.filter.return_value = query
    query.all.return_value = [(1,), (2,), (3,)]
    session.query.return_value = query
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ids = memory_record_db.list_active_memory_ids_by_layer(
        "t1", "agent", user_id="u1", agent_id="a1"
    )
    assert ids == [1, 2, 3]
    query.filter.assert_called()


def test_list_active_memory_ids_by_layer_exception(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.return_value.filter.side_effect = Exception("boom")
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ids = memory_record_db.list_active_memory_ids_by_layer("t1", "agent")
    assert ids == []
    session.rollback.assert_called()


def test_get_memory_records_by_ids_empty():
    # Empty input short-circuits before opening a session.
    assert memory_record_db.get_memory_records_by_ids([], "t1") == []


def test_get_memory_records_by_ids_success(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    record = MemoryRecord(
        memory_id=1,
        tenant_id="t1",
        user_id="u1",
        agent_id=None,
        conversation_id=None,
        layer="user",
        memory_type="long_term",
        status="active",
        content="hello",
        concept_tags=[],
        es_index_name=None,
        create_time=None,
        update_time=None,
        created_by="u1",
        updated_by="u1",
        delete_flag="N",
        idempotency_key="k",
        query_hashes=[],
        recall_days=[],
        recall_count=0,
        daily_count=0,
        grounded_count=0,
        light_hits=0,
        rem_hits=0,
        last_recalled_at=None,
        last_light_at=None,
        last_rem_at=None,
    )
    query = MagicMock()
    query.filter.return_value = query
    query.all.return_value = [record]
    session.query.return_value = query
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    rows = memory_record_db.get_memory_records_by_ids([1, 2], "t1")
    assert len(rows) == 1
    assert rows[0]["memory_id"] == 1


def test_get_memory_records_by_ids_exception(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.return_value.filter.side_effect = Exception("boom")
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    rows = memory_record_db.get_memory_records_by_ids([1], "t1")
    assert rows == []
    session.rollback.assert_called()


def test_find_by_idempotency_success(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    record = MemoryRecord(
        memory_id=1,
        tenant_id="t1",
        user_id="u1",
        agent_id=None,
        conversation_id=None,
        layer="user",
        memory_type="long_term",
        status="active",
        content="hi",
        concept_tags=[],
        es_index_name=None,
        create_time=None,
        update_time=None,
        created_by="u1",
        updated_by="u1",
        delete_flag="N",
        idempotency_key="k",
        query_hashes=[],
        recall_days=[],
        recall_count=0,
        daily_count=0,
        grounded_count=0,
        light_hits=0,
        rem_hits=0,
        last_recalled_at=None,
        last_light_at=None,
        last_rem_at=None,
    )
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = record
    session.query.return_value = query
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    row = memory_record_db.find_by_idempotency("t1", "k")
    assert row is not None
    assert row["memory_id"] == 1


def test_find_by_idempotency_not_found(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = None
    session.query.return_value = query
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    row = memory_record_db.find_by_idempotency("t1", "missing")
    assert row is None


def test_find_by_idempotency_exception(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.return_value.filter.side_effect = Exception("boom")
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    row = memory_record_db.find_by_idempotency("t1", "k")
    assert row is None
    session.rollback.assert_called()


def test_increment_recall_stats_not_found(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.return_value.filter.return_value.first.return_value = None
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ok = memory_record_db.increment_recall_stats(999, "t1")
    assert ok is False
    session.commit.assert_not_called()


def test_increment_recall_stats_dedup(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx

    record = MemoryRecord()
    record.memory_id = 1
    record.recall_count = 5
    record.daily_count = 5
    record.grounded_count = 2
    record.query_hashes = ["qh-existing"]
    record.recall_days = ["2026-07-12"]

    session.query.return_value.filter.return_value.first.return_value = record
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ok = memory_record_db.increment_recall_stats(
        1, "t1", query_hash="qh-existing", day="2026-07-12", grounded=False
    )
    assert ok is True
    # Counter increments are 1 each because the ``or 0`` defaults handle None.
    assert record.recall_count == 6
    assert record.daily_count == 6
    assert record.grounded_count == 2  # unchanged because grounded=False
    # No duplicates appended.
    assert record.query_hashes == ["qh-existing"]
    assert record.recall_days == ["2026-07-12"]


def test_increment_recall_stats_exception(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.return_value.filter.return_value.first.side_effect = Exception(
        "boom"
    )
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ok = memory_record_db.increment_recall_stats(1, "t1")
    assert ok is False
    session.rollback.assert_called()


def test_apply_dreaming_phase_rem(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    record = MemoryRecord()
    record.memory_id = 1
    record.rem_hits = 0
    session.query.return_value.filter.return_value.first.return_value = record
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ok = memory_record_db.apply_dreaming_phase(1, "t1", phase="rem")
    assert ok is True
    assert record.rem_hits == 1
    assert record.last_rem_at is not None


def test_apply_dreaming_phase_not_found(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.return_value.filter.return_value.first.return_value = None
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ok = memory_record_db.apply_dreaming_phase(999, "t1", phase="light")
    assert ok is False


def test_apply_dreaming_phase_exception(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.return_value.filter.return_value.first.side_effect = Exception(
        "boom"
    )
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    ok = memory_record_db.apply_dreaming_phase(1, "t1", phase="light")
    assert ok is False
    session.rollback.assert_called()


def test_list_memories_for_dreaming(monkeypatch, mock_session_ctx):
    from datetime import datetime, timedelta

    session, ctx = mock_session_ctx

    recent = MemoryRecord()
    recent.memory_id = 1
    recent.last_recalled_at = datetime.utcnow()
    recent.tenant_id = "t1"
    recent.user_id = "u1"
    recent.layer = "agent"
    recent.memory_type = "short_term"
    recent.status = "active"
    recent.content = "fresh"
    recent.concept_tags = []
    recent.es_index_name = None
    recent.create_time = None
    recent.update_time = None
    recent.created_by = "u1"
    recent.updated_by = "u1"
    recent.delete_flag = "N"
    recent.idempotency_key = "k1"
    recent.recall_count = 1
    recent.daily_count = 1
    recent.grounded_count = 0
    recent.query_hashes = []
    recent.recall_days = []
    recent.light_hits = 0
    recent.rem_hits = 0
    recent.last_light_at = None
    recent.last_rem_at = None

    stale = MemoryRecord()
    stale.memory_id = 2
    stale.last_recalled_at = datetime.utcnow() - timedelta(days=30)

    none_recall = MemoryRecord()
    none_recall.memory_id = 3
    none_recall.last_recalled_at = None

    query = MagicMock()
    query.filter.return_value = query
    query.all.return_value = [recent, stale, none_recall]
    session.query.return_value = query
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    rows = memory_record_db.list_memories_for_dreaming(
        "t1", user_id="u1", layer="agent", min_recall_count=1, window_days=7
    )
    assert len(rows) == 1
    assert rows[0]["memory_id"] == 1


def test_list_memories_for_dreaming_exception(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.return_value.filter.side_effect = Exception("boom")
    monkeypatch.setattr(
        "backend.database.memory_record_db.get_db_session", lambda: ctx
    )

    rows = memory_record_db.list_memories_for_dreaming("t1", user_id="u1")
    assert rows == []
    session.rollback.assert_called()


def test_record_to_dict_with_non_datetime_value():
    # ``_isoformat_or_none`` falls through and returns the raw value when it
    # has no ``isoformat`` method.
    record = MemoryRecord(
        memory_id=1,
        tenant_id="t1",
        user_id="u1",
        agent_id=None,
        conversation_id=None,
        layer="user",
        memory_type="long_term",
        status="active",
        content="x",
        concept_tags=None,
        es_index_name=None,
        create_time="not-a-datetime",
        update_time=None,
        created_by="u1",
        updated_by="u1",
        delete_flag="N",
        idempotency_key="k",
        query_hashes=None,
        recall_days=None,
        recall_count=None,
        daily_count=None,
        grounded_count=None,
        light_hits=None,
        rem_hits=None,
        last_light_at=None,
        last_rem_at=None,
        last_recalled_at=None,
    )

    row = memory_record_db._record_to_dict(record)
    assert row["concept_tags"] == []
    assert row["query_hashes"] == []
    assert row["recall_days"] == []
    assert row["recall_count"] == 0
    assert row["create_time"] == "not-a-datetime"


def test_isoformat_or_none_with_datetime():
    from datetime import datetime

    dt = datetime(2026, 1, 2, 3, 4, 5)
    assert memory_record_db._isoformat_or_none(dt) == dt.isoformat()


def test_isoformat_or_none_with_none():
    assert memory_record_db._isoformat_or_none(None) is None


def test_isoformat_or_none_with_other_value():
    # Non-datetime values are returned unchanged.
    assert memory_record_db._isoformat_or_none("plain") == "plain"
