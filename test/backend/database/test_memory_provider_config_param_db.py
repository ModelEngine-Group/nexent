"""Unit tests for ``backend.database.memory_provider_config_param_db``."""

from unittest.mock import MagicMock

import pytest

from test.backend.database.db_test_support import FakeColumn, install_database_stubs


class MemoryProviderConfigParam:
    provider_config_id = FakeColumn("provider_config_id")
    param_name = FakeColumn("param_name")
    param_value = FakeColumn("param_value")
    delete_flag = FakeColumn("delete_flag")

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


install_database_stubs("MemoryProviderConfigParam", MemoryProviderConfigParam)

from backend.database.memory_provider_config_param_db import (
    delete_params,
    get_params,
    upsert_params,
)


@pytest.fixture
def mock_session_ctx():
    session = MagicMock(name="session")
    ctx = MagicMock(name="ctx")
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    return session, ctx


def _configure_update_result(session, row_count):
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update.return_value = row_count
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query


def test_get_params_empty(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.all.return_value = []
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_param_db.get_db_session", lambda: ctx)

    assert get_params(1) == {}


def test_get_params_with_results(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    rows = [
        MemoryProviderConfigParam(param_name="plugin.name", param_value="mem0"),
        MemoryProviderConfigParam(param_name="plugin.api_key", param_value="sk-123"),
    ]
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.all.return_value = rows
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query
    monkeypatch.setattr("backend.database.memory_provider_config_param_db.get_db_session", lambda: ctx)

    result = get_params(1)
    assert result == {"plugin.name": "mem0", "plugin.api_key": "sk-123"}


def test_upsert_params_insert_new(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    _configure_update_result(session, 0)
    monkeypatch.setattr("backend.database.memory_provider_config_param_db.get_db_session", lambda: ctx)

    assert upsert_params(1, {"plugin.name": "mem0"}) is True
    session.add.assert_called_once()
    session.commit.assert_called_once()


def test_upsert_params_replace_existing(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    _configure_update_result(session, 2)
    monkeypatch.setattr("backend.database.memory_provider_config_param_db.get_db_session", lambda: ctx)

    assert upsert_params(1, {"plugin.name": "new", "plugin.api_key": "new-key"}) is True
    assert session.add.call_count == 2
    session.commit.assert_called_once()


def test_upsert_params_failure(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.side_effect = Exception("db error")
    monkeypatch.setattr("backend.database.memory_provider_config_param_db.get_db_session", lambda: ctx)

    assert upsert_params(1, {"plugin.name": "x"}) is False
    session.rollback.assert_called_once()


def test_delete_params_success(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    _configure_update_result(session, 3)
    monkeypatch.setattr("backend.database.memory_provider_config_param_db.get_db_session", lambda: ctx)

    assert delete_params(1) is True
    session.commit.assert_called_once()


def test_delete_params_no_params_to_delete(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    _configure_update_result(session, 0)
    monkeypatch.setattr("backend.database.memory_provider_config_param_db.get_db_session", lambda: ctx)

    assert delete_params(1) is True


def test_delete_params_failure(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.query.side_effect = Exception("db error")
    monkeypatch.setattr("backend.database.memory_provider_config_param_db.get_db_session", lambda: ctx)

    assert delete_params(1) is False
    session.rollback.assert_called_once()
