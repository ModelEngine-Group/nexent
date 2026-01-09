import sys
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
db_models_mock.RolePermission = MagicMock()

class MockRolePermission:
    def __init__(self, **kwargs):
        self.role_permission_id = kwargs.get('role_permission_id', 1)
        self.user_role = kwargs.get('user_role', 'USER')
        self.permission_category = kwargs.get('permission_category', 'SYSTEM')
        self.permission_type = kwargs.get('permission_type', 'READ')
        self.permission_subtype = kwargs.get('permission_subtype', 'BASIC')
        self.created_by = kwargs.get('created_by', 'test_user')
        self.updated_by = kwargs.get('updated_by', 'test_user')
        self.delete_flag = kwargs.get('delete_flag', 'N')
        self.create_time = kwargs.get('create_time', '2024-01-01 00:00:00')
        self.update_time = kwargs.get('update_time', '2024-01-01 00:00:00')


# Add the mocked db_models module to sys.modules
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# Mock exceptions module
exceptions_mock = MagicMock()
sys.modules['consts.exceptions'] = exceptions_mock
sys.modules['backend.consts.exceptions'] = exceptions_mock

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
from backend.database.role_permission_db import (
    get_role_permissions,
    get_all_role_permissions,
    create_role_permission,
    update_role_permission,
    soft_delete_role_permission,
    delete_role_permissions_by_role,
    check_role_permission,
    get_permissions_by_category,
    initialize_default_permissions
)


@pytest.fixture
def mock_session():
    """Create mock database session"""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    return mock_session, mock_query


def test_get_role_permissions_success(monkeypatch, mock_session):
    """Test successfully retrieving role permissions"""
    session, query = mock_session

    mock_permission1 = MockRolePermission(
        role_permission_id=1,
        user_role="USER",
        permission_category="KNOWLEDGE_BASE",
        permission_type="KNOWLEDGE",
        permission_subtype="READ"
    )
    mock_permission2 = MockRolePermission(
        role_permission_id=2,
        user_role="USER",
        permission_category="AGENT_MANAGEMENT",
        permission_type="AGENT",
        permission_subtype="READ"
    )

    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_permission1, mock_permission2]
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.role_permission_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.role_permission_db.as_dict", lambda obj: obj.__dict__)

    result = get_role_permissions("USER")

    assert len(result) == 2
    assert result[0]["user_role"] == "USER"
    assert result[0]["permission_category"] == "KNOWLEDGE_BASE"
    assert result[1]["permission_category"] == "AGENT_MANAGEMENT"


def test_get_all_role_permissions_success(monkeypatch, mock_session):
    """Test retrieving all role permissions"""
    session, query = mock_session

    mock_permission1 = MockRolePermission(user_role="USER")
    mock_permission2 = MockRolePermission(user_role="ADMIN")

    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_permission1, mock_permission2]
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.role_permission_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.role_permission_db.as_dict", lambda obj: obj.__dict__)

    result = get_all_role_permissions()

    assert len(result) == 2
    assert result[0]["user_role"] == "USER"
    assert result[1]["user_role"] == "ADMIN"


def test_create_role_permission_success(monkeypatch, mock_session):
    """Test successfully creating role permission"""
    session, _ = mock_session
    session.add = MagicMock()

    mock_permission = MockRolePermission()
    mock_permission.role_permission_id = 123

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.role_permission_db.get_db_session", lambda: mock_ctx)

    from unittest.mock import patch
    with patch('backend.database.role_permission_db.RolePermission', return_value=mock_permission):
        result = create_role_permission(
            user_role="USER",
            permission_category="KNOWLEDGE_BASE",
            permission_type="KNOWLEDGE",
            permission_subtype="READ",
            created_by="test_user"
        )

    assert result == 123
    session.add.assert_called_once_with(mock_permission)
    session.flush.assert_called_once()


def test_update_role_permission_success(monkeypatch, mock_session):
    """Test successfully updating role permission"""
    session, query = mock_session

    # Setup query filter().update() chain
    mock_update = MagicMock()
    mock_update.return_value = 1  # 1 row affected
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.role_permission_db.get_db_session", lambda: mock_ctx)

    result = update_role_permission(
        role_permission_id=123,
        updates={"permission_category": "new_category"},
        updated_by="test_user"
    )

    assert result is True


def test_soft_delete_role_permission_success(monkeypatch, mock_session):
    """Test successfully soft deleting role permission"""
    session, query = mock_session

    # Setup query filter().update() chain
    mock_update = MagicMock()
    mock_update.return_value = 1  # 1 row affected
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.role_permission_db.get_db_session", lambda: mock_ctx)

    result = soft_delete_role_permission(role_permission_id=123, updated_by="test_user")

    assert result is True


def test_delete_role_permissions_by_role_success(monkeypatch, mock_session):
    """Test successfully deleting all permissions for a role"""
    session, query = mock_session

    # Setup query filter().update() chain
    mock_update = MagicMock()
    mock_update.return_value = 3  # 3 rows affected
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.role_permission_db.get_db_session", lambda: mock_ctx)

    result = delete_role_permissions_by_role("USER", updated_by="test_user")

    assert result == 3


