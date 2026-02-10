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

# Add the mocked consts module to sys.modules
sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_mock.const

# Mock utils module
utils_mock = MagicMock()
utils_mock.auth_utils = MagicMock()
utils_mock.auth_utils.get_current_user_id_from_token = MagicMock(return_value="test_user_id")

# Mock str_utils module
str_utils_mock = MagicMock()


def mock_convert_string_to_list(s):
    """Mock implementation of convert_string_to_list that converts comma-separated string to int list"""
    if isinstance(s, str) and s:
        return [int(x.strip()) for x in s.split(',') if x.strip()]
    return []


str_utils_mock.convert_string_to_list = mock_convert_string_to_list
utils_mock.str_utils = str_utils_mock

# Add the mocked utils module to sys.modules
sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_mock.auth_utils
sys.modules['utils.str_utils'] = str_utils_mock

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
db_models_mock.TenantGroupInfo = MagicMock()
db_models_mock.TenantGroupUser = MagicMock()

class MockTenantGroupInfo:
    def __init__(self, **kwargs):
        self.group_id = kwargs.get('group_id', 1)
        self.tenant_id = kwargs.get('tenant_id', 'test_tenant')
        self.group_name = kwargs.get('group_name', 'test_group')
        self.group_description = kwargs.get('group_description', 'test description')
        self.created_by = kwargs.get('created_by', 'test_user')
        self.updated_by = kwargs.get('updated_by', 'test_user')
        self.delete_flag = kwargs.get('delete_flag', 'N')
        self.create_time = kwargs.get('create_time', '2024-01-01 00:00:00')
        self.update_time = kwargs.get('update_time', '2024-01-01 00:00:00')

class MockTenantGroupUser:
    def __init__(self, **kwargs):
        self.group_user_id = kwargs.get('group_user_id', 1)
        self.group_id = kwargs.get('group_id', 1)
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
from backend.database.group_db import (
    query_groups,
    query_groups_by_tenant,
    add_group,
    modify_group,
    remove_group,
    remove_group_users,
    add_user_to_group,
    remove_user_from_group,
    remove_user_from_all_groups,
    query_group_users,
    query_groups_by_user,
    query_group_ids_by_user,
    check_user_in_group,
    count_group_users,
    check_group_name_exists
)


@pytest.fixture
def mock_session():
    """Create mock database session"""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    return mock_session, mock_query


def test_get_group_by_id_success(monkeypatch, mock_session):
    """Test successfully retrieving group by ID"""
    session, query = mock_session

    mock_group = MockTenantGroupInfo()
    mock_group.group_id = 123
    mock_group.group_name = "test_group"

    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_group]
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.group_db.as_dict", lambda obj: obj.__dict__)

    result = query_groups(123)

    assert result is not None
    assert result["group_id"] == 123
    assert result["group_name"] == "test_group"


