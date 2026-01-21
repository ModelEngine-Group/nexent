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
utils_mock.str_utils = MagicMock()
utils_mock.str_utils.convert_list_to_string = MagicMock(side_effect=lambda x: ",".join(str(i) for i in x) if x else "")

# Add the mocked utils module to sys.modules
sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_mock.auth_utils
sys.modules['utils.str_utils'] = utils_mock.str_utils

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
db_models_mock.TenantInvitationCode = MagicMock()
db_models_mock.TenantInvitationRecord = MagicMock()

class MockTenantInvitationCode:
    def __init__(self, **kwargs):
        self.invitation_id = kwargs.get('invitation_id', 1)
        self.tenant_id = kwargs.get('tenant_id', 'test_tenant')
        self.invitation_code = kwargs.get('invitation_code', 'test_code')
        self.group_ids = kwargs.get('group_ids', '1,2,3')
        self.capacity = kwargs.get('capacity', 5)
        self.expiry_date = kwargs.get('expiry_date', '2024-12-31 23:59:59')
        self.status = kwargs.get('status', 'IN_USE')
        self.code_type = kwargs.get('code_type', 'ADMIN_INVITE')
        self.created_by = kwargs.get('created_by', 'test_user')
        self.updated_by = kwargs.get('updated_by', 'test_user')
        self.delete_flag = kwargs.get('delete_flag', 'N')
        self.create_time = kwargs.get('create_time', '2024-01-01 00:00:00')
        self.update_time = kwargs.get('update_time', '2024-01-01 00:00:00')

class MockTenantInvitationRecord:
    def __init__(self, **kwargs):
        self.invitation_record_id = kwargs.get('invitation_record_id', 1)
        self.invitation_id = kwargs.get('invitation_id', 1)
        self.user_id = kwargs.get('user_id', 'test_user')
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
from backend.database.invitation_db import (
    query_invitation_by_code,
    query_invitation_by_id,
    query_invitations_by_tenant,
    add_invitation,
    modify_invitation,
    remove_invitation,
    query_invitation_records,
    add_invitation_record,
    count_invitation_usage,
    query_invitation_status,
    query_invitations_with_pagination
)


@pytest.fixture
def mock_session():
    """Create mock database session"""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    return mock_session, mock_query


def test_query_invitation_by_code_success(monkeypatch, mock_session):
    """Test successfully retrieving invitation code by code"""
    session, query = mock_session

    mock_invitation = MockTenantInvitationCode()
    mock_invitation.invitation_id = 123
    mock_invitation.invitation_code = "test_code"

    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_invitation
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.invitation_db.as_dict", lambda obj: obj.__dict__)

    result = query_invitation_by_code("test_code")

    assert result is not None
    assert result["invitation_code"] == "test_code"
    assert result["invitation_id"] == 123


def test_query_invitation_by_code_not_found(monkeypatch, mock_session):
    """Test retrieving non-existent invitation code"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)

    result = query_invitation_by_code("nonexistent_code")

    assert result is None


def test_query_invitation_by_id_success(monkeypatch, mock_session):
    """Test retrieving invitation code by ID"""
    session, query = mock_session

    mock_invitation = MockTenantInvitationCode()
    mock_invitation.invitation_id = 123
    mock_invitation.invitation_code = "test_code"

    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_invitation
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr(
        "backend.database.invitation_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(
        "backend.database.invitation_db.as_dict", lambda obj: obj.__dict__)

    result = query_invitation_by_id(123)

    assert result is not None
    assert result["invitation_code"] == "test_code"
    assert result["invitation_id"] == 123


def test_query_invitation_by_id_not_found(monkeypatch, mock_session):
    """Test retrieving non-existent invitation code by ID"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr(
        "backend.database.invitation_db.get_db_session", lambda: mock_ctx)

    result = query_invitation_by_id(999)

    assert result is None


def test_query_invitations_by_tenant_success(monkeypatch, mock_session):
    """Test retrieving invitation codes by tenant"""
    session, query = mock_session

    mock_invitation1 = MockTenantInvitationCode(invitation_id=1, invitation_code="code1")
    mock_invitation2 = MockTenantInvitationCode(invitation_id=2, invitation_code="code2")

    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_invitation1, mock_invitation2]
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.invitation_db.as_dict", lambda obj: obj.__dict__)

    result = query_invitations_by_tenant("test_tenant")

    assert len(result) == 2
    assert result[0]["invitation_code"] == "code1"
    assert result[1]["invitation_code"] == "code2"


def test_add_invitation_success(monkeypatch, mock_session):
    """Test successfully creating invitation code"""
    session, _ = mock_session
    session.add = MagicMock()

    mock_invitation = MockTenantInvitationCode()
    mock_invitation.invitation_id = 123

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)

    from unittest.mock import patch
    with patch('backend.database.invitation_db.TenantInvitationCode', return_value=mock_invitation):
        result = add_invitation(
            tenant_id="test_tenant",
            invitation_code="test_code",
            code_type="ADMIN_INVITE",
            group_ids=[1, 2, 3],
            capacity=5,
            expiry_date="2024-12-31",
            status="IN_USE",
            created_by="test_user"
        )

    assert result == 123
    session.add.assert_called_once_with(mock_invitation)
    session.flush.assert_called_once()