def test_check_role_permission_true(monkeypatch, mock_session):
    """Test checking role permission - permission exists"""
    session, query = mock_session

    mock_permission = MockRolePermission()

    # Mock chain: query.filter().filter().filter().filter().first()
    mock_filter_final = MagicMock()
    mock_filter_final.first.return_value = mock_permission

    mock_filter3 = MagicMock()
    mock_filter3.filter.return_value = mock_filter_final

    mock_filter2 = MagicMock()
    mock_filter2.filter.return_value = mock_filter3

    mock_filter1 = MagicMock()
    mock_filter1.filter.return_value = mock_filter2

    query.filter.return_value = mock_filter1

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.role_permission_db.get_db_session", lambda: mock_ctx)

    result = check_role_permission(
        user_role="USER",
        permission_category="KNOWLEDGE_BASE",
        permission_type="KNOWLEDGE",
        permission_subtype="READ"
    )

    assert result is True


def test_check_role_permission_false(monkeypatch, mock_session):
    """Test checking role permission - permission does not exist"""
    session, query = mock_session

    # Mock chain: query.filter().filter().filter().filter().first()
    mock_filter_final = MagicMock()
    mock_filter_final.first.return_value = None

    mock_filter3 = MagicMock()
    mock_filter3.filter.return_value = mock_filter_final

    mock_filter2 = MagicMock()
    mock_filter2.filter.return_value = mock_filter3

    mock_filter1 = MagicMock()
    mock_filter1.filter.return_value = mock_filter2

    query.filter.return_value = mock_filter1

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.role_permission_db.get_db_session", lambda: mock_ctx)

    result = check_role_permission(
        user_role="USER",
        permission_category="NONEXISTENT",
        permission_type="NONEXISTENT",
        permission_subtype="NONEXISTENT"
    )

    assert result is False


def test_get_permissions_by_category_success(monkeypatch, mock_session):
    """Test retrieving permissions by category"""
    session, query = mock_session

    mock_permission1 = MockRolePermission(
        role_permission_id=1,
        user_role="USER",
        permission_category="KNOWLEDGE_BASE"
    )
    mock_permission2 = MockRolePermission(
        role_permission_id=2,
        user_role="ADMIN",
        permission_category="KNOWLEDGE_BASE"
    )

    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_permission1, mock_permission2]
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.role_permission_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.role_permission_db.as_dict", lambda obj: obj.__dict__)

    result = get_permissions_by_category("KNOWLEDGE_BASE")

    assert len(result) == 2
    assert all(perm["permission_category"] == "KNOWLEDGE_BASE" for perm in result)


def test_initialize_default_permissions_success(monkeypatch, mock_session):
    """Test initializing default permissions"""
    session, query = mock_session

    # Mock that permissions don't exist yet
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.role_permission_db.get_db_session", lambda: mock_ctx)

    # Mock create_role_permission to avoid actual creation
    def mock_create(*args, **kwargs):
        return 1

    monkeypatch.setattr("backend.database.role_permission_db.create_role_permission", mock_create)

    # Should not raise any exception
    initialize_default_permissions()

    # Verify create_role_permission was called multiple times for default permissions
    # (We can't easily count calls with this mock setup, but we can ensure no exception)


def test_database_error_handling(monkeypatch, mock_session):
    """Test database error handling"""
    session, query = mock_session
    query.filter.side_effect = MockSQLAlchemyError("Database error")

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.role_permission_db.get_db_session", lambda: mock_ctx)

    with pytest.raises(MockSQLAlchemyError, match="Database error"):
        get_role_permissions("USER")


def test_create_role_permission_with_none_fields(monkeypatch, mock_session):
    """Test creating role permission with None fields"""
    session, _ = mock_session
    session.add = MagicMock()

    mock_permission = MockRolePermission()
    mock_permission.role_permission_id = 123

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.role_permission_db.get_db_session", lambda: mock_ctx)

    from unittest.mock import patch
    with patch('backend.database.role_permission_db.RolePermission', return_value=mock_permission):
        result = create_role_permission(
            user_role="USER",
            permission_category=None,
            permission_type=None,
            permission_subtype=None,
            created_by="test_user"
        )

    assert result == 123
    session.add.assert_called_once_with(mock_permission)


def test_check_role_permission_partial_match(monkeypatch, mock_session):
    """Test checking role permission with partial criteria"""
    session, query = mock_session

    mock_permission = MockRolePermission()

    # Mock filter chain for partial matching
    mock_filter1 = MagicMock()
    mock_filter2 = MagicMock()
    mock_filter3 = MagicMock()
    mock_filter3.first.return_value = mock_permission

    query.filter.return_value = mock_filter1
    mock_filter1.filter.return_value = mock_filter2
    mock_filter2.filter.return_value = mock_filter3

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.role_permission_db.get_db_session", lambda: mock_ctx)

    result = check_role_permission(
        user_role="USER",
        permission_category="KNOWLEDGE_BASE"
        # Only checking category, not type or subtype
    )

    assert result is True