def test_get_group_by_id_not_found(monkeypatch, mock_session):
    """Test retrieving non-existent group"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = query_groups(999)

    assert result is None


def test_get_group_by_id_with_string_input(monkeypatch, mock_session):
    """Test retrieving groups by comma-separated string"""
    session, query = mock_session

    mock_group1 = MockTenantGroupInfo(group_id=1, group_name="group1")
    mock_group2 = MockTenantGroupInfo(group_id=2, group_name="group2")

    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_group1, mock_group2]
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr(
        "backend.database.group_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.group_db.as_dict",
                        lambda obj: obj.__dict__)

    result = query_groups("1,2")

    assert len(result) == 2
    assert result[0]["group_id"] == 1
    assert result[1]["group_id"] == 2


def test_get_group_by_id_with_list_input(monkeypatch, mock_session):
    """Test retrieving groups by list of IDs"""
    session, query = mock_session

    mock_group1 = MockTenantGroupInfo(group_id=1, group_name="group1")
    mock_group2 = MockTenantGroupInfo(group_id=3, group_name="group3")

    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_group1, mock_group2]
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr(
        "backend.database.group_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.group_db.as_dict",
                        lambda obj: obj.__dict__)

    result = query_groups([1, 3])

    assert len(result) == 2
    assert result[0]["group_id"] == 1
    assert result[1]["group_id"] == 3


def test_get_group_by_id_empty_string(monkeypatch, mock_session):
    """Test retrieving groups with empty string"""
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = None
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr(
        "backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = query_groups("")

    assert result == []


def test_get_group_by_id_empty_list(monkeypatch, mock_session):
    """Test retrieving groups with empty list"""
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = None
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr(
        "backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = query_groups([])

    assert result == []


def test_get_group_by_id_invalid_type():
    """Test get_group_by_id with invalid input type"""
    import pytest

    with pytest.raises(ValueError, match="group_id must be int, str, or List\\[int\\]"):
        query_groups(1.5)  # float is not supported


def test_get_groups_by_tenant_success(monkeypatch, mock_session):
    """Test retrieving groups by tenant"""
    session, query = mock_session

    mock_group1 = MockTenantGroupInfo(group_id=1, group_name="group1")
    mock_group2 = MockTenantGroupInfo(group_id=2, group_name="group2")

    # Mock the count query
    mock_count_filter = MagicMock()
    mock_count_filter.count.return_value = 2

    # Mock the paginated query chain
    mock_paginated_filter = MagicMock()
    mock_paginated_order_by = MagicMock()
    mock_paginated_offset = MagicMock()
    mock_paginated_limit = MagicMock()
    mock_paginated_limit.all.return_value = [mock_group1, mock_group2]
    mock_paginated_offset.limit.return_value = mock_paginated_limit
    mock_paginated_order_by.offset.return_value = mock_paginated_offset
    mock_paginated_filter.order_by.return_value = mock_paginated_order_by

    # Mock session.query to return different objects for different calls
    call_count = 0
    def mock_query(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:  # First call for count
            mock_q = MagicMock()
            mock_q.filter.return_value = mock_count_filter
            return mock_q
        else:  # Second call for paginated results
            mock_q = MagicMock()
            mock_q.filter.return_value = mock_paginated_filter
            return mock_q

    session.query = mock_query

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.group_db.as_dict", lambda obj: obj.__dict__)

    result = query_groups_by_tenant("test_tenant")

    assert result["total"] == 2
    assert len(result["groups"]) == 2
    assert result["groups"][0]["group_name"] == "group1"
    assert result["groups"][1]["group_name"] == "group2"


def test_create_group_success(monkeypatch, mock_session):
    """Test successfully creating group"""
    session, _ = mock_session
    session.add = MagicMock()

    mock_group = MockTenantGroupInfo()
    mock_group.group_id = 123

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    from unittest.mock import patch
    with patch('backend.database.group_db.TenantGroupInfo', return_value=mock_group):
        result = add_group(
            tenant_id="test_tenant",
            group_name="test_group",
            group_description="test description",
            created_by="test_user"
        )

    assert result == 123
    session.add.assert_called_once_with(mock_group)
    session.flush.assert_called_once()


def test_update_group_success(monkeypatch, mock_session):
    """Test successfully updating group"""
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
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = modify_group(
        group_id=123,
        updates={"group_name": "new_name", "group_description": "new description"},
        updated_by="test_user"
    )

    assert result is True


def test_soft_delete_group_success(monkeypatch, mock_session):
    """Test successfully soft deleting group"""
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
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = remove_group(group_id=123, updated_by="test_user")

    assert result is True


def test_add_user_to_group_success(monkeypatch, mock_session):
    """Test successfully adding user to group"""
    session, _ = mock_session
    session.add = MagicMock()

    mock_group_user = MockTenantGroupUser()
    mock_group_user.group_user_id = 456

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    from unittest.mock import patch
    with patch('backend.database.group_db.TenantGroupUser', return_value=mock_group_user):
        result = add_user_to_group(
            group_id=123,
            user_id="test_user",
            created_by="test_user"
        )

    assert result == 456
    session.add.assert_called_once_with(mock_group_user)
    session.flush.assert_called_once()


def test_remove_user_from_group_success(monkeypatch, mock_session):
    """Test successfully removing user from group"""
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
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = remove_user_from_group(
        group_id=123,
        user_id="test_user",
        updated_by="test_user"
    )

    assert result is True


def test_get_group_users_success(monkeypatch, mock_session):
    """Test retrieving users in a group"""
    session, query = mock_session

    mock_user1 = MockTenantGroupUser(group_user_id=1, user_id="user1")
    mock_user2 = MockTenantGroupUser(group_user_id=2, user_id="user2")

    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_user1, mock_user2]
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.group_db.as_dict", lambda obj: obj.__dict__)

    result = query_group_users(123)

    assert len(result) == 2
    assert result[0]["user_id"] == "user1"
    assert result[1]["user_id"] == "user2"


def test_get_groups_by_user_success(monkeypatch, mock_session):
    """Test retrieving groups for a user"""
    session, query = mock_session

    mock_group1 = MockTenantGroupInfo(group_id=1, group_name="group1")
    mock_group2 = MockTenantGroupInfo(group_id=2, group_name="group2")

    # Mock the join query
    mock_join = MagicMock()
    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_group1, mock_group2]
    mock_join.filter.return_value = mock_filter
    query.join.return_value = mock_join

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.group_db.as_dict", lambda obj: obj.__dict__)

    result = query_groups_by_user("test_user")

    assert len(result) == 2
    assert result[0]["group_name"] == "group1"
    assert result[1]["group_name"] == "group2"


def test_get_group_ids_by_user_success(monkeypatch, mock_session):
    """Test retrieving group IDs for a user"""
    session, _ = mock_session

    # Create a mock query that returns tuples of group_ids
    mock_specific_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.all.return_value = [(1,), (2,), (3,)]
    mock_specific_query.filter.return_value = mock_filter

    def mock_query_func(*args, **kwargs):
        return mock_specific_query

    session.query = mock_query_func

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr(
        "backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = query_group_ids_by_user("test_user")

    assert result == [1, 2, 3]


def test_is_user_in_group_true(monkeypatch, mock_session):
    """Test checking if user is in group - user is in group"""
    session, query = mock_session

    mock_group_user = MockTenantGroupUser()

    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_group_user
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = check_user_in_group("test_user", 123)

    assert result is True


def test_is_user_in_group_false(monkeypatch, mock_session):
    """Test checking if user is in group - user is not in group"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = check_user_in_group("test_user", 123)

    assert result is False


