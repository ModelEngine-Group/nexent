from consts.exceptions import NotFoundException, UnauthorizedError, ValidationError
import sys
import pytest
from unittest.mock import patch, MagicMock

# Mock external dependencies before importing
sys.modules['psycopg2'] = MagicMock()
sys.modules['boto3'] = MagicMock()
sys.modules['supabase'] = MagicMock()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
      return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate',
      lambda self: None).start()
patch('backend.database.client.MinioClient',
      return_value=minio_client_mock).start()


from backend.services.group_service import (
    get_group_info,
    get_groups_by_tenant,
    get_tenant_default_group_id,
    set_tenant_default_group_id,
    create_group,
    update_group,
    delete_group,
    add_user_to_single_group,
    remove_user_from_single_group,
    get_group_users,
    get_group_user_count,
    add_user_to_groups,
    update_group_members
)
# These imports are used in the patch decorators, not directly in the test functions


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


@patch('backend.services.group_service.query_groups')
def test_get_group_info_single(mock_query_groups):
    """Test getting single group"""
    mock_query_groups.return_value = {
        "group_id": 123, "group_name": "Test Group"}

    result = get_group_info(123)

    assert result["group_id"] == 123
    assert result["group_name"] == "Test Group"
    mock_query_groups.assert_called_once_with(123)


@patch('backend.services.group_service.query_groups')
def test_get_group_info_not_found(mock_query_groups):
    """Test getting non-existent group"""
    mock_query_groups.return_value = None

    with pytest.raises(NotFoundException, match="Group 123 not found"):
        get_group_info(123)


@patch('backend.services.group_service.query_groups')
def test_get_group_info_multiple_groups(mock_query_groups):
    """Test getting multiple groups by list of IDs"""
    mock_groups = [
        {"group_id": 1, "group_name": "Group 1", "group_description": "Desc 1"},
        {"group_id": 2, "group_name": "Group 2", "group_description": "Desc 2"}
    ]
    mock_query_groups.return_value = mock_groups

    result = get_group_info([1, 2])

    assert len(result) == 2
    assert result[0]["group_id"] == 1
    assert result[0]["group_name"] == "Group 1"
    assert result[0]["group_description"] == "Desc 1"
    assert result[1]["group_id"] == 2
    assert result[1]["group_name"] == "Group 2"
    assert result[1]["group_description"] == "Desc 2"
    mock_query_groups.assert_called_once_with([1, 2])


@patch('backend.services.group_service.query_groups')
def test_get_group_info_string_group_ids(mock_query_groups):
    """Test getting groups by comma-separated string of IDs"""
    mock_groups = [
        {"group_id": 1, "group_name": "Group 1", "group_description": "Desc 1"}
    ]
    mock_query_groups.return_value = mock_groups

    result = get_group_info("1")

    assert len(result) == 1
    assert result[0]["group_id"] == 1
    assert result[0]["group_name"] == "Group 1"
    assert result[0]["group_description"] == "Desc 1"
    mock_query_groups.assert_called_once_with("1")


@patch('backend.services.group_service.count_group_users')
@patch('backend.services.group_service.query_groups_by_tenant')
def test_get_groups_by_tenant_success(mock_query_groups_by_tenant, mock_count_users):
    """Test getting groups by tenant with pagination"""
    mock_result = {
        "groups": [
            {"group_id": 1, "group_name": "Group 1", "group_description": "Desc 1"},
            {"group_id": 2, "group_name": "Group 2", "group_description": "Desc 2"}
        ],
        "total": 2
    }
    mock_query_groups_by_tenant.return_value = mock_result
    # Mock count_group_users to return 3 for each group
    mock_count_users.return_value = 3

    result = get_groups_by_tenant("test_tenant", page=1, page_size=10)

    assert result["total"] == 2
    assert len(result["groups"]) == 2
    assert result["groups"][0]["group_id"] == 1
    assert result["groups"][0]["group_name"] == "Group 1"
    assert result["groups"][0]["group_description"] == "Desc 1"
    assert result["groups"][0]["user_count"] == 3  # Check user count
    assert result["groups"][1]["group_id"] == 2
    assert result["groups"][1]["group_name"] == "Group 2"
    assert result["groups"][1]["group_description"] == "Desc 2"
    assert result["groups"][1]["user_count"] == 3  # Check user count
    mock_query_groups_by_tenant.assert_called_once_with("test_tenant", 1, 10, "created_at", "desc")
    # count_group_users should be called for each group
    assert mock_count_users.call_count == 2




