import sys
import pytest
from unittest.mock import patch, MagicMock

# Mock external dependencies before importing
sys.modules['psycopg2'] = MagicMock()
sys.modules['boto3'] = MagicMock()
sys.modules['supabase'] = MagicMock()

from consts.exceptions import NotFoundException, UnauthorizedError
from backend.services.group_service import (
    get_group_info,
    create_group,
    update_group,
    delete_group,
    add_user_to_group,
    remove_user_from_group,
    get_group_users,
    get_group_user_count,
    add_user_to_groups
)
from backend.database.group_db import (
    query_groups_by_tenant,
    query_groups_by_user,
    query_group_ids_by_user,
    check_user_in_group
)


@pytest.fixture
def mock_user_info():
    """Mock user tenant information"""
    return {
        "user_tenant_id": 1,
        "user_id": "test_user",
        "tenant_id": "test_tenant",
        "user_role": "ADMIN"
    }


@pytest.fixture
def mock_group_info():
    """Mock group information"""
    return {
        "group_id": 123,
        "tenant_id": "test_tenant",
        "group_name": "Test Group",
        "group_description": "Test group description"
    }


@patch('backend.services.group_service.get_group_by_id')
def test_get_group_info_single(mock_get_group):
    """Test getting single group"""
    mock_get_group.return_value = {"group_id": 123, "group_name": "Test Group"}

    result = get_group_info(123)

    assert result["group_id"] == 123
    assert result["group_name"] == "Test Group"
    mock_get_group.assert_called_once_with(123)


@patch('backend.services.group_service.get_group_by_id')
def test_get_group_info_not_found(mock_get_group):
    """Test getting non-existent group"""
    mock_get_group.return_value = None

    with pytest.raises(NotFoundException, match="Group 123 not found"):
        get_group_info(123)


@patch('backend.database.group_db.query_groups_by_tenant')
def test_get_groups_by_tenant(mock_get_groups):
    """Test getting groups by tenant"""
    mock_groups = [
        {"group_id": 1, "group_name": "Group 1"},
        {"group_id": 2, "group_name": "Group 2"}
    ]
    mock_get_groups.return_value = mock_groups

    result = query_groups_by_tenant("tenant_123")

    assert len(result) == 2
    assert result[0]["group_name"] == "Group 1"
    mock_get_groups.assert_called_once_with("tenant_123")


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.create_group')
def test_create_group_success(mock_create_group, mock_get_user, mock_user_info):
    """Test creating group successfully"""
    mock_get_user.return_value = mock_user_info
    mock_create_group.return_value = 123

    result = create_group(
        tenant_id="test_tenant",
        group_name="Test Group",
        group_description="Description",
        user_id="test_user"
    )

    assert result["group_id"] == 123
    assert result["group_name"] == "Test Group"
    mock_create_group.assert_called_once_with(
        tenant_id="test_tenant",
        group_name="Test Group",
        group_description="Description",
        created_by="test_user"
    )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