def test_get_group_user_count_success(monkeypatch, mock_session):
    """Test getting group user count"""
    session, _ = mock_session

    # Create a mock query that returns count
    mock_specific_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.count.return_value = 5
    mock_specific_query.filter.return_value = mock_filter

    def mock_query_func(*args, **kwargs):
        return mock_specific_query

    session.query = mock_query_func

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = count_group_users(123)

    assert result == 5


def test_query_groups_by_tenant_with_pagination(monkeypatch, mock_session):
    """Test retrieving groups by tenant with pagination"""
    session, query = mock_session

    mock_group1 = MockTenantGroupInfo(group_id=1, group_name="group1")
    mock_group2 = MockTenantGroupInfo(group_id=2, group_name="group2")

    # Mock the count query
    mock_count_filter = MagicMock()
    mock_count_filter.count.return_value = 2

    # Mock the paginated query chain
    mock_paginated_filter = MagicMock()
    mock_paginated_order_by = MagicMock()
    mock_paginated_offset = MagicMock()
    mock_paginated_limit = MagicMock()
    mock_paginated_limit.all.return_value = [mock_group1, mock_group2]
    mock_paginated_offset.limit.return_value = mock_paginated_limit
    mock_paginated_order_by.offset.return_value = mock_paginated_offset
    mock_paginated_filter.order_by.return_value = mock_paginated_order_by

    # Mock session.query to return different objects for different calls
    call_count = 0
    def mock_query(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:  # First call for count
            mock_q = MagicMock()
            mock_q.filter.return_value = mock_count_filter
            return mock_q
        else:  # Second call for paginated results
            mock_q = MagicMock()
            mock_q.filter.return_value = mock_paginated_filter
            return mock_q

    session.query = mock_query

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.group_db.as_dict", lambda obj: obj.__dict__)

    result = query_groups_by_tenant("test_tenant", page=2, page_size=10)

    # Verify pagination parameters were used correctly
    mock_paginated_order_by.offset.assert_called_with(10)  # (page-1) * page_size = (2-1) * 10 = 10
    mock_paginated_offset.limit.assert_called_with(10)

    assert result["total"] == 2
    assert len(result["groups"]) == 2
    assert result["groups"][0]["group_name"] == "group1"
    assert result["groups"][1]["group_name"] == "group2"


def test_modify_group_no_updates_provided(monkeypatch, mock_session):
    """Test modifying group with no updates provided"""
    session, query = mock_session

    mock_update = MagicMock()
    mock_update.return_value = 1
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = modify_group(group_id=123, updates={})

    assert result is True


def test_modify_group_no_rows_affected(monkeypatch, mock_session):
    """Test modifying group when no rows are affected"""
    session, query = mock_session

    mock_update = MagicMock()
    mock_update.return_value = 0  # No rows affected
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = modify_group(group_id=999, updates={"group_name": "new_name"})

    assert result is False


def test_remove_group_no_rows_affected(monkeypatch, mock_session):
    """Test removing group when no rows are affected"""
    session, query = mock_session

    # First query: TenantGroupInfo
    mock_group_filter = MagicMock()
    mock_group_filter.update.return_value = 0  # No rows affected for TenantGroupInfo
    mock_group_filter.filter.return_value = mock_group_filter

    # Second query: TenantGroupUser
    mock_user_filter = MagicMock()
    mock_user_filter.update.return_value = 0
    mock_user_filter.filter.return_value = mock_user_filter

    # Setup session.query() to return different mocks for different model classes
    query_call_count = [0]
    def query_call_side_effect(model_class):
        query_call_count[0] += 1
        if query_call_count[0] == 1:
            # First call: TenantGroupInfo
            return mock_group_filter
        else:
            # Second call: TenantGroupUser
            return mock_user_filter
    session.query.side_effect = query_call_side_effect

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = remove_group(group_id=999, updated_by="test_user")

    assert result is False


def test_remove_group_success(monkeypatch, mock_session):
    """Test successfully removing group and its user relationships"""
    session, query = mock_session

    # First query: TenantGroupInfo - need filter() to return the same mock so update() works
    mock_group_filter = MagicMock()
    mock_group_filter.update.return_value = 1  # One row affected for TenantGroupInfo
    # Make filter() return the same mock so chained .update() works
    mock_group_filter.filter.return_value = mock_group_filter

    # Second query: TenantGroupUser
    mock_user_filter = MagicMock()
    mock_user_filter.update.return_value = 3  # Three user-group relationships removed
    mock_user_filter.filter.return_value = mock_user_filter

    # Setup session.query() to return different mocks for different model classes
    query_call_count = [0]
    def query_call_side_effect(model_class):
        query_call_count[0] += 1
        if query_call_count[0] == 1:
            # First call: TenantGroupInfo
            return mock_group_filter
        else:
            # Second call: TenantGroupUser
            return mock_user_filter
    session.query.side_effect = query_call_side_effect

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = remove_group(group_id=123, updated_by="admin_user")

    assert result is True


def test_remove_user_from_group_no_rows_affected(monkeypatch, mock_session):
    """Test removing user from group when no rows are affected"""
    session, query = mock_session

    mock_update = MagicMock()
    mock_update.return_value = 0  # No rows affected
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = remove_user_from_group(group_id=999, user_id="nonexistent_user", updated_by="test_user")

    assert result is False


def test_query_groups_by_user_no_groups(monkeypatch, mock_session):
    """Test retrieving groups for user when user has no groups"""
    session, query = mock_session

    mock_join = MagicMock()
    mock_filter = MagicMock()
    mock_filter.all.return_value = []
    mock_join.filter.return_value = mock_filter
    query.join.return_value = mock_join

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.group_db.as_dict", lambda obj: obj.__dict__)

    result = query_groups_by_user("user_with_no_groups")

    assert result == []


def test_query_group_ids_by_user_no_groups(monkeypatch, mock_session):
    """Test retrieving group IDs for user when user has no groups"""
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
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = query_group_ids_by_user("user_with_no_groups")

    assert result == []


def test_remove_user_from_all_groups_success(monkeypatch, mock_session):
    """Test successfully removing user from all groups"""
    session, query = mock_session

    # Setup query.filter().update() chain for TenantGroupUser
    mock_update = MagicMock()
    mock_update.return_value = 3  # 3 group memberships removed
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = remove_user_from_all_groups(
        user_id="test_user",
        removed_by="admin_user"
    )

    assert result == 3
    # Verify the filter was called
    query.filter.assert_called_once()
    # Verify update was called with correct parameters
    mock_update.assert_called_once_with({
        "delete_flag": "Y",
        "updated_by": "admin_user",
        "update_time": "NOW()"
    })


def test_remove_user_from_all_groups_no_memberships(monkeypatch, mock_session):
    """Test removing user from all groups when user has no group memberships"""
    session, query = mock_session

    # Setup query.filter().update() chain
    mock_update = MagicMock()
    mock_update.return_value = 0  # No rows affected
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = remove_user_from_all_groups(
        user_id="user_with_no_groups",
        removed_by="admin_user"
    )

    assert result == 0
    # Verify update was still called even with 0 affected rows
    mock_update.assert_called_once_with({
        "delete_flag": "Y",
        "updated_by": "admin_user",
        "update_time": "NOW()"
    })


def test_remove_user_from_all_groups_database_error(monkeypatch, mock_session):
    """Test database error handling for remove_user_from_all_groups"""
    session, query = mock_session

    # Setup query.filter() to raise an error
    query.filter.side_effect = MockSQLAlchemyError("Database connection failed")

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    with pytest.raises(MockSQLAlchemyError, match="Database connection failed"):
        remove_user_from_all_groups(
            user_id="test_user",
            removed_by="admin_user"
        )


def test_database_error_handling(monkeypatch, mock_session):
    """Test database error handling"""
    session, query = mock_session
    query.filter.side_effect = MockSQLAlchemyError("Database error")

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    with pytest.raises(MockSQLAlchemyError, match="Database error"):
        query_groups(123)


def test_check_group_name_exists_found(monkeypatch, mock_session):
    """Test checking group name exists - name found"""
    session, query = mock_session

    # Mock finding a group with the same name
    mock_group = MockTenantGroupInfo(group_id=1, group_name="test_group")

    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_group
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = check_group_name_exists("test_tenant", "test_group")

    assert result is True
    # Verify the filter was called
    query.filter.assert_called_once()


def test_check_group_name_exists_not_found(monkeypatch, mock_session):
    """Test checking group name exists - name not found"""
    session, query = mock_session

    # Mock not finding any group with the same name
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = check_group_name_exists("test_tenant", "new_group")

    assert result is False


def test_check_group_name_exists_with_exclusion(monkeypatch, mock_session):
    """Test checking group name exists - exclude specific group ID"""
    session, query = mock_session

    # Mock not finding any group (because the found group is excluded)
    mock_filter = MagicMock()
    mock_filter.first.return_value = None

    # Mock the chain for .filter().filter()
    mock_inner_filter = MagicMock()
    mock_inner_filter.first.return_value = None
    mock_filter.filter.return_value = mock_inner_filter

    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    # When updating group 1 to name "test_group", exclude group 1
    result = check_group_name_exists("test_tenant", "test_group", exclude_group_id=1)

    assert result is False
    # Verify filter().filter() was called (second filter for exclusion)
    mock_filter.filter.assert_called_once_with(
        db_models_mock.TenantGroupInfo.group_id != 1
    )


def test_check_group_name_exists_database_error(monkeypatch, mock_session):
    """Test checking group name exists - database error"""
    session, query = mock_session

    query.filter.side_effect = MockSQLAlchemyError("Database error")

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    with pytest.raises(MockSQLAlchemyError, match="Database error"):
        check_group_name_exists("test_tenant", "test_group")


def test_remove_group_users_success(monkeypatch, mock_session):
    """Test successfully removing all users from a group"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.update.return_value = 5  # Five user-group relationships removed
    mock_filter.filter.return_value = mock_filter

    session.query.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = remove_group_users(group_id=123, removed_by="admin_user")

    assert result == 5


def test_remove_group_users_no_rows_affected(monkeypatch, mock_session):
    """Test removing users from group when no relationships exist"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.update.return_value = 0  # No rows affected
    mock_filter.filter.return_value = mock_filter

    session.query.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.group_db.get_db_session", lambda: mock_ctx)

    result = remove_group_users(group_id=999, removed_by="admin_user")

    assert result == 0
