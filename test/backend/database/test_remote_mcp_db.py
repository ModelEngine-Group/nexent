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

# Mock utils module
utils_mock = MagicMock()
utils_mock.auth_utils = MagicMock()
utils_mock.auth_utils.get_current_user_id_from_token = MagicMock(return_value="test_user_id")

# Add the mocked utils module to sys.modules
sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_mock.auth_utils

# Provide a stub for the `boto3` module so that it can be imported safely even
# if the testing environment does not have it available.
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Mock the entire client module
client_mock = MagicMock()
client_mock.MinioClient = MagicMock()
client_mock.PostgresClient = MagicMock()
client_mock.db_client = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock()
client_mock.filter_property = MagicMock()

# Add the mocked client module to sys.modules
sys.modules['database.client'] = client_mock
sys.modules['backend.database.client'] = client_mock

# Mock db_models module
db_models_mock = MagicMock()
db_models_mock.McpRecord = MagicMock()
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# Mock exceptions module
exceptions_mock = MagicMock()
sys.modules['consts.exceptions'] = exceptions_mock
sys.modules['backend.consts.exceptions'] = exceptions_mock

# Now import the functions to be tested
from backend.database.remote_mcp_db import (
    create_mcp_record,
    delete_mcp_record_by_name_and_url,
    update_mcp_status_by_name_and_url,
    get_mcp_records_by_tenant,
    get_mcp_server_by_name_and_tenant,
    check_mcp_name_exists
)

class MockMcpRecord:
    def __init__(self):
        self.mcp_name = "test_mcp"
        self.mcp_server = "http://test.server.com"
        self.tenant_id = "tenant1"
        self.user_id = "user1"
        self.status = True
        self.delete_flag = "N"
        self.create_time = "2024-01-01 00:00:00"
        self.__dict__ = {
            "mcp_name": "test_mcp",
            "mcp_server": "http://test.server.com",
            "tenant_id": "tenant1",
            "user_id": "user1",
            "status": True,
            "delete_flag": "N",
            "create_time": "2024-01-01 00:00:00"
        }

@pytest.fixture
def mock_session():
    """Create mock database session"""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    return mock_session, mock_query

def test_create_mcp_record_success(monkeypatch, mock_session):
    """Test successful creation of MCP record"""
    session, _ = mock_session
    session.add = MagicMock()
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.remote_mcp_db.filter_property", lambda data, model: data)
    monkeypatch.setattr("backend.database.remote_mcp_db.McpRecord", lambda **kwargs: MagicMock())
    
    mcp_data = {
        "mcp_name": "test_mcp",
        "mcp_server": "http://test.server.com",
        "status": True
    }
    
    # Should not raise any exception
    create_mcp_record(mcp_data, "tenant1", "user1")
    
    session.add.assert_called_once()

def test_create_mcp_record_failure(monkeypatch, mock_session):
    """Test failure of MCP record creation - exception should propagate"""
    from sqlalchemy.exc import SQLAlchemyError
    
    session, _ = mock_session
    session.add = MagicMock(side_effect=SQLAlchemyError("Database error"))
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.remote_mcp_db.filter_property", lambda data, model: data)
    monkeypatch.setattr("backend.database.remote_mcp_db.McpRecord", lambda **kwargs: MagicMock())
    
    mcp_data = {
        "mcp_name": "test_mcp",
        "mcp_server": "http://test.server.com",
        "status": True
    }
    
    # Should raise SQLAlchemyError
    with pytest.raises(SQLAlchemyError):
        create_mcp_record(mcp_data, "tenant1", "user1")

def test_delete_mcp_record_by_name_and_url_success(monkeypatch, mock_session):
    """Test successful deletion of MCP record"""
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    
    # Should not raise any exception
    delete_mcp_record_by_name_and_url("test_mcp", "http://test.server.com", "tenant1", "user1")
    
    mock_update.assert_called_once_with({"delete_flag": "Y", "updated_by": "user1"})

def test_delete_mcp_record_by_name_and_url_failure(monkeypatch, mock_session):
    """Test failure of MCP record deletion - exception should propagate"""
    from sqlalchemy.exc import SQLAlchemyError
    
    session, query = mock_session
    query.filter.side_effect = SQLAlchemyError("Database error")
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    
    # Should raise SQLAlchemyError
    with pytest.raises(SQLAlchemyError):
        delete_mcp_record_by_name_and_url("test_mcp", "http://test.server.com", "tenant1", "user1")

