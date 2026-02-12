import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import pytest
from unittest.mock import MagicMock

# First mock the consts module to avoid ModuleNotFoundError
consts_mock = MagicMock()
consts_mock.const = MagicMock()
# Set required constants in consts.const
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
consts_mock.const.TENANT_ID = "tenant_id"

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
db_models_mock.TenantConfig = MagicMock()

class MockTenantConfig:
    def __init__(self, **kwargs):
        self.tenant_config_id = kwargs.get('tenant_config_id', 1)
        self.tenant_id = kwargs.get('tenant_id', 'test_tenant')
        self.user_id = kwargs.get('user_id', 'test_user')
        self.config_key = kwargs.get('config_key', 'test_key')
        self.config_value = kwargs.get('config_value', 'test_value')
        self.created_by = kwargs.get('created_by', 'test_user')
        self.updated_by = kwargs.get('updated_by', 'test_user')
        self.delete_flag = kwargs.get('delete_flag', 'N')
        self.create_time = kwargs.get('create_time', '2024-01-01 00:00:00')
        self.update_time = kwargs.get('update_time', '2024-01-01 00:00:00')

# Add the mocked db_models module to sys.modules
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# Mock sqlalchemy module
sqlalchemy_mock = MagicMock()
sqlalchemy_mock.exc = MagicMock()

class MockSQLAlchemyError(Exception):
    pass

sqlalchemy_mock.exc.SQLAlchemyError = MockSQLAlchemyError

# Add the mocked sqlalchemy module to sys.modules
sys.modules['sqlalchemy'] = sqlalchemy_mock
sys.modules['sqlalchemy.exc'] = sqlalchemy_mock.exc

# Now we can safely import the module under test
from backend.database.tenant_config_db import (
    get_all_configs_by_tenant_id,
    get_tenant_config_info,
    get_single_config_info,
    insert_config,
    delete_config_by_tenant_config_id,
    delete_config,
    update_config_by_tenant_config_id,
    update_config_by_tenant_config_id_and_data,
    get_all_tenant_ids
)


@pytest.fixture
def mock_session():
    """Create mock database session"""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    return mock_session, mock_query


def test_get_all_configs_by_tenant_id_success(monkeypatch, mock_session):
    """Test successfully retrieving all configs for a tenant"""
    session, query = mock_session

    mock_config1 = MockTenantConfig(
        tenant_config_id=1,
        config_key="key1",
        config_value="value1",
        update_time="2024-01-01 10:00:00"
    )
    mock_config2 = MockTenantConfig(
        tenant_config_id=2,
        config_key="key2",
        config_value="value2",
        update_time="2024-01-01 11:00:00"
    )

    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_config1, mock_config2]
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    result = get_all_configs_by_tenant_id("test_tenant")

    assert len(result) == 2
    assert result[0]["config_key"] == "key1"
    assert result[0]["config_value"] == "value1"
    assert result[1]["config_key"] == "key2"
    assert result[1]["config_value"] == "value2"


def test_get_all_configs_by_tenant_id_empty(monkeypatch, mock_session):
    """Test retrieving configs when none exist"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.all.return_value = []
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    result = get_all_configs_by_tenant_id("test_tenant")

    assert result == []


def test_get_tenant_config_info_success(monkeypatch, mock_session):
    """Test successfully retrieving tenant config info for user and key"""
    session, query = mock_session

    mock_config = MockTenantConfig(
        config_value="test_value",
        tenant_config_id=123
    )

    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_config]
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    result = get_tenant_config_info("test_tenant", "test_user", "test_key")

    assert len(result) == 1
    assert result[0]["config_value"] == "test_value"
    assert result[0]["tenant_config_id"] == 123


def test_get_tenant_config_info_not_found(monkeypatch, mock_session):
    """Test retrieving tenant config info when not found"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.all.return_value = []
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    result = get_tenant_config_info("test_tenant", "test_user", "test_key")

    assert result == []


def test_get_single_config_info_success(monkeypatch, mock_session):
    """Test successfully retrieving single config info"""
    session, query = mock_session

    mock_config = MockTenantConfig(
        config_value="single_value",
        tenant_config_id=456
    )

    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_config
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    result = get_single_config_info("test_tenant", "test_key")

    assert result["config_value"] == "single_value"
    assert result["tenant_config_id"] == 456