@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.check_group_name_exists')
@patch('backend.services.group_service.add_group')
def test_create_group_success(mock_add_group, mock_check_name, mock_get_user, mock_user_info):
    """Test creating group successfully"""
    mock_get_user.return_value = mock_user_info
    mock_check_name.return_value = False  # Name doesn't exist
    mock_add_group.return_value = 123

    result = create_group(
        tenant_id="test_tenant",
        group_name="Test Group",
        group_description="Description",
        user_id="test_user"
    )

    assert result["group_id"] == 123
    assert result["group_name"] == "Test Group"
    mock_add_group.assert_called_once_with(
        tenant_id="test_tenant",
        group_name="Test Group",
        group_description="Description",
        created_by="test_user"
    )
    mock_check_name.assert_called_once_with("test_tenant", "Test Group")


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
@patch('backend.services.group_service.check_group_name_exists')
def test_create_group_duplicate_name(mock_check_name, mock_get_user, mock_user_info):
    """Test creating group with duplicate name"""
    mock_get_user.return_value = mock_user_info
    mock_check_name.return_value = True  # Simulate name already exists

    with pytest.raises(ValidationError, match="Group name 'Test Group' already exists"):
        create_group(
            tenant_id="test_tenant",
            group_name="Test Group",
            group_description="Description",
            user_id="test_user"
        )

    mock_check_name.assert_called_once_with("test_tenant", "Test Group")