def test_update_mcp_status_by_name_and_url_success(monkeypatch, mock_session):
    """Test successful update of MCP status"""
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    
    # Should not raise any exception
    update_mcp_status_by_name_and_url("test_mcp", "http://test.server.com", "tenant1", "user1", False)
    
    mock_update.assert_called_once_with({"status": False, "updated_by": "user1"})

def test_update_mcp_status_by_name_and_url_failure(monkeypatch, mock_session):
    """Test failure of MCP status update - exception should propagate"""
    from sqlalchemy.exc import SQLAlchemyError
    
    session, query = mock_session
    query.filter.side_effect = SQLAlchemyError("Database error")
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    
    # Should raise SQLAlchemyError
    with pytest.raises(SQLAlchemyError):
        update_mcp_status_by_name_and_url("test_mcp", "http://test.server.com", "tenant1", "user1", True)

def test_get_mcp_records_by_tenant_success(monkeypatch, mock_session):
    """Test successful retrieval of MCP records list by tenant"""
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
    assert result[1]["mcp_name"] == "test_mcp2"

def test_get_mcp_server_by_name_and_tenant_success(monkeypatch, mock_session):
    """Test successful retrieval of MCP server address by name and tenant"""
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
    """Test retrieval of MCP server address by name and tenant when record does not exist"""
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
    
    result = get_mcp_server_by_name_and_tenant("nonexistent_mcp", "tenant1")
    
    assert result == ""

def test_get_mcp_server_by_name_and_tenant_database_error(monkeypatch, mock_session):
    """Test database error when retrieving MCP server address - exception should propagate"""
    from sqlalchemy.exc import SQLAlchemyError
    
    session, query = mock_session
    query.filter.side_effect = SQLAlchemyError("Database error")
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    
    # Should raise SQLAlchemyError, not MCPDatabaseError
    with pytest.raises(SQLAlchemyError):
        get_mcp_server_by_name_and_tenant("test_mcp", "tenant1")

def test_check_mcp_name_exists_true(monkeypatch, mock_session):
    """Test checking MCP name exists, returns True"""
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
    """Test checking MCP name exists, returns False"""
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
    
    result = check_mcp_name_exists("nonexistent_mcp", "tenant1")
    
    assert result is False

def test_check_mcp_name_exists_database_error(monkeypatch, mock_session):
    """Test database error when checking if MCP name exists - exception should propagate"""
    from sqlalchemy.exc import SQLAlchemyError
    
    session, query = mock_session
    query.filter.side_effect = SQLAlchemyError("Database error")
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    
    # Should raise SQLAlchemyError, not MCPDatabaseError
    with pytest.raises(SQLAlchemyError):
        check_mcp_name_exists("test_mcp", "tenant1")

# Integration test
def test_mcp_record_lifecycle(monkeypatch, mock_session):
    """Test complete MCP record lifecycle: create, query, update status, delete"""
    session, query = mock_session
    
    # Mock database operations
    session.add = MagicMock()
    
    mock_mcp = MockMcpRecord()
    mock_first = MagicMock()
    mock_first.return_value = mock_mcp
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    mock_filter.update = MagicMock()
    query.filter.return_value = mock_filter
    
    # Create a Mock class to simulate McpRecord
    mock_mcp_record_class = MagicMock()
    mock_mcp_record_class.mcp_name = MagicMock()
    mock_mcp_record_class.tenant_id = MagicMock()
    mock_mcp_record_class.delete_flag = MagicMock()
    mock_mcp_record_class.mcp_server = MagicMock()
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.remote_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.remote_mcp_db.filter_property", lambda data, model: data)
    monkeypatch.setattr("backend.database.remote_mcp_db.McpRecord", mock_mcp_record_class)
    
    # 1. Create MCP record - should not raise exception
    mcp_data = {
        "mcp_name": "test_mcp",
        "mcp_server": "http://test.server.com",
        "status": True
    }
    create_mcp_record(mcp_data, "tenant1", "user1")
    
    # 2. Check if MCP name exists
    exists_result = check_mcp_name_exists("test_mcp", "tenant1")
    assert exists_result is True
    
    # 3. Get MCP server address
    server_result = get_mcp_server_by_name_and_tenant("test_mcp", "tenant1")
    assert server_result == "http://test.server.com"
    
    # 4. Update MCP status - should not raise exception
    update_mcp_status_by_name_and_url("test_mcp", "http://test.server.com", "tenant1", "user1", False)
    
    # 5. Delete MCP record - should not raise exception
    delete_mcp_record_by_name_and_url("test_mcp", "http://test.server.com", "tenant1", "user1") 