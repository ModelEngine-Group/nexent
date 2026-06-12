"""
Unit tests for backend/database/remote_mcp_db.py

Tests all MCP record database operations with comprehensive coverage.
Uses mocked database sessions to avoid real DB connections.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

import pytest
from unittest.mock import MagicMock

# First mock the consts module to avoid ModuleNotFoundError
consts_mock = MagicMock()
consts_mock.const = MagicMock()
# Set constants needed in consts.const
consts_mock.const.MINIO_ENDPOINT = "http://localhost:9000"
consts_mock.const.MINIO_ACCESS_KEY = "test_access_key"
consts_mock.const.MINIO_SECRET_KEY = "test_secret_key"
consts_mock.const.MINIO_REGION = "us-east-1"
consts_mock.const.MINIO_DEFAULT_BUCKET = "test-bucket"
consts_mock.const.POSTGRES_HOST = "localhost"
consts_mock.const.POSTGRES_USER = "test_user"
consts_mock.const.NEXENT_POSTGRES_PASSWORD = "test_password"
consts_mock.const.POSTGRES_DB = "test_db"
consts_mock.const.POSTGRES_PORT = 5432
consts_mock.const.DEFAULT_TENANT_ID = "default_tenant"

# Add the mocked consts module to sys.modules
sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_mock.const

# Mock utils
utils_mock = MagicMock()
utils_mock.auth_utils = MagicMock()
utils_mock.auth_utils.get_current_user_id_from_token = MagicMock(return_value="test_user_id")
sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_mock.auth_utils

# Mock boto3
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Mock client module
client_mock = MagicMock()
client_mock.MinioClient = MagicMock()
client_mock.PostgresClient = MagicMock()
client_mock.db_client = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock()
client_mock.filter_property = MagicMock()
sys.modules['database.client'] = client_mock
sys.modules['backend.database.client'] = client_mock

# Mock db_models
db_models_mock = MagicMock()
db_models_mock.McpRecord = MagicMock()
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# Mock exceptions
exceptions_mock = MagicMock()
sys.modules['consts.exceptions'] = exceptions_mock
sys.modules['backend.consts.exceptions'] = exceptions_mock

# Now import the functions to be tested
from backend.database.remote_mcp_db import (
    create_mcp_record,
    delete_mcp_record_by_name_and_url,
    delete_mcp_record_by_container_id,
    update_mcp_status_by_name_and_url,
    update_mcp_record_by_name_and_url,
    update_mcp_record_manage_fields_by_id,
    update_mcp_record_enabled_by_id,
    update_mcp_record_status_by_id,
    update_mcp_record_container_fields_by_id,
    delete_mcp_record_by_id,
    get_mcp_records_by_tenant,
    get_mcp_records_by_container_port,
    get_mcp_server_by_name_and_tenant,
    get_mcp_authorization_token_by_name_and_url,
    get_mcp_record_by_id_and_tenant,
    get_mcp_custom_headers_by_name_and_url,
    check_mcp_name_exists,
    check_enabled_mcp_name_exists,
)


class MockMcpRecord:
    def __init__(self):
        self.mcp_id = 1
        self.mcp_name = "test_mcp"
        self.mcp_server = "http://test.server.com"
        self.tenant_id = "tenant1"
        self.user_id = "user1"
        self.status = True
        self.delete_flag = "N"
        self.container_id = "container-1"
        self.authorization_token = "test_token_123"
        self.custom_headers = None
        self.create_time = "2024-01-01 00:00:00"
        self.__dict__ = {
            "mcp_id": 1,
            "mcp_name": "test_mcp",
            "mcp_server": "http://test.server.com",
            "tenant_id": "tenant1",
            "user_id": "user1",
            "status": True,
            "delete_flag": "N",
            "container_id": "container-1",
            "authorization_token": "test_token_123",
            "custom_headers": None,
            "create_time": "2024-01-01 00:00:00",
        }


@pytest.fixture
def mock_session():
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    return mock_session, mock_query


# ============================================================================
# create_mcp_record
# ============================================================================

def test_create_mcp_record_success(monkeypatch, mock_session):
    session, _ = mock_session
    session.add = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.remote_mcp_db.filter_property", lambda data, model: data)
    monkeypatch.setattr("backend.database.remote_mcp_db.McpRecord", lambda **kwargs: MagicMock())

    mcp_data = {"mcp_name": "test_mcp", "mcp_server": "http://test.server.com", "status": True}
    create_mcp_record(mcp_data, "tenant1", "user1")
    session.add.assert_called_once()


def test_create_mcp_record_with_custom_headers(monkeypatch, mock_session):
    """Test that custom_headers is included in the allowed fields (line 29 coverage)"""
    session, _ = mock_session
    session.add = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.remote_mcp_db.filter_property", lambda data, model: data)

    captured_kwargs = {}

    def mock_mcp_record(**kwargs):
        captured_kwargs.update(kwargs)
        return MagicMock()

    monkeypatch.setattr("backend.database.remote_mcp_db.McpRecord", mock_mcp_record)

    custom_headers = {"X-Custom-Auth": "Bearer token123", "X-Api-Key": "apikey"}
    mcp_data = {
        "mcp_name": "test_mcp",
        "mcp_server": "http://test.server.com",
        "status": True,
        "custom_headers": custom_headers,
    }
    create_mcp_record(mcp_data, "tenant1", "user1")

    assert captured_kwargs.get("custom_headers") == custom_headers


def test_create_mcp_record_failure(monkeypatch, mock_session):
    from sqlalchemy.exc import SQLAlchemyError

    session, _ = mock_session
    session.add = MagicMock(side_effect=SQLAlchemyError("Database error"))
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.remote_mcp_db.filter_property", lambda data, model: data)
    monkeypatch.setattr("backend.database.remote_mcp_db.McpRecord", lambda **kwargs: MagicMock())

    with pytest.raises(SQLAlchemyError):
        create_mcp_record({"mcp_name": "test_mcp"}, "tenant1", "user1")


# ============================================================================
# delete_mcp_record_by_name_and_url
# ============================================================================

def test_delete_mcp_record_by_name_and_url_success(monkeypatch, mock_session):
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    delete_mcp_record_by_name_and_url("test_mcp", "http://test.server.com", "tenant1", "user1")
    mock_update.assert_called_once_with({"delete_flag": "Y", "updated_by": "user1"})


# ============================================================================
# delete_mcp_record_by_container_id
# ============================================================================

def test_delete_mcp_record_by_container_id_success(monkeypatch, mock_session):
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    delete_mcp_record_by_container_id("container-1", "tenant1", "user1")
    mock_update.assert_called_once_with({"delete_flag": "Y", "updated_by": "user1"})


# ============================================================================
# update_mcp_status_by_name_and_url
# ============================================================================

def test_update_mcp_status_by_name_and_url_success(monkeypatch, mock_session):
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    update_mcp_status_by_name_and_url("test_mcp", "http://test.server.com", "tenant1", "user1", False)
    mock_update.assert_called_once_with({"status": False, "updated_by": "user1"})


# ============================================================================
# get_mcp_records_by_tenant
# ============================================================================

def test_get_mcp_records_by_tenant_success(monkeypatch, mock_session):
    session, query = mock_session
    mock_mcp1 = MockMcpRecord()
    mock_mcp2 = MockMcpRecord()
    mock_mcp2.mcp_name = "test_mcp2"
    mock_mcp2.__dict__["mcp_name"] = "test_mcp2"

    mock_order_by = MagicMock()
    mock_order_by.all.return_value = [mock_mcp1, mock_mcp2]
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order_by
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.remote_mcp_db.as_dict", lambda obj: obj.__dict__)

    result = get_mcp_records_by_tenant("tenant1")
    assert len(result) == 2
    assert result[0]["mcp_name"] == "test_mcp"


def test_get_mcp_records_by_tenant_with_tag(monkeypatch, mock_session):
    session, query = mock_session
    mock_mcp = MockMcpRecord()

    mock_order_by = MagicMock()
    mock_order_by.all.return_value = [mock_mcp]
    mock_filter2 = MagicMock()
    mock_filter2.order_by.return_value = mock_order_by
    mock_filter = MagicMock()
    mock_filter.filter.return_value = mock_filter2
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.remote_mcp_db.as_dict", lambda obj: obj.__dict__)

    result = get_mcp_records_by_tenant("tenant1", tag="test-tag")
    assert len(result) == 1


# ============================================================================
# get_mcp_records_by_container_port (NEW)
# ============================================================================

def test_get_mcp_records_by_container_port_found(monkeypatch, mock_session):
    session, query = mock_session
    mock_mcp = MockMcpRecord()

    mock_order_by = MagicMock()
    mock_order_by.all.return_value = [mock_mcp]
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order_by
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.remote_mcp_db.as_dict", lambda obj: obj.__dict__)

    result = get_mcp_records_by_container_port(8080)
    assert len(result) == 1


def test_get_mcp_records_by_container_port_empty(monkeypatch, mock_session):
    session, query = mock_session

    mock_order_by = MagicMock()
    mock_order_by.all.return_value = []
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order_by
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    result = get_mcp_records_by_container_port(8080)
    assert len(result) == 0


# ============================================================================
# update_mcp_record_manage_fields_by_id (NEW)
# ============================================================================

def test_update_mcp_record_manage_fields_by_id_success(monkeypatch, mock_session):
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    update_mcp_record_manage_fields_by_id(
        mcp_id=1, tenant_id="tid", user_id="uid",
        name="new-name", server_url="http://new.url",
        description="desc", tags=["a"], source="local",
        authorization_token="tok", custom_headers=None, config_json={"key": "val"},
    )
    mock_update.assert_called_once()
    call_args = mock_update.call_args[0][0]
    assert call_args["mcp_name"] == "new-name"
    assert call_args["mcp_server"] == "http://new.url"
    assert call_args["tags"] == ["a"]
    assert call_args["config_json"] == {"key": "val"}


def test_update_mcp_record_manage_fields_by_id_none_tags(monkeypatch, mock_session):
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    update_mcp_record_manage_fields_by_id(
        mcp_id=1, tenant_id="tid", user_id="uid",
        name="n", server_url="u", description=None,
        tags=None, source="local", authorization_token=None,
        custom_headers=None, config_json=None,
    )
    call_args = mock_update.call_args[0][0]
    assert call_args["tags"] == []


def test_update_mcp_record_manage_fields_by_id_with_custom_headers(monkeypatch, mock_session):
    """Test custom_headers parameter in update_mcp_record_manage_fields_by_id (lines 146, 162)"""
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    custom_headers = {"X-Custom-Header": "value123", "Authorization": "Bearer token"}
    update_mcp_record_manage_fields_by_id(
        mcp_id=1, tenant_id="tid", user_id="uid",
        name="new-name", server_url="http://new.url",
        description="updated description", tags=["tag1", "tag2"],
        source="community", authorization_token="new_token",
        custom_headers=custom_headers,
        config_json={"timeout": 30},
    )
    mock_update.assert_called_once()
    call_args = mock_update.call_args[0][0]
    assert call_args["custom_headers"] == custom_headers
    assert call_args["mcp_name"] == "new-name"
    assert call_args["authorization_token"] == "new_token"


# ============================================================================
# update_mcp_record_enabled_by_id (NEW)
# ============================================================================

def test_update_mcp_record_enabled_by_id(monkeypatch, mock_session):
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    update_mcp_record_enabled_by_id(mcp_id=1, tenant_id="tid", user_id="uid", enabled=True)
    mock_update.assert_called_once_with({"enabled": True, "updated_by": "uid"})

    update_mcp_record_enabled_by_id(mcp_id=2, tenant_id="tid", user_id="uid", enabled=False)
    assert mock_update.call_count == 2


# ============================================================================
# update_mcp_record_status_by_id (NEW)
# ============================================================================

def test_update_mcp_record_status_by_id(monkeypatch, mock_session):
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    update_mcp_record_status_by_id(mcp_id=1, tenant_id="tid", user_id="uid", status=True)
    mock_update.assert_called_once_with({"status": True, "updated_by": "uid"})


# ============================================================================
# update_mcp_record_container_fields_by_id (NEW)
# ============================================================================

def test_update_mcp_record_container_fields_by_id(monkeypatch, mock_session):
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    update_mcp_record_container_fields_by_id(
        mcp_id=1, tenant_id="tid", user_id="uid",
        container_id="cid", container_port=8080,
        mcp_server="http://srv/mcp", status=True,
    )
    mock_update.assert_called_once()
    call_args = mock_update.call_args[0][0]
    assert call_args["container_id"] == "cid"
    assert call_args["container_port"] == 8080
    assert call_args["mcp_server"] == "http://srv/mcp"
    assert call_args["status"] is True


def test_update_mcp_record_container_fields_by_id_none_values(monkeypatch, mock_session):
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    update_mcp_record_container_fields_by_id(
        mcp_id=1, tenant_id="tid", user_id="uid",
        container_id=None, container_port=None,
        mcp_server="http://srv/mcp", status=None,
    )
    call_args = mock_update.call_args[0][0]
    assert call_args["container_id"] is None
    assert call_args["status"] is None


# ============================================================================
# delete_mcp_record_by_id (NEW)
# ============================================================================

def test_delete_mcp_record_by_id(monkeypatch, mock_session):
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    delete_mcp_record_by_id(mcp_id=1, tenant_id="tid", user_id="uid")
    mock_update.assert_called_once_with({"delete_flag": "Y", "updated_by": "uid"})


# ============================================================================
# get_mcp_server_by_name_and_tenant
# ============================================================================

def test_get_mcp_server_by_name_and_tenant_success(monkeypatch, mock_session):
    session, query = mock_session
    mock_mcp = MockMcpRecord()

    mock_first = MagicMock()
    mock_first.return_value = mock_mcp
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    result = get_mcp_server_by_name_and_tenant("test_mcp", "tenant1")
    assert result == "http://test.server.com"


def test_get_mcp_server_by_name_and_tenant_not_found(monkeypatch, mock_session):
    session, query = mock_session

    mock_first = MagicMock()
    mock_first.return_value = None
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    result = get_mcp_server_by_name_and_tenant("nonexistent", "tenant1")
    assert result == ""


# ============================================================================
# get_mcp_authorization_token_by_name_and_url
# ============================================================================

def test_get_mcp_authorization_token_success(monkeypatch, mock_session):
    session, query = mock_session
    mock_mcp = MockMcpRecord()
    mock_mcp.authorization_token = "bearer_token_123"

    mock_first = MagicMock()
    mock_first.return_value = mock_mcp
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    result = get_mcp_authorization_token_by_name_and_url("test_mcp", "http://test.server.com", "tenant1")
    assert result == "bearer_token_123"


def test_get_mcp_authorization_token_not_found(monkeypatch, mock_session):
    session, query = mock_session

    mock_first = MagicMock()
    mock_first.return_value = None
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    result = get_mcp_authorization_token_by_name_and_url("nonexistent", "http://test.server.com", "tenant1")
    assert result is None


# ============================================================================
# get_mcp_custom_headers_by_name_and_url (NEW - lines 277-294)
# ============================================================================

def test_get_mcp_custom_headers_by_name_and_url_success(monkeypatch, mock_session):
    """Test get_mcp_custom_headers_by_name_and_url when record exists (lines 277-294)"""
    session, query = mock_session
    mock_mcp = MockMcpRecord()
    expected_headers = {"X-Custom-Auth": "Bearer token123", "X-Api-Key": "apikey"}
    mock_mcp.custom_headers = expected_headers

    mock_first = MagicMock()
    mock_first.return_value = mock_mcp
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    result = get_mcp_custom_headers_by_name_and_url("test_mcp", "http://test.server.com", "tenant1")
    assert result == expected_headers


def test_get_mcp_custom_headers_by_name_and_url_not_found(monkeypatch, mock_session):
    """Test get_mcp_custom_headers_by_name_and_url when record does not exist (lines 277-294)"""
    session, query = mock_session

    mock_first = MagicMock()
    mock_first.return_value = None
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    result = get_mcp_custom_headers_by_name_and_url("nonexistent", "http://test.server.com", "tenant1")
    assert result is None


def test_get_mcp_custom_headers_by_name_and_url_empty_headers(monkeypatch, mock_session):
    """Test get_mcp_custom_headers_by_name_and_url when custom_headers is None (lines 277-294)"""
    session, query = mock_session
    mock_mcp = MockMcpRecord()
    mock_mcp.custom_headers = None

    mock_first = MagicMock()
    mock_first.return_value = mock_mcp
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    result = get_mcp_custom_headers_by_name_and_url("test_mcp", "http://test.server.com", "tenant1")
    assert result is None


# ============================================================================
# get_mcp_record_by_id_and_tenant
# ============================================================================

def test_get_mcp_record_by_id_and_tenant_success(monkeypatch, mock_session):
    session, query = mock_session
    mock_mcp = MockMcpRecord()
    mock_mcp.mcp_id = 123

    mock_first = MagicMock()
    mock_first.return_value = mock_mcp
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.remote_mcp_db.as_dict", lambda obj: obj.__dict__)

    result = get_mcp_record_by_id_and_tenant(123, "tenant1")
    assert result is not None
    assert result["mcp_id"] == 123


def test_get_mcp_record_by_id_and_tenant_not_found(monkeypatch, mock_session):
    session, query = mock_session

    mock_first = MagicMock()
    mock_first.return_value = None
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    result = get_mcp_record_by_id_and_tenant(999, "tenant1")
    assert result is None


# ============================================================================
# check_mcp_name_exists
# ============================================================================

def test_check_mcp_name_exists_true(monkeypatch, mock_session):
    session, query = mock_session
    mock_mcp = MockMcpRecord()

    mock_first = MagicMock()
    mock_first.return_value = mock_mcp
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    result = check_mcp_name_exists("test_mcp", "tenant1")
    assert result is True


def test_check_mcp_name_exists_false(monkeypatch, mock_session):
    session, query = mock_session

    mock_first = MagicMock()
    mock_first.return_value = None
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    result = check_mcp_name_exists("nonexistent", "tenant1")
    assert result is False


# ============================================================================
# check_enabled_mcp_name_exists (NEW)
# ============================================================================

def test_check_enabled_mcp_name_exists_true(monkeypatch, mock_session):
    session, query = mock_session
    mock_mcp = MockMcpRecord()

    mock_first = MagicMock()
    mock_first.return_value = mock_mcp
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    result = check_enabled_mcp_name_exists("test_mcp", "tenant1")
    assert result is True


def test_check_enabled_mcp_name_exists_false(monkeypatch, mock_session):
    session, query = mock_session

    mock_first = MagicMock()
    mock_first.return_value = None
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    result = check_enabled_mcp_name_exists("nonexistent", "tenant1")
    assert result is False


# ============================================================================
# update_mcp_record_by_name_and_url
# ============================================================================

class MockMCPUpdateRequest:
    def __init__(self, current_service_name, current_mcp_url, new_service_name, new_mcp_url, new_authorization_token=None, custom_headers=None):
        self.current_service_name = current_service_name
        self.current_mcp_url = current_mcp_url
        self.new_service_name = new_service_name
        self.new_mcp_url = new_mcp_url
        self.new_authorization_token = new_authorization_token
        self.custom_headers = custom_headers


def test_update_mcp_record_by_name_and_url_success(monkeypatch, mock_session):
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    update_data = MockMCPUpdateRequest("old", "http://old.url", "new", "http://new.url")
    update_mcp_record_by_name_and_url(update_data=update_data, tenant_id="tenant1", user_id="user1", status=True)

    mock_update.assert_called_once_with({
        "mcp_name": "new", "mcp_server": "http://new.url",
        "updated_by": "user1", "status": True, "authorization_token": None,
        "custom_headers": None,
    })


def test_update_mcp_record_by_name_and_url_without_status(monkeypatch, mock_session):
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    update_data = MockMCPUpdateRequest("old", "http://old.url", "new", "http://new.url")
    update_mcp_record_by_name_and_url(update_data=update_data, tenant_id="tenant1", user_id="user1")

    mock_update.assert_called_once_with({
        "mcp_name": "new", "mcp_server": "http://new.url",
        "updated_by": "user1", "authorization_token": None,
        "custom_headers": None,
    })


def test_update_mcp_record_by_name_and_url_with_token(monkeypatch, mock_session):
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    update_data = MockMCPUpdateRequest("old", "http://old.url", "new", "http://new.url", "new_token_456")
    update_mcp_record_by_name_and_url(update_data=update_data, tenant_id="tenant1", user_id="user1", status=True)

    mock_update.assert_called_once_with({
        "mcp_name": "new", "mcp_server": "http://new.url",
        "updated_by": "user1", "status": True, "authorization_token": "new_token_456",
        "custom_headers": None,
    })


def test_update_mcp_record_by_name_and_url_with_custom_headers(monkeypatch, mock_session):
    """Test custom_headers handling in update_mcp_record_by_name_and_url (lines 324-327)"""
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    custom_headers = {"X-Custom-Auth": "Bearer token123", "X-Api-Key": "apikey"}
    update_data = MockMCPUpdateRequest(
        "old", "http://old.url", "new", "http://new.url",
        custom_headers=custom_headers
    )
    update_mcp_record_by_name_and_url(update_data=update_data, tenant_id="tenant1", user_id="user1", status=True)

    mock_update.assert_called_once()
    call_args = mock_update.call_args[0][0]
    assert call_args["custom_headers"] == custom_headers
    assert call_args["mcp_name"] == "new"


def test_update_mcp_record_by_name_and_url_with_token_and_custom_headers(monkeypatch, mock_session):
    """Test both authorization_token and custom_headers in update_mcp_record_by_name_and_url (lines 320-326)"""
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    custom_headers = {"X-Header": "value"}
    update_data = MockMCPUpdateRequest(
        "old", "http://old.url", "new", "http://new.url",
        new_authorization_token="new_token",
        custom_headers=custom_headers
    )
    update_mcp_record_by_name_and_url(update_data=update_data, tenant_id="tenant1", user_id="user1", status=True)

    mock_update.assert_called_once()
    call_args = mock_update.call_args[0][0]
    assert call_args["authorization_token"] == "new_token"
    assert call_args["custom_headers"] == custom_headers


def test_update_mcp_record_by_name_and_url_with_none_custom_headers(monkeypatch, mock_session):
    """Test update_mcp_record_by_name_and_url when custom_headers attribute exists but is None (line 325)"""
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)

    update_data = MockMCPUpdateRequest("old", "http://old.url", "new", "http://new.url", custom_headers=None)
    update_mcp_record_by_name_and_url(update_data=update_data, tenant_id="tenant1", user_id="user1", status=True)

    mock_update.assert_called_once()
    call_args = mock_update.call_args[0][0]
    assert call_args.get("custom_headers") is None


# ============================================================================
# Integration: MCP record lifecycle
# ============================================================================

def test_mcp_record_lifecycle(monkeypatch, mock_session):
    session, query = mock_session

    session.add = MagicMock()

    mock_mcp = MockMcpRecord()
    mock_first = MagicMock()
    mock_first.return_value = mock_mcp
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    mock_filter.update = MagicMock()
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.remote_mcp_db.filter_property", lambda data, model: data)
    monkeypatch.setattr("backend.database.remote_mcp_db.McpRecord", MagicMock())

    # 1. Create
    mcp_data = {"mcp_name": "test_mcp", "mcp_server": "http://test.server.com", "status": True}
    create_mcp_record(mcp_data, "tenant1", "user1")

    # 2. Check exists
    assert check_mcp_name_exists("test_mcp", "tenant1") is True

    # 3. Get by ID
    monkeypatch.setattr("backend.database.remote_mcp_db.as_dict", lambda obj: obj.__dict__)
    record = get_mcp_record_by_id_and_tenant(1, "tenant1")
    assert record is not None

    # 4. Update enabled
    update_mcp_record_enabled_by_id(mcp_id=1, tenant_id="tenant1", user_id="user1", enabled=True)

    # 5. Delete by ID
    delete_mcp_record_by_id(mcp_id=1, tenant_id="tenant1", user_id="user1")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
