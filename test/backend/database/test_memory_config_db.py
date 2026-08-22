import sys
import types
from unittest.mock import MagicMock

import pytest


# Ensure backend imports resolve
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."))


# Stub database.client
client_mod = types.ModuleType("database.client")
client_mod.get_db_session = MagicMock(name="get_db_session")
client_mod.filter_property = MagicMock(name="filter_property")
sys.modules["database.client"] = client_mod
sys.modules["backend.database.client"] = client_mod


# Stub db_models
db_models_mod = types.ModuleType("database.db_models")

class MemoryUserConfig:
    user_id = MagicMock(name="MemoryUserConfig.user_id")
    delete_flag = MagicMock(name="MemoryUserConfig.delete_flag")
    config_id = MagicMock(name="MemoryUserConfig.config_id")


db_models_mod.MemoryUserConfig = MemoryUserConfig
sys.modules["database.db_models"] = db_models_mod
sys.modules["backend.database.db_models"] = db_models_mod


from backend.database.memory_config_db import soft_delete_all_configs_by_user_id


@pytest.fixture
def mock_session_ctx():
    session = MagicMock(name="session")
    ctx = MagicMock(name="ctx")
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    return session, ctx


def test_soft_delete_all_configs_by_user_id_success(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    # Build query().filter().update(). commit() chain
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update.return_value = 5
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query

    monkeypatch.setattr("backend.database.memory_config_db.get_db_session", lambda: ctx)

    ok = soft_delete_all_configs_by_user_id("user-1", actor="user-1")

    assert ok is True
    session.query.assert_called_once()
    mock_filter.update.assert_called_once()
    session.commit.assert_called_once()


def test_soft_delete_all_configs_by_user_id_failure(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    mock_query = MagicMock()
    mock_filter = MagicMock()
    # Simulate exception from update
    mock_filter.update.side_effect = Exception("db error")
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query

    monkeypatch.setattr("backend.database.memory_config_db.get_db_session", lambda: ctx)

    ok = soft_delete_all_configs_by_user_id("user-2", actor="user-2")

    assert ok is False
    session.rollback.assert_called_once()
