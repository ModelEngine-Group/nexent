"""Unit tests for ``backend.database.memory_external_ingest_event_log_db``."""

import sys
import types
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."))

client_mod = types.ModuleType("database.client")
client_mod.get_db_session = MagicMock(name="get_db_session")
client_mod.filter_property = MagicMock(name="filter_property", side_effect=lambda d, _m: d)
sys.modules["database.client"] = client_mod
sys.modules["backend.database.client"] = client_mod

db_models_mod = types.ModuleType("database.db_models")


class _FakeColumn:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return ("eq", self.name, other)

    def __hash__(self):
        return hash(self.name)

    def desc(self):
        return ("desc", self.name)


class MemoryExternalIngestEventLog:
    log_id = _FakeColumn("log_id")
    provider = _FakeColumn("provider")
    tenant_id = _FakeColumn("tenant_id")
    user_id = _FakeColumn("user_id")
    agent_id = _FakeColumn("agent_id")
    conversation_id = _FakeColumn("conversation_id")
    event_id = _FakeColumn("event_id")
    idempotency_key = _FakeColumn("idempotency_key")
    unit_ids = _FakeColumn("unit_ids")
    response_status = _FakeColumn("response_status")
    response_summary = _FakeColumn("response_summary")
    sent_at = _FakeColumn("sent_at")
    create_time = _FakeColumn("create_time")
    delete_flag = _FakeColumn("delete_flag")

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


db_models_mod.MemoryExternalIngestEventLog = MemoryExternalIngestEventLog
sys.modules["database.db_models"] = db_models_mod
sys.modules["backend.database.db_models"] = db_models_mod

from backend.database.memory_external_ingest_event_log_db import (
    get_event_log_by_idempotency,
    insert_event_log,
    list_event_logs,
)


@pytest.fixture
def mock_session_ctx():
    session = MagicMock(name="session")
    ctx = MagicMock(name="ctx")
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    return session, ctx


def test_insert_event_log_success(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx

    def fake_refresh(obj):
        obj.log_id = 100

    session.refresh.side_effect = fake_refresh
    monkeypatch.setattr("backend.database.memory_external_ingest_event_log_db.get_db_session", lambda: ctx)

    result = insert_event_log({"provider": "mem0", "tenant_id": "t1"})
    assert result == 100
    session.add.assert_called_once()
    session.commit.assert_called_once()


def test_insert_event_log_failure(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.add.side_effect = Exception("db error")
    monkeypatch.setattr("backend.database.memory_external_ingest_event_log_db.get_db_session", lambda: ctx)

    assert insert_event_log({"provider": "x"}) is None
    session.rollback.assert_called_once()


def test_get_event_log_by_idempotency_found(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    row = MemoryExternalIngestEventLog(
        log_id=1, provider="mem0", tenant_id="t1", user_id="u1",
        agent_id="a1", conversation_id="c1", event_id="e1",
        idempotency_key="nexent:t1:a1:u1:c1:memory_stored:e1",
        unit_ids="1,2", response_status="ok", response_summary="ok",
        sent_at=None, create_time=None,
    )
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = row
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_external_ingest_event_log_db.get_db_session", lambda: ctx)

    result = get_event_log_by_idempotency("nexent:t1:a1:u1:c1:memory_stored:e1")
    assert result is not None
    assert result["log_id"] == 1
    assert result["provider"] == "mem0"


def test_get_event_log_by_idempotency_not_found(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_external_ingest_event_log_db.get_db_session", lambda: ctx)

    assert get_event_log_by_idempotency("nonexistent") is None


def test_list_event_logs_with_filters(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    rows = [
        MemoryExternalIngestEventLog(
            log_id=1, provider="mem0", tenant_id="t1", user_id="u1",
            agent_id="a1", conversation_id="c1", event_id="e1",
            idempotency_key="k1", unit_ids="1", response_status="ok",
            response_summary="ok", sent_at=None, create_time=None,
        )
    ]
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.filter.return_value = mock_filter
    mock_filter.order_by.return_value = mock_filter
    mock_filter.limit.return_value = mock_filter
    mock_filter.all.return_value = rows
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_external_ingest_event_log_db.get_db_session", lambda: ctx)

    result = list_event_logs("t1", user_id="u1", agent_id="a1", limit=10)
    assert len(result) == 1
    assert result[0]["provider"] == "mem0"
    assert mock_filter.filter.call_count == 2
    mock_filter.order_by.assert_called_once()
    mock_filter.limit.assert_called_once_with(10)


def test_list_event_logs_default_limit(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_filter
    mock_filter.limit.return_value = mock_filter
    mock_filter.all.return_value = []
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_external_ingest_event_log_db.get_db_session", lambda: ctx)

    result = list_event_logs("t1")
    assert result == []
    mock_filter.limit.assert_called_once_with(50)
