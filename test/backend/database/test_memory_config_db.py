# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import sys
import types
from unittest.mock import MagicMock

import pytest


# Ensure backend imports resolve
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."))


# Stub management.db.client
client_mod = types.ModuleType("management.db.client")
client_mod.get_db_session = MagicMock(name="get_db_session")
client_mod.filter_property = MagicMock(name="filter_property")
sys.modules["management.db.client"] = client_mod
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["management.db.client"])
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["management.db.client"])
sys.modules["management.db.client"] = client_mod
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["management.db.client"])


# Stub db_models
db_models_mod = types.ModuleType("management.db.models")

class MemoryUserConfig:
    user_id = MagicMock(name="MemoryUserConfig.user_id")
    delete_flag = MagicMock(name="MemoryUserConfig.delete_flag")
    config_id = MagicMock(name="MemoryUserConfig.config_id")


db_models_mod.MemoryUserConfig = MemoryUserConfig
sys.modules["management.db.models"] = db_models_mod
sys.modules["management.db.models"] = db_models_mod


from management.db.memory.config import soft_delete_all_configs_by_user_id


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

    monkeypatch.setattr("management.db.memory.config.get_db_session", lambda: ctx)

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

    monkeypatch.setattr("management.db.memory.config.get_db_session", lambda: ctx)

    ok = soft_delete_all_configs_by_user_id("user-2", actor="user-2")

    assert ok is False
    session.rollback.assert_called_once()
