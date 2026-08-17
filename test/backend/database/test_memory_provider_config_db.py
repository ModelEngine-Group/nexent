"""Unit tests for ``backend.database.memory_provider_config_db``."""

import sys
import types
from unittest.mock import MagicMock

import pytest

# Path setup
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."))

# Stub database.client
client_mod = types.ModuleType("database.client")
client_mod.get_db_session = MagicMock(name="get_db_session")
client_mod.filter_property = MagicMock(name="filter_property", side_effect=lambda d, _m: d)
sys.modules["database.client"] = client_mod
sys.modules["backend.database.client"] = client_mod

# Stub db_models
db_models_mod = types.ModuleType("database.db_models")


class _FakeColumn:
    """Minimal column proxy for filter expressions."""
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return ("eq", self.name, other)

    def __hash__(self):
        return hash(self.name)


class MemoryProviderConfig:
    provider_config_id = _FakeColumn("provider_config_id")
    tenant_id = _FakeColumn("tenant_id")
    provider_name = _FakeColumn("provider_name")
    connection_type = _FakeColumn("connection_type")
    enabled = _FakeColumn("enabled")
    timeout_seconds = _FakeColumn("timeout_seconds")
    last_error_code = _FakeColumn("last_error_code")
    create_time = _FakeColumn("create_time")
    update_time = _FakeColumn("update_time")
    created_by = _FakeColumn("created_by")
    updated_by = _FakeColumn("updated_by")
    delete_flag = _FakeColumn("delete_flag")

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


db_models_mod.MemoryProviderConfig = MemoryProviderConfig
sys.modules["database.db_models"] = db_models_mod
sys.modules["backend.database.db_models"] = db_models_mod

from backend.database.memory_provider_config_db import (
    disable_provider_config,
    get_provider_config,
    get_provider_config_by_name,
    insert_provider_config,
    list_provider_configs,
    soft_delete_provider_config,
    update_provider_config,
)


@pytest.fixture
def mock_session_ctx():
    session = MagicMock(name="session")
    ctx = MagicMock(name="ctx")
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    return session, ctx


# ---- get_provider_config ----

def test_get_provider_config_found(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    row = MemoryProviderConfig(
        provider_config_id=1, tenant_id="t1", provider_name="p1",
        connection_type="plugin", enabled=True, timeout_seconds=30,
        last_error_code=None, create_time=None, update_time=None,
        created_by="u1", updated_by="u1",
    )
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = row
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    result = get_provider_config(1)

    assert result is not None
    assert result["provider_config_id"] == 1
    assert result["provider_name"] == "p1"


def test_get_provider_config_not_found(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    assert get_provider_config(999) is None


# ---- get_provider_config_by_name ----

def test_get_provider_config_by_name_found(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    row = MemoryProviderConfig(
        provider_config_id=2, tenant_id="t1", provider_name="mem0",
        connection_type="plugin", enabled=False, timeout_seconds=30,
        last_error_code=None, create_time=None, update_time=None,
        created_by="u1", updated_by="u1",
    )
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = row
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    result = get_provider_config_by_name("t1", "mem0")

    assert result is not None
    assert result["provider_name"] == "mem0"


def test_get_provider_config_by_name_not_found(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    assert get_provider_config_by_name("t1", "nonexistent") is None


# ---- list_provider_configs ----

def test_list_provider_configs_empty(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.all.return_value = []
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    assert list_provider_configs("t1") == []


def test_list_provider_configs_with_results(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    rows = [
        MemoryProviderConfig(
            provider_config_id=i, tenant_id="t1", provider_name=f"p{i}",
            connection_type="plugin", enabled=True, timeout_seconds=30,
            last_error_code=None, create_time=None, update_time=None,
            created_by="u1", updated_by="u1",
        )
        for i in range(3)
    ]
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.all.return_value = rows
    mock_filter.filter.return_value = mock_filter
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    result = list_provider_configs("t1")
    assert len(result) == 3


def test_list_provider_configs_enabled_only(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.filter.return_value = mock_filter
    mock_filter.all.return_value = []
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    list_provider_configs("t1", enabled_only=True)
    # enabled_only adds an extra .filter() call
    assert mock_filter.filter.call_count == 1


# ---- insert_provider_config ----

def test_insert_provider_config_success(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx

    created_obj = MagicMock()
    created_obj.provider_config_id = 42

    def fake_add(obj):
        nonlocal created_obj
        created_obj = obj

    session.add.side_effect = fake_add

    def fake_refresh(obj):
        obj.provider_config_id = 42

    session.refresh.side_effect = fake_refresh
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    result = insert_provider_config({"tenant_id": "t1", "provider_name": "p1"})
    assert result == 42
    session.commit.assert_called_once()


def test_insert_provider_config_failure(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.add.side_effect = Exception("unique constraint")
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    result = insert_provider_config({"tenant_id": "t1", "provider_name": "dup"})
    assert result is None
    session.rollback.assert_called_once()


# ---- update_provider_config ----

def test_update_provider_config_success(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update.return_value = 1
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    assert update_provider_config(1, {"provider_name": "new_name"}) is True
    session.commit.assert_called_once()


def test_update_provider_config_failure(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update.side_effect = Exception("db error")
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    assert update_provider_config(1, {"provider_name": "x"}) is False
    session.rollback.assert_called_once()


# ---- soft_delete_provider_config ----

def test_soft_delete_provider_config_success(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update.return_value = 1
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    assert soft_delete_provider_config(1, "u1") is True
    session.commit.assert_called_once()


def test_soft_delete_provider_config_failure(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update.side_effect = Exception("db error")
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    assert soft_delete_provider_config(1, "u1") is False
    session.rollback.assert_called_once()


# ---- disable_provider_config ----

def test_disable_provider_config_success(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update.return_value = 1
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    assert disable_provider_config(1) is True
    session.commit.assert_called_once()


def test_disable_provider_config_failure(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update.side_effect = Exception("db error")
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_db.get_db_session", lambda: ctx)

    assert disable_provider_config(1) is False
    session.rollback.assert_called_once()