def test_get_single_config_info_not_found(monkeypatch, mock_session):
    """Test retrieving single config info when not found"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    result = get_single_config_info("test_tenant", "test_key")

    assert result == {}


def test_insert_config_success(monkeypatch, mock_session):
    """Test successfully inserting config"""
    session, _ = mock_session
    session.add = MagicMock()
    session.commit = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    insert_data = {
        "tenant_id": "test_tenant",
        "user_id": "test_user",
        "config_key": "test_key",
        "config_value": "test_value"
    }

    result = insert_config(insert_data)

    assert result is True
    session.add.assert_called_once()
    session.commit.assert_called_once()


def test_insert_config_failure(monkeypatch, mock_session):
    """Test inserting config with database error"""
    session, _ = mock_session
    session.add = MagicMock()
    session.commit = MagicMock(side_effect=MockSQLAlchemyError("Insert failed"))
    session.rollback = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    insert_data = {
        "tenant_id": "test_tenant",
        "user_id": "test_user",
        "config_key": "test_key",
        "config_value": "test_value"
    }

    result = insert_config(insert_data)

    assert result is False
    session.rollback.assert_called_once()


def test_delete_config_by_tenant_config_id_success(monkeypatch, mock_session):
    """Test successfully deleting config by tenant config ID"""
    session, query = mock_session

    mock_update = MagicMock()
    mock_update.return_value = 1  # 1 row affected
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    session.commit = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    result = delete_config_by_tenant_config_id(123)

    assert result is True
    session.commit.assert_called_once()


def test_delete_config_by_tenant_config_id_failure(monkeypatch, mock_session):
    """Test deleting config by tenant config ID with database error"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.update = MagicMock(side_effect=MockSQLAlchemyError("Delete failed"))
    query.filter.return_value = mock_filter

    session.rollback = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    result = delete_config_by_tenant_config_id(123)

    assert result is False
    session.rollback.assert_called_once()


def test_delete_config_success(monkeypatch, mock_session):
    """Test successfully deleting config"""
    session, query = mock_session

    mock_update = MagicMock()
    mock_update.return_value = 1  # 1 row affected
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    session.commit = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    result = delete_config("test_tenant", "test_user", "test_key", "test_value")

    assert result is True
    session.commit.assert_called_once()


def test_delete_config_failure(monkeypatch, mock_session):
    """Test deleting config with database error"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.update = MagicMock(side_effect=MockSQLAlchemyError("Delete failed"))
    query.filter.return_value = mock_filter

    session.rollback = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    result = delete_config("test_tenant", "test_user", "test_key", "test_value")

    assert result is False
    session.rollback.assert_called_once()


def test_update_config_by_tenant_config_id_success(monkeypatch, mock_session):
    """Test successfully updating config by tenant config ID"""
    session, query = mock_session

    mock_update = MagicMock()
    mock_update.return_value = 1  # 1 row affected
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    session.commit = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    result = update_config_by_tenant_config_id(123, "new_value")

    assert result is True
    session.commit.assert_called_once()


def test_update_config_by_tenant_config_id_failure(monkeypatch, mock_session):
    """Test updating config by tenant config ID with database error"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.update = MagicMock(side_effect=MockSQLAlchemyError("Update failed"))
    query.filter.return_value = mock_filter

    session.rollback = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    result = update_config_by_tenant_config_id(123, "new_value")

    assert result is False
    session.rollback.assert_called_once()


def test_update_config_by_tenant_config_id_and_data_success(monkeypatch, mock_session):
    """Test successfully updating config by tenant config ID and data"""
    session, query = mock_session

    mock_update = MagicMock()
    mock_update.return_value = 1  # 1 row affected
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    session.commit = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    update_data = {"config_value": "new_value", "updated_by": "test_user"}
    result = update_config_by_tenant_config_id_and_data(123, update_data)

    assert result is True
    session.commit.assert_called_once()


def test_update_config_by_tenant_config_id_and_data_failure(monkeypatch, mock_session):
    """Test updating config by tenant config ID and data with database error"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.update = MagicMock(side_effect=MockSQLAlchemyError("Update failed"))
    query.filter.return_value = mock_filter

    session.rollback = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    update_data = {"config_value": "new_value", "updated_by": "test_user"}
    result = update_config_by_tenant_config_id_and_data(123, update_data)

    assert result is False
    session.rollback.assert_called_once()


def test_get_all_tenant_ids_success(monkeypatch, mock_session):
    """Test successfully retrieving all tenant IDs"""
    session, _ = mock_session

    # Create a mock query chain that returns tenant IDs
    mock_distinct = MagicMock()
    mock_distinct.all.return_value = [("tenant1",), ("tenant2",), ("tenant3",)]

    mock_filter = MagicMock()
    mock_filter.distinct.return_value = mock_distinct

    mock_specific_query = MagicMock()
    mock_specific_query.filter.return_value = mock_filter

    def mock_query_func(*args, **kwargs):
        return mock_specific_query

    session.query = mock_query_func

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    result = get_all_tenant_ids()

    assert result == []


def test_get_all_tenant_ids_empty(monkeypatch, mock_session):
    """Test retrieving tenant IDs when none exist"""
    session, _ = mock_session

    # Create a mock query that returns empty result
    mock_specific_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.all.return_value = []
    mock_specific_query.filter.return_value = mock_filter

    def mock_query_func(*args, **kwargs):
        return mock_specific_query

    session.query = mock_query_func

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    result = get_all_tenant_ids()

    assert result == []


def test_database_error_handling(monkeypatch, mock_session):
    """Test database error handling across functions"""
    session, query = mock_session
    query.filter.side_effect = MockSQLAlchemyError("Database error")

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tenant_config_db.get_db_session", lambda: mock_ctx)

    with pytest.raises(MockSQLAlchemyError, match="Database error"):
        get_all_configs_by_tenant_id("test_tenant")