def test_add_invitation_with_group_ids_list(monkeypatch, mock_session):
    """Test successfully creating invitation code with group IDs as list"""
    session, _ = mock_session
    session.add = MagicMock()

    mock_invitation = MockTenantInvitationCode()
    mock_invitation.invitation_id = 123

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)

    from unittest.mock import patch
    with patch('backend.database.invitation_db.TenantInvitationCode', return_value=mock_invitation) as mock_constructor:
        result = add_invitation(
            tenant_id="test_tenant",
            invitation_code="test_code",
            code_type="ADMIN_INVITE",
            group_ids=[1, 2, 3],
            capacity=5,
            expiry_date="2024-12-31",
            status="IN_USE",
            created_by="test_user"
        )

    assert result == 123
    # Verify TenantInvitationCode was called with group_ids converted to string
    mock_constructor.assert_called_once_with(
        tenant_id="test_tenant",
        invitation_code="test_code",
        code_type="ADMIN_INVITE",
        group_ids="1,2,3",  # Should be converted to comma-separated string
        capacity=5,
        expiry_date="2024-12-31",
        status="IN_USE",
        created_by="test_user",
        updated_by="test_user"
    )
    session.add.assert_called_once_with(mock_invitation)
    session.flush.assert_called_once()


def test_modify_invitation_success(monkeypatch, mock_session):
    """Test successfully updating invitation code"""
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
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)

    result = modify_invitation(
        invitation_id=123,
        updates={"status": "DISABLE", "capacity": 10},
        updated_by="test_user"
    )

    assert result is True


def test_remove_invitation_success(monkeypatch, mock_session):
    """Test successfully soft deleting invitation code"""
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
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)

    result = remove_invitation(invitation_id=123, updated_by="test_user")

    assert result is True


def test_query_invitation_records_success(monkeypatch, mock_session):
    """Test retrieving invitation records by invitation ID"""
    session, query = mock_session

    mock_record1 = MockTenantInvitationRecord(invitation_record_id=1, user_id="user1")
    mock_record2 = MockTenantInvitationRecord(invitation_record_id=2, user_id="user2")

    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_record1, mock_record2]
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.invitation_db.as_dict", lambda obj: obj.__dict__)

    result = query_invitation_records(123)

    assert len(result) == 2
    assert result[0]["user_id"] == "user1"
    assert result[1]["user_id"] == "user2"


def test_add_invitation_record_success(monkeypatch, mock_session):
    """Test successfully creating invitation record"""
    session, _ = mock_session
    session.add = MagicMock()

    mock_record = MockTenantInvitationRecord()
    mock_record.invitation_record_id = 456

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)

    from unittest.mock import patch
    with patch('backend.database.invitation_db.TenantInvitationRecord', return_value=mock_record):
        result = add_invitation_record(
            invitation_id=123,
            user_id="test_user",
            created_by="test_user"
        )

    assert result == 456
    session.add.assert_called_once_with(mock_record)
    session.flush.assert_called_once()


def test_count_invitation_usage_success(monkeypatch, mock_session):
    """Test getting invitation usage count"""
    session, _ = mock_session

    # Create a mock query that returns count
    mock_specific_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.count.return_value = 3
    mock_specific_query.filter.return_value = mock_filter

    def mock_query_func(*args, **kwargs):
        return mock_specific_query

    session.query = mock_query_func

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)

    result = count_invitation_usage(123)

    assert result == 3


def test_get_invitation_status_in_use(monkeypatch, mock_session):
    """Test getting invitation status when in use"""
    session, query = mock_session

    mock_invitation = MockTenantInvitationCode()
    mock_invitation.status = "IN_USE"

    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_invitation
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)

    result = query_invitation_status("test_code")

    assert result == "IN_USE"


def test_get_invitation_status_expired(monkeypatch, mock_session):
    """Test getting invitation status when expired"""
    session, query = mock_session

    mock_invitation = MockTenantInvitationCode()
    mock_invitation.status = "EXPIRE"

    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_invitation
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)

    result = query_invitation_status("test_code")

    assert result == "EXPIRE"


