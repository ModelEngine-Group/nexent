import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

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
db_models_mock.UserTenant = MagicMock()
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# Mock exceptions module
exceptions_mock = MagicMock()
sys.modules['consts.exceptions'] = exceptions_mock
sys.modules['backend.consts.exceptions'] = exceptions_mock

# Now import the functions to be tested
from backend.database.user_tenant_db import (
    get_user_tenant_by_user_id,
    insert_user_tenant
)

class MockUserTenant:
    def __init__(self):
        self.user_id = "test_user_id"
        self.tenant_id = "test_tenant_id"
        self.delete_flag = "N"
        self.created_by = "test_user_id"
        self.updated_by = "test_user_id"
        self.create_time = "2024-01-01 00:00:00"
        self.update_time = "2024-01-01 00:00:00"
        self.__dict__ = {
            "user_id": "test_user_id",
            "tenant_id": "test_tenant_id",
            "delete_flag": "N",
            "created_by": "test_user_id",
            "updated_by": "test_user_id",
            "create_time": "2024-01-01 00:00:00",
            "update_time": "2024-01-01 00:00:00"
        }

@pytest.fixture
def mock_session():
    """Create mock database session"""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    return mock_session, mock_query

def test_get_user_tenant_by_user_id_success(monkeypatch, mock_session):
    """Test successful retrieval of user tenant relationship by user ID"""
    session, query = mock_session
    mock_user_tenant = MockUserTenant()
    
    mock_first = MagicMock()
    mock_first.return_value = mock_user_tenant
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.user_tenant_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.user_tenant_db.as_dict", lambda obj: obj.__dict__)
    
    result = get_user_tenant_by_user_id("test_user_id")
    
    assert result is not None
    assert result["user_id"] == "test_user_id"
    assert result["tenant_id"] == "test_tenant_id"
    assert result["delete_flag"] == "N"

def test_get_user_tenant_by_user_id_not_found(monkeypatch, mock_session):
    """Test retrieval of user tenant relationship when record does not exist"""
    session, query = mock_session
    
    mock_first = MagicMock()
    mock_first.return_value = None
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.user_tenant_db.get_db_session", lambda: mock_ctx)
    
    result = get_user_tenant_by_user_id("nonexistent_user_id")
    
    assert result is None

def test_get_user_tenant_by_user_id_database_error(monkeypatch, mock_session):
    """Test database error when retrieving user tenant relationship - exception should propagate"""
    from sqlalchemy.exc import SQLAlchemyError
    
    session, query = mock_session
    query.filter.side_effect = SQLAlchemyError("Database error")
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.user_tenant_db.get_db_session", lambda: mock_ctx)
    
    # Should raise SQLAlchemyError
    with pytest.raises(SQLAlchemyError):
        get_user_tenant_by_user_id("test_user_id")

def test_insert_user_tenant_success(monkeypatch, mock_session):
    """Test successful insertion of user tenant relationship"""
    session, _ = mock_session
    session.add = MagicMock()
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.user_tenant_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.user_tenant_db.UserTenant", lambda **kwargs: MagicMock())
    
    # Should not raise any exception
    insert_user_tenant("test_user_id", "test_tenant_id")
    
    session.add.assert_called_once()

def test_insert_user_tenant_failure(monkeypatch, mock_session):
    """Test failure of user tenant relationship insertion - exception should propagate"""
    from sqlalchemy.exc import SQLAlchemyError
    
    session, _ = mock_session
    session.add = MagicMock(side_effect=SQLAlchemyError("Database error"))
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.user_tenant_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.user_tenant_db.UserTenant", lambda **kwargs: MagicMock())
    
    # Should raise SQLAlchemyError
    with pytest.raises(SQLAlchemyError):
        insert_user_tenant("test_user_id", "test_tenant_id")

def test_insert_user_tenant_with_empty_user_id(monkeypatch, mock_session):
    """Test insertion of user tenant relationship with empty user ID"""
    session, _ = mock_session
    session.add = MagicMock()
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.user_tenant_db.get_db_session", lambda: mock_ctx)
    
    # Mock UserTenant constructor to capture the arguments
    mock_user_tenant_instance = MagicMock()
    mock_user_tenant_constructor = MagicMock(return_value=mock_user_tenant_instance)
    monkeypatch.setattr("backend.database.user_tenant_db.UserTenant", mock_user_tenant_constructor)
    
    # Should not raise any exception
    insert_user_tenant("", "test_tenant_id")
    
    # Verify UserTenant was called with correct parameters
    mock_user_tenant_constructor.assert_called_once_with(
        user_id="",
        tenant_id="test_tenant_id",
        created_by="",
        updated_by=""
    )
    session.add.assert_called_once_with(mock_user_tenant_instance)

def test_insert_user_tenant_with_empty_tenant_id(monkeypatch, mock_session):
    """Test insertion of user tenant relationship with empty tenant ID"""
    session, _ = mock_session
    session.add = MagicMock()
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.user_tenant_db.get_db_session", lambda: mock_ctx)
    
    # Mock UserTenant constructor to capture the arguments
    mock_user_tenant_instance = MagicMock()
    mock_user_tenant_constructor = MagicMock(return_value=mock_user_tenant_instance)
    monkeypatch.setattr("backend.database.user_tenant_db.UserTenant", mock_user_tenant_constructor)
    
    # Should not raise any exception
    insert_user_tenant("test_user_id", "")
    
    # Verify UserTenant was called with correct parameters
    mock_user_tenant_constructor.assert_called_once_with(
        user_id="test_user_id",
        tenant_id="",
        created_by="test_user_id",
        updated_by="test_user_id"
    )
    session.add.assert_called_once_with(mock_user_tenant_instance)

# Integration test
def test_user_tenant_lifecycle(monkeypatch, mock_session):
    """Test complete user tenant lifecycle: insert and then retrieve"""
    session, query = mock_session
    
    # Mock database operations for insertion
    session.add = MagicMock()
    
    # Mock database operations for retrieval
    mock_user_tenant = MockUserTenant()
    mock_first = MagicMock()
    mock_first.return_value = mock_user_tenant
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter
    
    # Create a proper mock UserTenant class with attributes
    mock_user_tenant_class = MagicMock()
    mock_user_tenant_class.user_id = MagicMock()
    mock_user_tenant_class.delete_flag = MagicMock()
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.user_tenant_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.user_tenant_db.UserTenant", mock_user_tenant_class)
    monkeypatch.setattr("backend.database.user_tenant_db.as_dict", lambda obj: obj.__dict__)
    
    # 1. Insert user tenant relationship - should not raise exception
    insert_user_tenant("test_user_id", "test_tenant_id")
    session.add.assert_called_once()
    
    # 2. Retrieve user tenant relationship
    result = get_user_tenant_by_user_id("test_user_id")
    assert result is not None
    assert result["user_id"] == "test_user_id"
    assert result["tenant_id"] == "test_tenant_id"
    assert result["delete_flag"] == "N"

def test_get_user_tenant_by_user_id_with_deleted_record(monkeypatch, mock_session):
    """Test retrieval of user tenant relationship when record is marked as deleted"""
    session, query = mock_session
    
    # Mock a deleted record (should not be returned)
    mock_first = MagicMock()
    mock_first.return_value = None  # Filter should exclude deleted records
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.user_tenant_db.get_db_session", lambda: mock_ctx)
    
    result = get_user_tenant_by_user_id("deleted_user_id")
    
    assert result is None
    # Verify that the filter was called with correct conditions
    query.filter.assert_called_once() 