def test_create_group_unauthorized(mock_get_user, mock_user_info):
    """Test creating group with unauthorized user"""
    mock_user_info["user_role"] = "USER"
    mock_get_user.return_value = mock_user_info

    with pytest.raises(UnauthorizedError, match="not authorized to create groups"):
        create_group(
            tenant_id="test_tenant",
            group_name="Test Group",
            user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.get_group_by_id')
@patch('backend.services.group_service.update_group')
def test_update_group_success(mock_update_group, mock_get_group, mock_get_user, mock_user_info, mock_group_info):
    """Test updating group successfully"""
    mock_get_user.return_value = mock_user_info
    mock_get_group.return_value = mock_group_info
    mock_update_group.return_value = True

    result = update_group(
        group_id=123,
        updates={"group_name": "Updated Group"},
        user_id="test_user"
    )

    assert result is True
    mock_update_group.assert_called_once_with(
        group_id=123,
        updates={"group_name": "Updated Group"},
        updated_by="test_user"
    )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.get_group_by_id')
def test_update_group_not_found(mock_get_group, mock_get_user, mock_user_info):
    """Test updating non-existent group"""
    mock_get_user.return_value = mock_user_info
    mock_get_group.return_value = None

    with pytest.raises(NotFoundException, match="Group 123 not found"):
        update_group(
            group_id=123,
            updates={"group_name": "Updated Group"},
            user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.get_group_by_id')
@patch('backend.services.group_service.soft_delete_group')
def test_delete_group_success(mock_delete_group, mock_get_group, mock_get_user, mock_user_info, mock_group_info):
    """Test deleting group successfully"""
    mock_get_user.return_value = mock_user_info
    mock_get_group.return_value = mock_group_info
    mock_delete_group.return_value = True

    result = delete_group(
        group_id=123,
        user_id="test_user"
    )

    assert result is True
    mock_delete_group.assert_called_once_with(
        group_id=123,
        updated_by="test_user"
    )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.get_group_by_id')
@patch('backend.services.group_service.add_user_to_group')
@patch('backend.services.group_service.is_user_in_group')
def test_add_user_to_group_success(mock_is_user_in_group, mock_add_user, mock_get_group, mock_get_user, mock_user_info, mock_group_info):
    """Test adding user to group successfully"""
    mock_get_user.return_value = mock_user_info
    mock_get_group.return_value = mock_group_info
    mock_is_user_in_group.return_value = False
    mock_add_user.return_value = 456

    result = add_user_to_group(
        group_id=123,
        user_id="member_user",
        current_user_id="test_user"
    )

    assert result["group_user_id"] == 456
    assert result["already_member"] is False
    mock_add_user.assert_called_once_with(
        group_id=123,
        user_id="member_user",
        created_by="test_user"
    )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.get_group_by_id')
@patch('backend.services.group_service.is_user_in_group')
def test_add_user_to_group_service_already_member(mock_is_user_in_group, mock_get_group, mock_get_user, mock_user_info, mock_group_info):
    """Test adding user who is already in group"""
    mock_get_user.return_value = mock_user_info
    mock_get_group.return_value = mock_group_info
    mock_is_user_in_group.return_value = True

    result = add_user_to_group(
        group_id=123,
        user_id="member_user",
        current_user_id="test_user"
    )

    assert result["already_member"] is True
    assert result["group_id"] == 123


@patch('backend.services.group_service.get_group_by_id')
@patch('backend.services.group_service.get_group_users')
def test_get_group_users_success(mock_get_users, mock_get_group, mock_group_info):
    """Test getting group users successfully"""
    mock_get_group.return_value = mock_group_info
    mock_users = [{"user_id": "user1"}, {"user_id": "user2"}]
    mock_get_users.return_value = mock_users

    result = get_group_users(123)

    assert len(result) == 2
    assert result[0]["user_id"] == "user1"
    mock_get_users.assert_called_once_with(123)


@patch('backend.database.group_db.query_groups_by_user')
def test_get_groups_by_user(mock_get_groups):
    """Test getting user groups"""
    mock_groups = [{"group_id": 1, "group_name": "Group 1"}]
    mock_get_groups.return_value = mock_groups

    result = query_groups_by_user("user_123")

    assert len(result) == 1
    assert result[0]["group_name"] == "Group 1"
    mock_get_groups.assert_called_once_with("user_123")


@patch('backend.database.group_db.query_group_ids_by_user')
def test_get_group_ids_by_user(mock_get_group_ids):
    """Test getting user group IDs"""
    mock_get_group_ids.return_value = [1, 2, 3]

    result = query_group_ids_by_user("user_123")

    assert result == [1, 2, 3]
    mock_get_group_ids.assert_called_once_with("user_123")


@patch('backend.database.group_db.check_user_in_group')
def test_is_user_in_group(mock_is_user_in_group):
    """Test checking if user is in group"""
    mock_is_user_in_group.return_value = True

    result = check_user_in_group("user_123", 456)

    assert result is True
    mock_is_user_in_group.assert_called_once_with("user_123", 456)


@patch('backend.services.group_service.get_group_by_id')
@patch('backend.services.group_service.get_group_user_count')
def test_get_group_user_count_success(mock_get_count, mock_get_group, mock_group_info):
    """Test getting group user count successfully"""
    mock_get_group.return_value = mock_group_info
    mock_get_count.return_value = 5

    result = get_group_user_count(123)

    assert result == 5
    mock_get_count.assert_called_once_with(123)


@patch('backend.services.group_service.add_user_to_group')
def test_add_user_to_groups(mock_add_user):
    """Test adding user to multiple groups"""
    mock_add_user.side_effect = [
        {"group_id": 1, "user_id": "user_123", "already_member": False},
        {"group_id": 2, "user_id": "user_123", "already_member": False}
    ]

    result = add_user_to_groups("user_123", [1, 2], "admin_user")

    assert len(result) == 2
    assert result[0]["group_id"] == 1
    assert result[1]["group_id"] == 2