def test_get_invitation_status_not_found(monkeypatch, mock_session):
    """Test getting invitation status when it doesn't exist"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)

    result = query_invitation_status("nonexistent_code")

    assert result is None


def test_database_error_handling(monkeypatch, mock_session):
    """Test database error handling"""
    session, query = mock_session
    query.filter.side_effect = MockSQLAlchemyError("Database error")

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)

    with pytest.raises(MockSQLAlchemyError, match="Database error"):
        query_invitation_by_code("test_code")


def test_query_invitations_with_pagination_success(monkeypatch, mock_session):
    """Test successfully querying invitations with pagination and usage count"""
    session, query = mock_session

    # Mock invitations data with usage counts (invitation_record, used_times)
    mock_invitation1 = MockTenantInvitationCode(invitation_id=1, invitation_code="code1")
    mock_invitation2 = MockTenantInvitationCode(invitation_id=2, invitation_code="code2")
    mock_results = [(mock_invitation1, 3), (mock_invitation2, 0)]  # invitation1 used 3 times, invitation2 used 0 times

    # Mock query chain
    mock_filter = MagicMock()
    mock_filter.count.return_value = 5  # Total count
    mock_offset = MagicMock()
    mock_offset.limit.return_value = mock_offset
    mock_offset.all.return_value = mock_results
    mock_filter.offset.return_value = mock_offset
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.invitation_db.as_dict", lambda obj: obj.__dict__)

    result = query_invitations_with_pagination(page=1, page_size=2)

    assert result["total"] == 5
    assert result["page"] == 1
    assert result["page_size"] == 2
    assert result["total_pages"] == 3  # Ceiling division: (5 + 2 - 1) // 2 = 3
    assert len(result["items"]) == 2
    assert result["items"][0]["invitation_code"] == "code1"
    assert result["items"][0]["used_times"] == 3
    assert result["items"][1]["invitation_code"] == "code2"
    assert result["items"][1]["used_times"] == 0


def test_query_invitations_with_pagination_empty_results(monkeypatch, mock_session):
    """Test querying invitations with pagination when no results"""
    session, query = mock_session

    # Mock empty results
    mock_filter = MagicMock()
    mock_filter.count.return_value = 0  # Total count
    mock_offset = MagicMock()
    mock_offset.limit.return_value = mock_offset
    mock_offset.all.return_value = []
    mock_filter.offset.return_value = mock_offset
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.invitation_db.as_dict", lambda obj: obj.__dict__)

    result = query_invitations_with_pagination(page=1, page_size=10)

    assert result["total"] == 0
    assert result["page"] == 1
    assert result["page_size"] == 10
    assert result["total_pages"] == 0  # Ceiling division: (0 + 10 - 1) // 10 = 0
    assert len(result["items"]) == 0


def test_query_invitations_with_pagination_with_tenant_filter(monkeypatch, mock_session):
    """Test querying invitations with pagination and tenant filter"""
    session, query = mock_session

    # Mock invitations data with usage count
    mock_invitation = MockTenantInvitationCode(invitation_id=1, invitation_code="code1", tenant_id="test_tenant")
    mock_result = (mock_invitation, 2)  # invitation used 2 times

    # Mock query chain with tenant filter
    mock_tenant_filter = MagicMock()
    mock_tenant_filter.count.return_value = 1
    mock_offset = MagicMock()
    mock_offset.limit.return_value = mock_offset
    mock_offset.all.return_value = [mock_result]
    mock_tenant_filter.offset.return_value = mock_offset

    mock_base_filter = MagicMock()
    mock_base_filter.filter.return_value = mock_tenant_filter
    query.filter.return_value = mock_base_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.invitation_db.as_dict", lambda obj: obj.__dict__)

    result = query_invitations_with_pagination(tenant_id="test_tenant", page=1, page_size=10)

    assert result["total"] == 1
    assert result["page"] == 1
    assert result["page_size"] == 10
    assert result["total_pages"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["tenant_id"] == "test_tenant"
    assert result["items"][0]["used_times"] == 2


def test_query_invitations_with_pagination_second_page(monkeypatch, mock_session):
    """Test querying invitations with pagination on second page"""
    session, query = mock_session

    # Mock invitations data for second page with usage count
    mock_invitation = MockTenantInvitationCode(invitation_id=3, invitation_code="code3")
    mock_result = (mock_invitation, 1)  # invitation used 1 time

    # Mock query chain
    mock_filter = MagicMock()
    mock_filter.count.return_value = 5  # Total count
    mock_offset = MagicMock()
    mock_offset.limit.return_value = mock_offset
    mock_offset.all.return_value = [mock_result]
    mock_filter.offset.return_value = mock_offset
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.invitation_db.as_dict", lambda obj: obj.__dict__)

    result = query_invitations_with_pagination(page=2, page_size=2)

    assert result["total"] == 5
    assert result["page"] == 2
    assert result["page_size"] == 2
    assert result["total_pages"] == 3
    assert len(result["items"]) == 1
    assert result["items"][0]["invitation_code"] == "code3"
    assert result["items"][0]["used_times"] == 1


def test_query_invitations_with_pagination_database_error(monkeypatch, mock_session):
    """Test database error handling in pagination query"""
    session, query = mock_session
    query.filter.side_effect = MockSQLAlchemyError("Database error")

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.invitation_db.get_db_session", lambda: mock_ctx)

    with pytest.raises(MockSQLAlchemyError, match="Database error"):
        query_invitations_with_pagination()