@patch('backend.services.group_service.get_user_tenant_by_user_id')
def test_create_group_user_not_found(mock_get_user):
    """Test creating group when user doesn't exist"""
    mock_get_user.return_value = None

    with pytest.raises(NotFoundException, match="User test_user not found"):
        create_group(
            tenant_id="test_tenant",
            group_name="Test Group",
            user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.check_group_name_exists')
@patch('backend.services.group_service.query_groups')
@patch('backend.services.group_service.modify_group')
def test_update_group_success(mock_modify_group, mock_query_groups, mock_check_name, mock_get_user, mock_user_info, mock_group_info):
    """Test updating group successfully"""
    mock_get_user.return_value = mock_user_info
    mock_query_groups.return_value = mock_group_info
    mock_check_name.return_value = False  # Name doesn't exist
    mock_modify_group.return_value = True

    result = update_group(
        group_id=123,
        updates={"group_name": "Updated Group"},
        user_id="test_user"
    )

    assert result is True
    mock_modify_group.assert_called_once_with(
        group_id=123,
        updates={"group_name": "Updated Group"},
        updated_by="test_user"
    )
    mock_check_name.assert_called_once_with(
        mock_group_info["tenant_id"],
        "Updated Group",
        exclude_group_id=123
    )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.query_groups')
def test_update_group_not_found(mock_query_groups, mock_get_user, mock_user_info):
    """Test updating non-existent group"""
    mock_get_user.return_value = mock_user_info
    mock_query_groups.return_value = None

    with pytest.raises(NotFoundException, match="Group 123 not found"):
        update_group(
            group_id=123,
            updates={"group_name": "Updated Group"},
            user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
def test_update_group_user_not_found(mock_get_user):
    """Test updating group when user doesn't exist"""
    mock_get_user.return_value = None

    with pytest.raises(NotFoundException, match="User test_user not found"):
        update_group(
            group_id=123,
            updates={"group_name": "Updated Group"},
            user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
def test_update_group_unauthorized_role(mock_get_user, mock_user_info):
    """Test updating group with insufficient user permissions"""
    mock_user_info["user_role"] = "USER"
    mock_get_user.return_value = mock_user_info

    with pytest.raises(UnauthorizedError, match="not authorized to update groups"):
        update_group(
            group_id=123,
            updates={"group_name": "Updated Group"},
            user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.query_groups')
@patch('backend.services.group_service.check_group_name_exists')
def test_update_group_duplicate_name(mock_check_name, mock_query_groups, mock_get_user, mock_user_info, mock_group_info):
    """Test updating group with duplicate name"""
    mock_get_user.return_value = mock_user_info
    mock_query_groups.return_value = mock_group_info
    mock_check_name.return_value = True  # Simulate name already exists

    with pytest.raises(ValidationError, match="Group name 'Test Group' already exists"):
        update_group(
            group_id=123,
            updates={"group_name": "Test Group"},  # Trying to rename to existing name
            user_id="test_user"
        )

    mock_check_name.assert_called_once_with(
        mock_group_info["tenant_id"],
        "Test Group",
        exclude_group_id=123
    )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.query_groups')
@patch('backend.services.group_service.remove_group')
def test_delete_group_success(mock_remove_group, mock_query_groups, mock_get_user, mock_user_info, mock_group_info):
    """Test deleting group successfully"""
    mock_get_user.return_value = mock_user_info
    mock_query_groups.return_value = mock_group_info
    mock_remove_group.return_value = True

    result = delete_group(
        group_id=123,
        user_id="test_user"
    )

    assert result is True
    mock_remove_group.assert_called_once_with(
        group_id=123,
        updated_by="test_user"
    )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
def test_delete_group_user_not_found(mock_get_user):
    """Test deleting group when user doesn't exist"""
    mock_get_user.return_value = None

    with pytest.raises(NotFoundException, match="User test_user not found"):
        delete_group(
            group_id=123,
            user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
def test_delete_group_unauthorized_role(mock_get_user, mock_user_info):
    """Test deleting group with insufficient user permissions"""
    mock_user_info["user_role"] = "USER"
    mock_get_user.return_value = mock_user_info

    with pytest.raises(UnauthorizedError, match="not authorized to delete groups"):
        delete_group(
            group_id=123,
            user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.query_groups')
def test_delete_group_group_not_found(mock_query_groups, mock_get_user, mock_user_info):
    """Test deleting non-existent group"""
    mock_get_user.return_value = mock_user_info
    mock_query_groups.return_value = None

    with pytest.raises(NotFoundException, match="Group 123 not found"):
        delete_group(
            group_id=123,
            user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.query_groups')
@patch('backend.services.group_service.add_user_to_group')
@patch('backend.services.group_service.check_user_in_group')
def test_add_user_to_single_group_success(mock_check_user, mock_add_user, mock_query_groups, mock_get_user, mock_user_info, mock_group_info):
    """Test adding user to group successfully"""
    mock_get_user.return_value = mock_user_info
    mock_query_groups.return_value = mock_group_info
    mock_check_user.return_value = False
    mock_add_user.return_value = 456

    result = add_user_to_single_group(
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
@patch('backend.services.group_service.query_groups')
@patch('backend.services.group_service.check_user_in_group')
def test_add_user_to_single_group_already_member(mock_check_user, mock_query_groups, mock_get_user, mock_user_info, mock_group_info):
    """Test adding user who is already in group"""
    mock_get_user.return_value = mock_user_info
    mock_query_groups.return_value = mock_group_info
    mock_check_user.return_value = True

    result = add_user_to_single_group(
        group_id=123,
        user_id="member_user",
        current_user_id="test_user"
    )

    assert result["already_member"] is True
    assert result["group_id"] == 123


@patch('backend.services.group_service.get_user_tenant_by_user_id')
def test_add_user_to_single_group_current_user_not_found(mock_get_user):
    """Test adding user to group when current user doesn't exist"""
    mock_get_user.return_value = None

    with pytest.raises(UnauthorizedError, match="User test_user not found"):
        add_user_to_single_group(
            group_id=123,
            user_id="member_user",
            current_user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.query_groups')
def test_add_user_to_single_group_group_not_found(mock_query_groups, mock_get_user, mock_user_info):
    """Test adding user to non-existent group"""
    mock_get_user.return_value = mock_user_info
    mock_query_groups.return_value = None

    with pytest.raises(NotFoundException, match="Group 123 not found"):
        add_user_to_single_group(
            group_id=123,
            user_id="member_user",
            current_user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.query_groups')
@patch('backend.services.group_service.query_group_users')
def test_get_group_users_success(mock_query_users, mock_query_groups, mock_get_user, mock_group_info):
    """Test getting group users successfully"""
    mock_query_groups.return_value = mock_group_info
    mock_users = [{"user_id": "user1"}, {"user_id": "user2"}]
    mock_query_users.return_value = mock_users

    # Mock get_user_tenant_by_user_id to return user info for each user
    def mock_user_info(user_id):
        if user_id == "user1":
            return {"user_id": "user1", "user_email": "user1@example.com", "user_role": "USER"}
        elif user_id == "user2":
            return {"user_id": "user2", "user_email": "user2@example.com", "user_role": "ADMIN"}
        return None

    mock_get_user.side_effect = mock_user_info

    result = get_group_users(123)

    assert len(result) == 2
    assert result[0]["id"] == "user1"
    assert result[0]["username"] == "user1@example.com"
    assert result[0]["role"] == "USER"
    assert result[1]["id"] == "user2"
    assert result[1]["username"] == "user2@example.com"
    assert result[1]["role"] == "ADMIN"
    mock_query_users.assert_called_once_with(123)
    # get_user_tenant_by_user_id should be called for each user
    assert mock_get_user.call_count == 2


@patch('backend.services.group_service.query_groups')
@patch('backend.services.group_service.count_group_users')
def test_get_group_user_count_success(mock_count_users, mock_query_groups, mock_group_info):
    """Test getting group user count successfully"""
    mock_query_groups.return_value = mock_group_info
    mock_count_users.return_value = 5

    result = get_group_user_count(123)

    assert result == 5
    mock_count_users.assert_called_once_with(123)


@patch('backend.services.group_service.query_groups')
def test_get_group_user_count_group_not_found(mock_query_groups):
    """Test getting user count for non-existent group"""
    mock_query_groups.return_value = None

    with pytest.raises(NotFoundException, match="Group 123 not found"):
        get_group_user_count(123)


@patch('backend.services.group_service.add_user_to_single_group')
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


@patch('backend.services.group_service.add_user_to_single_group')
def test_add_user_to_groups_with_exception(mock_add_user):
    """Test adding user to multiple groups with exception handling"""
    mock_add_user.side_effect = [
        {"group_id": 1, "user_id": "user_123", "already_member": False},
        Exception("Group not found")  # Simulate exception for second group
    ]

    result = add_user_to_groups("user_123", [1, 2], "admin_user")

    assert len(result) == 2
    assert result[0]["group_id"] == 1
    assert result[0]["already_member"] is False
    assert result[1]["group_id"] == 2
    assert result[1]["error"] == "Group not found"


@patch('backend.services.group_service.get_tenant_info')
def test_get_tenant_default_group_id_success(mock_get_tenant_info):
    """Test getting tenant default group ID successfully"""
    mock_get_tenant_info.return_value = {"default_group_id": "123"}

    result = get_tenant_default_group_id("test_tenant")

    assert result == 123
    mock_get_tenant_info.assert_called_once_with("test_tenant")


@patch('backend.services.group_service.get_tenant_info')
def test_get_tenant_default_group_id_no_default(mock_get_tenant_info):
    """Test getting tenant default group ID when none is set"""
    mock_get_tenant_info.return_value = {"default_group_id": ""}

    result = get_tenant_default_group_id("test_tenant")

    assert result is None
    mock_get_tenant_info.assert_called_once_with("test_tenant")


@patch('backend.services.group_service.get_tenant_info')
def test_get_tenant_default_group_id_exception(mock_get_tenant_info):
    """Test getting tenant default group ID when exception occurs"""
    mock_get_tenant_info.side_effect = Exception("Database error")

    result = get_tenant_default_group_id("test_tenant")

    assert result is None


@patch('backend.services.group_service.get_tenant_info')
@patch('backend.services.group_service.query_groups')
@patch('backend.services.group_service.get_single_config_info')
@patch('backend.services.group_service.update_config_by_tenant_config_id')
def test_set_tenant_default_group_id_update_existing(mock_update_config, mock_get_config, mock_query_groups, mock_get_tenant_info):
    """Test setting tenant default group ID by updating existing config"""
    mock_get_tenant_info.return_value = {"tenant_id": "test_tenant"}
    mock_query_groups.return_value = {"tenant_id": "test_tenant"}
    mock_get_config.return_value = {"tenant_config_id": 456}
    mock_update_config.return_value = True

    result = set_tenant_default_group_id("test_tenant", 123, "user_123")

    assert result is True
    mock_update_config.assert_called_once_with(456, "123")


@patch('backend.services.group_service.get_tenant_info')
@patch('backend.services.group_service.query_groups')
@patch('backend.services.group_service.get_single_config_info')
@patch('backend.services.group_service.insert_config')
def test_set_tenant_default_group_id_create_new(mock_insert_config, mock_get_config, mock_query_groups, mock_get_tenant_info):
    """Test setting tenant default group ID by creating new config"""
    mock_get_tenant_info.return_value = {"tenant_id": "test_tenant"}
    mock_query_groups.return_value = {"tenant_id": "test_tenant"}
    mock_get_config.return_value = None  # No existing config
    mock_insert_config.return_value = True

    result = set_tenant_default_group_id("test_tenant", 123, "user_123")

    assert result is True
    mock_insert_config.assert_called_once()
    call_args = mock_insert_config.call_args[0][0]  # Get the dict argument
    assert call_args["tenant_id"] == "test_tenant"
    assert call_args["config_key"] == "DEFAULT_GROUP_ID"
    assert call_args["config_value"] == "123"


@patch('backend.services.group_service.get_tenant_info')
def test_set_tenant_default_group_id_tenant_not_found(mock_get_tenant_info):
    """Test setting tenant default group ID when tenant doesn't exist"""
    mock_get_tenant_info.return_value = None

    with pytest.raises(NotFoundException, match="Tenant test_tenant not found"):
        set_tenant_default_group_id("test_tenant", 123, "user_123")


@patch('backend.services.group_service.get_tenant_info')
@patch('backend.services.group_service.query_groups')
def test_set_tenant_default_group_id_group_not_found(mock_query_groups, mock_get_tenant_info):
    """Test setting tenant default group ID when group doesn't exist"""
    mock_get_tenant_info.return_value = {"tenant_id": "test_tenant"}
    mock_query_groups.return_value = None

    with pytest.raises(NotFoundException, match="Group 123 not found"):
        set_tenant_default_group_id("test_tenant", 123, "user_123")


@patch('backend.services.group_service.get_tenant_info')
@patch('backend.services.group_service.query_groups')
def test_set_tenant_default_group_id_wrong_tenant(mock_query_groups, mock_get_tenant_info):
    """Test setting tenant default group ID when group belongs to different tenant"""
    mock_get_tenant_info.return_value = {"tenant_id": "test_tenant"}
    mock_query_groups.return_value = {"tenant_id": "other_tenant"}

    with pytest.raises(ValidationError, match="Group 123 does not belong to tenant test_tenant"):
        set_tenant_default_group_id("test_tenant", 123, "user_123")


@patch('backend.services.group_service.get_tenant_info')
@patch('backend.services.group_service.query_groups')
@patch('backend.services.group_service.get_single_config_info')
@patch('backend.services.group_service.update_config_by_tenant_config_id')
def test_set_tenant_default_group_id_update_failure(mock_update_config, mock_get_config, mock_query_groups, mock_get_tenant_info):
    """Test setting tenant default group ID when update fails"""
    mock_get_tenant_info.return_value = {"tenant_id": "test_tenant"}
    mock_query_groups.return_value = {"tenant_id": "test_tenant"}
    mock_get_config.return_value = {"tenant_config_id": 456}
    mock_update_config.return_value = False

    result = set_tenant_default_group_id("test_tenant", 123, "user_123")

    assert result is False


@patch('backend.services.group_service.get_tenant_info')
@patch('backend.services.group_service.query_groups')
@patch('backend.services.group_service.get_single_config_info')
@patch('backend.services.group_service.insert_config')
def test_set_tenant_default_group_id_exception_handling(mock_insert_config, mock_get_config, mock_query_groups, mock_get_tenant_info):
    """Test exception handling in set_tenant_default_group_id"""
    mock_get_tenant_info.return_value = {"tenant_id": "test_tenant"}
    mock_query_groups.return_value = {"tenant_id": "test_tenant"}
    mock_get_config.return_value = None  # No existing config
    mock_insert_config.side_effect = Exception("Database connection failed")

    with pytest.raises(ValidationError, match="Failed to set default group: Database connection failed"):
        set_tenant_default_group_id("test_tenant", 123, "user_123")


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.query_groups')
@patch('backend.services.group_service.remove_user_from_group')
def test_remove_user_from_single_group_success(mock_remove_user, mock_query_groups, mock_get_user, mock_user_info, mock_group_info):
    """Test removing user from group successfully"""
    mock_get_user.return_value = mock_user_info
    mock_query_groups.return_value = mock_group_info
    mock_remove_user.return_value = True

    result = remove_user_from_single_group(
        group_id=123,
        user_id="member_user",
        current_user_id="test_user"
    )

    assert result is True
    mock_remove_user.assert_called_once_with(
        group_id=123,
        user_id="member_user",
        updated_by="test_user"
    )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
def test_remove_user_from_single_group_unauthorized_user_not_found(mock_get_user):
    """Test removing user from group when current user doesn't exist"""
    mock_get_user.return_value = None

    with pytest.raises(UnauthorizedError, match="User test_user not found"):
        remove_user_from_single_group(
            group_id=123,
            user_id="member_user",
            current_user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
def test_remove_user_from_single_group_unauthorized_role(mock_get_user, mock_user_info):
    """Test removing user from group with insufficient permissions"""
    mock_user_info["user_role"] = "USER"
    mock_get_user.return_value = mock_user_info

    with pytest.raises(UnauthorizedError, match="not authorized to manage group memberships"):
        remove_user_from_single_group(
            group_id=123,
            user_id="member_user",
            current_user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.query_groups')
def test_remove_user_from_single_group_group_not_found(mock_query_groups, mock_get_user, mock_user_info):
    """Test removing user from group when group doesn't exist"""
    mock_get_user.return_value = mock_user_info
    mock_query_groups.return_value = None

    with pytest.raises(NotFoundException, match="Group 123 not found"):
        remove_user_from_single_group(
            group_id=123,
            user_id="member_user",
            current_user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.query_groups')
@patch('backend.services.group_service.get_group_users')
@patch('backend.services.group_service.add_user_to_single_group')
@patch('backend.services.group_service.remove_user_from_single_group')
def test_update_group_members_success(
    mock_remove_user,
    mock_add_user,
    mock_get_members,
    mock_query_groups,
    mock_get_user,
    mock_user_info
):
    """Test successfully updating group members"""
    mock_get_user.return_value = mock_user_info
    mock_query_groups.return_value = {"group_id": 123, "group_name": "Test Group"}

    # Current members: user1, user2
    mock_get_members.return_value = [
        {"id": "user1", "username": "User 1"},
        {"id": "user2", "username": "User 2"}
    ]

    # Target members: user2, user3 (remove user1, add user3)
    mock_remove_user.return_value = True
    mock_add_user.return_value = {"group_user_id": 1, "group_id": 123, "user_id": "user3"}

    result = update_group_members(
        group_id=123,
        user_ids=["user2", "user3"],
        current_user_id="test_user"
    )

    assert result == {
        "group_id": 123,
        "added_count": 1,
        "removed_count": 1,
        "total_members": 2
    }

    # Should add user3
    mock_add_user.assert_called_once_with(123, "user3", "test_user")
    # Should remove user1
    mock_remove_user.assert_called_once_with(123, "user1", "test_user")


@patch('backend.services.group_service.get_user_tenant_by_user_id')
def test_update_group_members_unauthorized_user_not_found(mock_get_user):
    """Test updating group members when current user doesn't exist"""
    mock_get_user.return_value = None

    with pytest.raises(UnauthorizedError, match="User test_user not found"):
        update_group_members(
            group_id=123,
            user_ids=["user1", "user2"],
            current_user_id="test_user"
        )


@patch('backend.services.group_service.get_user_tenant_by_user_id')
@patch('backend.services.group_service.query_groups')
def test_update_group_members_group_not_found(mock_query_groups, mock_get_user, mock_user_info):
    """Test updating group members when group doesn't exist"""
    mock_get_user.return_value = mock_user_info
    mock_query_groups.return_value = None

    with pytest.raises(NotFoundException, match="Group 123 not found"):
        update_group_members(
            group_id=123,
            user_ids=["user1", "user2"],
            current_user_id="test_user"
        )
