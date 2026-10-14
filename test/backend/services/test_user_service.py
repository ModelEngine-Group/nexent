"""
Unit tests for backend.services.user_service module
"""
import sys
import os
import importlib.machinery
import types

# Add backend path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

# Mock external dependencies before any imports
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules['boto3'] = boto3_module
sys.modules['psycopg2'] = MagicMock()
sys.modules['nexent'] = MagicMock()
sys.modules['nexent.core'] = MagicMock()
sys.modules['nexent.core.agents'] = MagicMock()
sys.modules['nexent.core.agents.agent_model'] = MagicMock()
sys.modules['nexent.storage'] = MagicMock()
sys.modules['nexent.storage.storage_client_factory'] = MagicMock()
sys.modules['nexent.storage.minio_config'] = MagicMock()

# Mock for memory_service import used in delete_user_and_cleanup
nexent_memory_service = MagicMock()
sys.modules['nexent.memory'] = MagicMock()
sys.modules['nexent.memory.memory_service'] = nexent_memory_service

# Create mock ToolConfig class for imports
from pydantic import BaseModel
class MockToolConfig(BaseModel):
    name: str = ""
    description: str = ""
    parameters: dict = {}

sys.modules['nexent.core.agents.agent_model'].ToolConfig = MockToolConfig

# Patch storage client factory before imports
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=MagicMock()).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=MagicMock()).start()

# Mock database functions before importing the service
patch('database.user_tenant_db.get_users_by_tenant_id').start()
patch('database.user_tenant_db.update_user_tenant_role').start()
patch('database.user_tenant_db.get_user_tenant_by_user_id').start()
patch('database.user_tenant_db.soft_delete_user_tenant_by_user_id').start()
patch('database.group_db.remove_user_from_all_groups').start()
patch('database.group_db.query_groups_by_users', return_value={}).start()

# Import unit under test
from consts.exceptions import ForbiddenError, NotFoundException
from backend.services.user_service import (
    delete_user_and_cleanup,
    get_users,
    get_users_for_requester,
    update_user,
    update_user_for_requester,
)


class TestUserAuthorization:
    """Test role and tenant enforcement for user management."""

    def test_admin_can_list_own_tenant(self, mocker):
        mock_get_users = mocker.patch(
            "backend.services.user_service.get_users",
            return_value={"users": [], "total": 0},
        )

        result = get_users_for_requester(
            "tenant-1",
            requester_tenant_id="tenant-1",
            requester_role="ADMIN",
        )

        assert result == {"users": [], "total": 0}
        mock_get_users.assert_called_once_with("tenant-1", 1, 20, "created_at", "desc")

    @pytest.mark.parametrize(
        "role,target_tenant",
        [("ADMIN", "tenant-2"), ("DEV", "tenant-1"), ("USER", "tenant-1")],
    )
    def test_disallowed_user_listing_is_rejected(self, role, target_tenant):
        with pytest.raises(ForbiddenError, match="list users"):
            get_users_for_requester(
                target_tenant,
                requester_tenant_id="tenant-1",
                requester_role=role,
            )

    @pytest.mark.asyncio
    async def test_admin_can_update_non_su_in_own_tenant(self, mocker):
        mocker.patch(
            "backend.services.user_service.get_user_tenant_by_user_id",
            return_value={"tenant_id": "tenant-1", "user_role": "USER"},
        )
        mock_update = mocker.patch(
            "backend.services.user_service.update_user",
            return_value={"id": "user-2", "role": "DEV"},
        )

        result = await update_user_for_requester(
            "user-2",
            {"role": "DEV"},
            updated_by="admin-1",
            requester_tenant_id="tenant-1",
            requester_role="ADMIN",
        )

        assert result["role"] == "DEV"
        mock_update.assert_awaited_once_with("user-2", {"role": "DEV"}, "admin-1")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "target",
        [
            {"tenant_id": "tenant-2", "user_role": "USER"},
            {"tenant_id": "tenant-1", "user_role": "SU"},
        ],
    )
    async def test_admin_cannot_update_cross_tenant_or_su(self, mocker, target):
        mocker.patch("backend.services.user_service.get_user_tenant_by_user_id", return_value=target)

        with pytest.raises(ForbiddenError, match="update this user"):
            await update_user_for_requester(
                "user-2",
                {"role": "DEV"},
                updated_by="admin-1",
                requester_tenant_id="tenant-1",
                requester_role="ADMIN",
            )

    @pytest.mark.asyncio
    async def test_update_missing_user_returns_not_found(self, mocker):
        mocker.patch("backend.services.user_service.get_user_tenant_by_user_id", return_value=None)

        with pytest.raises(NotFoundException, match="not found"):
            await update_user_for_requester(
                "missing",
                {"role": "USER"},
                updated_by="su-1",
                requester_tenant_id="tenant-1",
                requester_role="SU",
            )


@pytest.fixture(autouse=True)
def reset_mocks():
    """Reset mock return values, call counts, and side effects for each test"""
    from backend.services import user_service

    # Reset all mocks and clear side effects
    user_service.get_users_by_tenant_id.reset_mock()
    user_service.get_users_by_tenant_id.side_effect = None
    user_service.update_user_tenant_role.reset_mock()
    user_service.update_user_tenant_role.side_effect = None
    user_service.get_user_tenant_by_user_id.reset_mock()
    user_service.get_user_tenant_by_user_id.side_effect = None
    user_service.soft_delete_user_tenant_by_user_id.reset_mock()
    user_service.soft_delete_user_tenant_by_user_id.side_effect = None
    user_service.remove_user_from_all_groups.reset_mock()
    user_service.remove_user_from_all_groups.side_effect = None
    user_service.query_groups_by_users.reset_mock()
    user_service.query_groups_by_users.side_effect = None
    user_service.query_groups_by_users.return_value = {}


class TestGetUsers:
    """Test cases for get_users function"""

    @pytest.mark.parametrize("page,page_size,expected_page,expected_page_size", [
        (1, 20, 1, 20),  # Default pagination
        (2, 10, 2, 10),  # Custom pagination
        (5, 50, 5, 50),  # Large page size
    ])
    def test_get_users_success_with_pagination(self, page, page_size, expected_page, expected_page_size):
        """Test successfully retrieving users with various pagination settings"""
        from backend.services import user_service
        mock_db = user_service.get_users_by_tenant_id
        tenant_id = "tenant123"

        mock_relationships = [
            {"user_id": "user1", "user_email": "user1@example.com", "user_role": "USER", "tenant_id": tenant_id},
            {"user_id": "user2", "user_email": "user2@example.com", "user_role": "ADMIN", "tenant_id": tenant_id}
        ]

        mock_db.return_value = {
            "users": mock_relationships,
            "total": 2
        }

        # Execute
        result = get_users(tenant_id, page, page_size, "created_at", "desc")

        # Assert
        assert len(result["users"]) == 2
        assert result["users"][0]["id"] == "user1"
        assert result["users"][0]["username"] == "user1@example.com"
        assert result["users"][0]["role"] == "USER"
        assert result["users"][1]["id"] == "user2"
        assert result["users"][1]["username"] == "user2@example.com"
        assert result["users"][1]["role"] == "ADMIN"
        assert result["total"] == 2
        assert result["page"] == expected_page
        assert result["page_size"] == expected_page_size
        assert result["total_pages"] == 1  # Calculated: ceil(2/page_size)

        # Verify database call
        mock_db.assert_called_once_with(tenant_id, page, page_size, "created_at", "desc")

    def test_get_users_success_without_pagination(self):
        """Test successfully retrieving users without pagination (returns all data)"""
        from backend.services import user_service
        mock_db = user_service.get_users_by_tenant_id
        tenant_id = "tenant123"

        mock_relationships = [
            {"user_id": "user1", "user_email": "user1@example.com", "user_role": "USER", "tenant_id": tenant_id},
            {"user_id": "user2", "user_email": "user2@example.com", "user_role": "ADMIN", "tenant_id": tenant_id},
            {"user_id": "user3", "user_email": "user3@example.com", "user_role": "USER", "tenant_id": tenant_id}
        ]

        mock_db.return_value = {
            "users": mock_relationships,
            "total": 3
        }

        # Execute
        result = get_users(tenant_id, None, None, "created_at", "desc")

        # Assert
        assert len(result["users"]) == 3
        assert result["total"] == 3
        assert "page" not in result
        assert "page_size" not in result
        assert "total_pages" not in result

        # Verify database call
        mock_db.assert_called_once_with(tenant_id, None, None, "created_at", "desc")

    def test_get_users_success_with_only_page(self):
        """Test retrieving users with only page parameter (no pagination info in result)"""
        from backend.services import user_service
        mock_db = user_service.get_users_by_tenant_id
        tenant_id = "tenant123"

        mock_relationships = [
            {"user_id": "user1", "user_email": "user1@example.com", "user_role": "USER", "tenant_id": tenant_id}
        ]

        mock_db.return_value = {
            "users": mock_relationships,
            "total": 1
        }

        result = get_users(tenant_id, 1, None, "created_at", "desc")

        assert len(result["users"]) == 1
        assert result["total"] == 1
        assert "page" not in result
        assert "page_size" not in result
        assert "total_pages" not in result

    def test_get_users_success_with_only_page_size(self):
        """Test retrieving users with only page_size parameter (no pagination info in result)"""
        from backend.services import user_service
        mock_db = user_service.get_users_by_tenant_id
        tenant_id = "tenant123"

        mock_relationships = [
            {"user_id": "user1", "user_email": "user1@example.com", "user_role": "USER", "tenant_id": tenant_id}
        ]

        mock_db.return_value = {
            "users": mock_relationships,
            "total": 1
        }

        result = get_users(tenant_id, None, 20, "created_at", "desc")

        assert len(result["users"]) == 1
        assert result["total"] == 1
        assert "page" not in result
        assert "page_size" not in result
        assert "total_pages" not in result

    def test_get_users_success_with_asc_sort(self):
        """Test successfully retrieving users with ascending sort order"""
        from backend.services import user_service
        mock_db = user_service.get_users_by_tenant_id
        tenant_id = "tenant123"

        mock_relationships = [
            {"user_id": "user1", "user_email": "user1@example.com", "user_role": "USER", "tenant_id": tenant_id}
        ]

        mock_db.return_value = {
            "users": mock_relationships,
            "total": 1
        }

        result = get_users(tenant_id, 1, 20, "created_at", "asc")

        assert len(result["users"]) == 1
        assert result["total"] == 1
        mock_db.assert_called_once_with(tenant_id, 1, 20, "created_at", "asc")

    def test_get_users_empty_result(self):
        """Test retrieving users when no users exist"""
        from backend.services import user_service
        mock_db = user_service.get_users_by_tenant_id
        mock_db.return_value = {
            "users": [],
            "total": 0
        }

        result = get_users("tenant123", 1, 20)

        assert result["users"] == []
        assert result["total"] == 0
        assert result["total_pages"] == 0

    def test_get_users_with_null_email(self):
        """Test retrieving users when user_email is None"""
        from backend.services import user_service
        mock_db = user_service.get_users_by_tenant_id
        mock_relationships = [
            {"user_id": "user1", "user_email": None, "user_role": "USER", "tenant_id": "tenant123"}
        ]

        mock_db.return_value = {
            "users": mock_relationships,
            "total": 1
        }

        result = get_users("tenant123", 1, 20)

        assert result["users"][0]["username"] is None
        assert result["total"] == 1

    def test_get_users_default_parameters(self):
        """Test get_users with default parameters"""
        from backend.services import user_service
        mock_db = user_service.get_users_by_tenant_id
        mock_db.return_value = {
            "users": [],
            "total": 0
        }

        result = get_users("tenant123")  # No page/page_size specified, uses defaults

        assert result["page"] == 1
        assert result["page_size"] == 20
        assert result["total_pages"] == 0
        mock_db.assert_called_once_with("tenant123", 1, 20, 'created_at', 'desc')

    def test_get_users_calculates_total_pages_correctly(self):
        """Test that total_pages is calculated correctly for pagination"""
        from backend.services import user_service
        mock_db = user_service.get_users_by_tenant_id
        mock_db.return_value = {
            "users": [
                {"user_id": "user1", "user_email": "user1@example.com", "user_role": "USER", "tenant_id": "tenant123"}
            ],
            "total": 25
        }

        result = get_users("tenant123", 2, 10)

        assert result["total"] == 25
        assert result["total_pages"] == 3  # Calculated: ceil(25/10) = 3

    def test_get_users_includes_group_names(self):
        """Test that get_users returns group_names populated from batch query"""
        from backend.services import user_service
        mock_db = user_service.get_users_by_tenant_id
        mock_group_db = user_service.query_groups_by_users
        tenant_id = "tenant123"

        mock_relationships = [
            {"user_id": "user1", "user_email": "user1@example.com", "user_role": "USER", "tenant_id": tenant_id},
            {"user_id": "user2", "user_email": "user2@example.com", "user_role": "ADMIN", "tenant_id": tenant_id}
        ]
        mock_db.return_value = {"users": mock_relationships, "total": 2}
        mock_group_db.return_value = {
            "user1": ["engineering", "qa"],
            "user2": ["engineering"],
        }

        result = get_users(tenant_id, 1, 20)

        assert result["users"][0]["group_names"] == ["engineering", "qa"]
        assert result["users"][1]["group_names"] == ["engineering"]
        mock_group_db.assert_called_once_with(["user1", "user2"])

    def test_get_users_with_no_groups_returns_empty_list(self):
        """Test that users with no group memberships get empty group_names list"""
        from backend.services import user_service
        mock_db = user_service.get_users_by_tenant_id
        mock_group_db = user_service.query_groups_by_users
        tenant_id = "tenant123"

        mock_relationships = [
            {"user_id": "user1", "user_email": "user1@example.com", "user_role": "USER", "tenant_id": tenant_id}
        ]
        mock_db.return_value = {"users": mock_relationships, "total": 1}
        mock_group_db.return_value = {}

        result = get_users(tenant_id, 1, 20)

        assert result["users"][0]["group_names"] == []

    def test_get_users_batch_query_passes_user_ids(self):
        """Test that query_groups_by_users is called with the tenant's user IDs"""
        from backend.services import user_service
        mock_db = user_service.get_users_by_tenant_id
        mock_group_db = user_service.query_groups_by_users

        mock_relationships = [
            {"user_id": "user_a", "user_email": "a@test.com", "user_role": "USER", "tenant_id": "t1"},
            {"user_id": "user_b", "user_email": "b@test.com", "user_role": "ADMIN", "tenant_id": "t1"},
        ]
        mock_db.return_value = {"users": mock_relationships, "total": 2}
        mock_group_db.return_value = {}

        get_users("t1", 1, 20)

        mock_group_db.assert_called_once_with(["user_a", "user_b"])

    def test_get_users_with_filters_passes_filter_arguments(self):
        """Test that resource filters are forwarded to the database layer."""
        from backend.services import user_service

        user_service.get_users_by_tenant_id.return_value = {
            "users": [], "total": 0
        }

        result = get_users(
            "tenant123", 1, 20, "created_at", "desc",
            search="alice", roles=["ADMIN"], group_ids=[7]
        )

        assert result["users"] == []
        user_service.get_users_by_tenant_id.assert_called_once_with(
            tenant_id="tenant123", page=1, page_size=20,
            sort_by="created_at", sort_order="desc", search="alice",
            roles=["ADMIN"], group_ids=[7]
        )


@pytest.mark.asyncio
class TestUpdateUser:
    """Test cases for update_user function"""

    @pytest.mark.parametrize("role", ["ADMIN", "DEV", "USER"])
    async def test_update_user_success_valid_roles(self, role):
        """Test successfully updating user with valid roles"""
        from backend.services import user_service
        mock_update_role = user_service.update_user_tenant_role
        mock_get_user = user_service.get_user_tenant_by_user_id

        user_id = "user123"
        updated_by = "updater456"

        mock_update_role.return_value = True
        mock_get_user.return_value = {
            "user_id": user_id,
            "user_email": "user@example.com",
            "user_role": role,
            "tenant_id": "tenant123"
        }

        # Execute
        result = await update_user(user_id, {"role": role}, updated_by)

        # Assert
        assert result["id"] == user_id
        assert result["username"] == "user@example.com"
        assert result["role"] == role

        # Verify database calls
        mock_update_role.assert_called_once_with(user_id, role, updated_by)
        mock_get_user.assert_called_once_with(user_id)

    async def test_update_user_success_with_null_email(self):
        """Test successfully updating user when user_email is None"""
        from backend.services import user_service
        mock_update_role = user_service.update_user_tenant_role
        mock_get_user = user_service.get_user_tenant_by_user_id

        user_id = "user123"
        update_data = {"role": "USER"}
        updated_by = "updater456"

        mock_update_role.return_value = True
        mock_get_user.return_value = {
            "user_id": user_id,
            "user_email": None,
            "user_role": "USER",
            "tenant_id": "tenant123"
        }

        result = await update_user(user_id, update_data, updated_by)

        assert result["username"] is None
        assert result["role"] == "USER"

    async def test_update_user_invalid_role(self):
        """Test updating user with invalid role"""
        from backend.services import user_service
        mock_update_role = user_service.update_user_tenant_role

        user_id = "user123"
        update_data = {"role": "INVALID_ROLE"}
        updated_by = "updater456"

        # Execute & Assert
        with pytest.raises(ValueError, match="Invalid role. Must be one of: ADMIN, DEV, USER"):
            await update_user(user_id, update_data, updated_by)

        # Verify database function was not called
        mock_update_role.assert_not_called()

    async def test_update_user_update_failed(self):
        """Test updating user when database update fails"""
        from backend.services import user_service
        mock_update_role = user_service.update_user_tenant_role
        mock_get_user = user_service.get_user_tenant_by_user_id

        user_id = "user123"
        update_data = {"role": "ADMIN"}
        updated_by = "updater456"

        mock_update_role.return_value = False

        # Execute & Assert
        with pytest.raises(ValueError, match=f"User {user_id} not found or update failed"):
            await update_user(user_id, update_data, updated_by)

        # Verify calls
        mock_update_role.assert_called_once_with(user_id, "ADMIN", updated_by)
        mock_get_user.assert_not_called()

    async def test_update_user_not_found_after_update(self):
        """Test updating user when user not found after update"""
        from backend.services import user_service
        mock_update_role = user_service.update_user_tenant_role
        mock_get_user = user_service.get_user_tenant_by_user_id

        user_id = "user123"
        update_data = {"role": "ADMIN"}
        updated_by = "updater456"

        mock_update_role.return_value = True
        mock_get_user.return_value = None

        # Execute & Assert
        with pytest.raises(ValueError, match=f"User {user_id} not found after update"):
            await update_user(user_id, update_data, updated_by)

        # Verify calls
        mock_update_role.assert_called_once_with(user_id, "ADMIN", updated_by)
        mock_get_user.assert_called_once_with(user_id)

    async def test_update_user_empty_update_data(self):
        """Test updating user with empty update data"""
        from backend.services import user_service
        mock_update_role = user_service.update_user_tenant_role
        mock_get_user = user_service.get_user_tenant_by_user_id

        user_id = "user123"
        update_data = {}
        updated_by = "updater456"

        mock_update_role.return_value = True
        mock_get_user.return_value = {
            "user_id": user_id,
            "user_email": "user@example.com",
            "user_role": "USER",
            "tenant_id": "tenant123"
        }

        result = await update_user(user_id, update_data, updated_by)

        # Assert role remains unchanged
        assert result["role"] == "USER"

        # Verify database called with None for role
        mock_update_role.assert_called_once_with(user_id, None, updated_by)

    async def test_update_user_unexpected_error(self):
        """Test updating user with unexpected error"""
        from backend.services import user_service
        mock_update_role = user_service.update_user_tenant_role

        user_id = "user123"
        update_data = {"role": "ADMIN"}
        updated_by = "updater456"

        mock_update_role.side_effect = Exception("Database connection failed")

        # Execute & Assert
        with pytest.raises(Exception, match="Database connection failed"):
            await update_user(user_id, update_data, updated_by)


class TestDataValidation:
    """Test data validation and edge cases"""

    @pytest.mark.asyncio
    async def test_update_user_role_validation_all_valid_roles(self):
        """Test role validation with all valid roles"""
        from backend.services import user_service
        valid_roles = ["ADMIN", "DEV", "USER"]

        for role in valid_roles:
            # Reset mocks for each iteration
            mock_update_role = user_service.update_user_tenant_role
            mock_get_user = user_service.get_user_tenant_by_user_id

            # Reset return values for each iteration
            mock_update_role.reset_mock()
            mock_get_user.reset_mock()

            mock_update_role.return_value = True
            mock_get_user.return_value = {
                "user_id": "user123",
                "user_email": "user@example.com",
                "user_role": role,
                "tenant_id": "tenant123"
            }

            result = await update_user("user123", {"role": role}, "updater456")

            assert result["role"] == role
            mock_update_role.assert_called_once_with("user123", role, "updater456")

    @pytest.mark.asyncio
    async def test_update_user_without_role_key(self):
        """Test updating user without role key in update_data"""
        from backend.services import user_service
        mock_update_role = user_service.update_user_tenant_role
        mock_get_user = user_service.get_user_tenant_by_user_id

        user_id = "user123"
        update_data = {"some_other_field": "value"}
        updated_by = "updater456"

        mock_update_role.return_value = True
        mock_get_user.return_value = {
            "user_id": user_id,
            "user_email": "user@example.com",
            "user_role": "USER",
            "tenant_id": "tenant123"
        }

        result = await update_user(user_id, update_data, updated_by)

        # Assert - should call with None role (no role update)
        mock_update_role.assert_called_once_with(user_id, None, updated_by)
        assert result["role"] == "USER"  # Existing role preserved

    @pytest.mark.parametrize("invalid_role", ["invalid", "SUPER_ADMIN", "GUEST", "", None])
    async def test_update_user_invalid_role_various_cases(self, invalid_role):
        """Test updating user with various invalid roles"""
        from backend.services import user_service
        mock_update_role = user_service.update_user_tenant_role

        user_id = "user123"
        update_data = {"role": invalid_role}
        updated_by = "updater456"

        # Execute & Assert
        with pytest.raises(ValueError, match="Invalid role. Must be one of: ADMIN, DEV, USER"):
            await update_user(user_id, update_data, updated_by)

        # Verify database function was not called
        mock_update_role.assert_not_called()


class TestDeleteUserAndCleanup:
    """Test cases for delete_user_and_cleanup function"""

    @pytest.mark.asyncio
    async def test_delete_user_and_cleanup_success(self, mocker):
        """Test successful complete user deletion and cleanup"""
        # Mock all the dependencies
        mock_soft_delete_tenant = mocker.patch(
            "backend.services.user_service.soft_delete_user_tenant_by_user_id",
            return_value=True
        )
        mock_remove_groups = mocker.patch(
            "backend.services.user_service.remove_user_from_all_groups",
            return_value=1
        )
        mock_soft_delete_configs = mocker.patch(
            "backend.services.user_service.soft_delete_all_configs_by_user_id"
        )
        mock_soft_delete_convs = mocker.patch(
            "backend.services.user_service.soft_delete_all_conversations_by_user",
            return_value=5
        )
        mock_soft_delete_oauth = mocker.patch(
            "backend.services.user_service.soft_delete_all_oauth_accounts_by_user_id",
            return_value=0
        )
        mock_get_admin = mocker.patch(
            "backend.services.user_service.get_supabase_admin_client"
        )

        # Setup mock admin client
        mock_admin = MagicMock()
        mock_admin.auth.admin.delete_user = MagicMock()
        mock_get_admin.return_value = mock_admin

        user_id = "user123"
        tenant_id = "tenant456"

        await delete_user_and_cleanup(user_id, tenant_id)

        # Verify all steps were called
        mock_soft_delete_tenant.assert_called_once_with(user_id, user_id)
        mock_remove_groups.assert_called_once_with(user_id, user_id)
        mock_soft_delete_configs.assert_called_once_with(user_id, actor=user_id)
        mock_soft_delete_convs.assert_called_once_with(user_id)
        mock_soft_delete_oauth.assert_called_once_with(user_id, user_id)
        mock_get_admin.assert_called_once()
        mock_admin.auth.admin.delete_user.assert_called_once_with(user_id)

    @pytest.mark.asyncio
    async def test_delete_user_and_cleanup_best_effort(self, mocker):
        """Test that errors in individual steps don't fail the entire cleanup"""
        # Mock all dependencies with exceptions
        mocker.patch(
            "backend.services.user_service.soft_delete_user_tenant_by_user_id",
            side_effect=Exception("tenant deletion failed")
        )
        mocker.patch(
            "backend.services.user_service.remove_user_from_all_groups",
            side_effect=Exception("groups removal failed")
        )
        mocker.patch(
            "backend.services.user_service.soft_delete_all_configs_by_user_id",
            side_effect=Exception("configs failed")
        )
        mocker.patch(
            "backend.services.user_service.soft_delete_all_conversations_by_user",
            side_effect=Exception("convs failed")
        )
        mocker.patch(
            "backend.services.user_service.soft_delete_all_oauth_accounts_by_user_id",
            side_effect=Exception("oauth failed")
        )
        mocker.patch(
            "backend.services.user_service.get_supabase_admin_client",
            side_effect=Exception("admin failed")
        )

        user_id = "user123"
        tenant_id = "tenant456"

        # Should not raise, errors are logged and swallowed
        await delete_user_and_cleanup(user_id, tenant_id)

    def _mock_base_cleanup(self, mocker):
        mocker.patch(
            "backend.services.user_service.soft_delete_user_tenant_by_user_id",
            return_value=True,
        )
        mocker.patch(
            "backend.services.user_service.remove_user_from_all_groups",
            return_value=1,
        )
        mocker.patch(
            "backend.services.user_service.soft_delete_all_configs_by_user_id"
        )
        mocker.patch(
            "backend.services.user_service.soft_delete_all_conversations_by_user",
            return_value=5,
        )
        mocker.patch(
            "backend.services.user_service.soft_delete_all_oauth_accounts_by_user_id",
            return_value=0,
        )
        mock_get_admin = mocker.patch(
            "backend.services.user_service.get_supabase_admin_client"
        )
        mock_admin = MagicMock()
        mock_admin.auth.admin.delete_user = MagicMock()
        mock_get_admin.return_value = mock_admin

    def _install_fake_vdb(self, mocker, delete_side_effect=None):
        fake_vdb = types.ModuleType("management.services.knowledge_base.service")
        fake_vdb.get_vector_db_core = MagicMock(return_value="vdb-core")
        fake_vdb.ElasticSearchService = MagicMock()
        fake_vdb.ElasticSearchService.full_delete_knowledge_base = AsyncMock(
            side_effect=delete_side_effect
        )
        mocker.patch.dict(
            sys.modules, {"management.services.knowledge_base.service": fake_vdb}
        )
        return fake_vdb

    @pytest.mark.asyncio
    async def test_delete_user_and_cleanup_success_with_private_kb_cleanup(
        self, mocker
    ):
        self._mock_base_cleanup(mocker)
        mocker.patch(
            "backend.services.user_service.get_private_knowledge_info_by_creator",
            return_value=[
                {"knowledge_id": 1, "index_name": "private-kb-1"},
                {"knowledge_id": 2, "index_name": "private-kb-2"},
            ],
        )
        fake_vdb = self._install_fake_vdb(mocker)

        result = await delete_user_and_cleanup("user123", "tenant456")

        assert result == {"total": 2, "succeeded": 2, "failed": 0}
        fake_vdb.get_vector_db_core.assert_called_once_with()
        assert (
            fake_vdb.ElasticSearchService.full_delete_knowledge_base.await_count
            == 2
        )
        fake_vdb.ElasticSearchService.full_delete_knowledge_base.assert_any_await(
            "private-kb-1", "vdb-core", "user123"
        )
        fake_vdb.ElasticSearchService.full_delete_knowledge_base.assert_any_await(
            "private-kb-2", "vdb-core", "user123"
        )

    @pytest.mark.asyncio
    async def test_delete_user_and_cleanup_reports_partial_cleanup_failures(
        self, mocker
    ):
        self._mock_base_cleanup(mocker)
        mocker.patch(
            "backend.services.user_service.get_private_knowledge_info_by_creator",
            return_value=[
                {"knowledge_id": 1, "index_name": "private-kb-1"},
                {"knowledge_id": 2, "index_name": "private-kb-2"},
            ],
        )
        fake_vdb = self._install_fake_vdb(
            mocker, delete_side_effect=[None, Exception("delete failed")]
        )

        result = await delete_user_and_cleanup("user123", "tenant456")

        assert result == {"total": 2, "succeeded": 1, "failed": 1}
        assert (
            fake_vdb.ElasticSearchService.full_delete_knowledge_base.await_count
            == 2
        )

    @pytest.mark.asyncio
    async def test_delete_user_and_cleanup_skips_private_kb_cleanup_when_none(
        self, mocker
    ):
        self._mock_base_cleanup(mocker)
        mocker.patch(
            "backend.services.user_service.get_private_knowledge_info_by_creator",
            return_value=[],
        )
        fake_vdb = self._install_fake_vdb(mocker)

        result = await delete_user_and_cleanup("user123", "tenant456")

        assert result is None
        fake_vdb.get_vector_db_core.assert_not_called()
        fake_vdb.ElasticSearchService.full_delete_knowledge_base.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_user_and_cleanup_counts_missing_index_name_as_failed(
        self, mocker
    ):
        self._mock_base_cleanup(mocker)
        mocker.patch(
            "backend.services.user_service.get_private_knowledge_info_by_creator",
            return_value=[
                {"knowledge_id": 1, "index_name": None},
                {"knowledge_id": 2, "index_name": "private-kb-2"},
            ],
        )
        fake_vdb = self._install_fake_vdb(mocker)

        result = await delete_user_and_cleanup("user123", "tenant456")

        assert result == {"total": 2, "succeeded": 1, "failed": 1}
        fake_vdb.ElasticSearchService.full_delete_knowledge_base.assert_awaited_once_with(
            "private-kb-2", "vdb-core", "user123"
        )

    @pytest.mark.asyncio
    async def test_delete_user_and_cleanup_private_kb_query_failure_is_swallowed(
        self, mocker
    ):
        self._mock_base_cleanup(mocker)
        mocker.patch(
            "backend.services.user_service.get_private_knowledge_info_by_creator",
            side_effect=Exception("query failed"),
        )

        result = await delete_user_and_cleanup("user123", "tenant456")

        assert result is None


class TestCoverageGaps:
    """Cover authorization and cleanup fallback branches."""

    def test_superuser_can_list_any_tenant(self, mocker):
        mock_get_users = mocker.patch(
            "backend.services.user_service.get_users",
            return_value={"users": [], "total": 0},
        )

        assert get_users_for_requester(
            "tenant-2",
            requester_tenant_id="tenant-1",
            requester_role="SU",
        ) == {"users": [], "total": 0}
        mock_get_users.assert_called_once_with("tenant-2", 1, 20, "created_at", "desc")

    def test_requester_forwards_resource_filters(self, mocker):
        """Test that authorized requests with filters use the filtered call path."""
        mock_get_users = mocker.patch(
            "backend.services.user_service.get_users",
            return_value={"users": [], "total": 0},
        )

        result = get_users_for_requester(
            "tenant-1", 1, 20, "created_at", "desc",
            search="alice", requester_tenant_id="tenant-1", requester_role="ADMIN",
        )

        assert result == {"users": [], "total": 0}
        mock_get_users.assert_called_once_with(
            "tenant-1", 1, 20, "created_at", "desc", "alice", None, None
        )

    @pytest.mark.asyncio
    async def test_superuser_can_update_any_user(self, mocker):
        mocker.patch(
            "backend.services.user_service.get_user_tenant_by_user_id",
            return_value={"tenant_id": "tenant-2", "user_role": "SU"},
        )
        mock_update = mocker.patch(
            "backend.services.user_service.update_user",
            return_value={"id": "user-2", "role": "USER"},
        )

        result = await update_user_for_requester(
            "user-2",
            {"role": "USER"},
            updated_by="su-1",
            requester_tenant_id="tenant-1",
            requester_role="SU",
        )

        assert result["id"] == "user-2"
        mock_update.assert_awaited_once_with("user-2", {"role": "USER"}, "su-1")

    @pytest.mark.asyncio
    async def test_cleanup_handles_missing_supabase_admin_client(self, mocker):
        mocker.patch(
            "backend.services.user_service.soft_delete_user_tenant_by_user_id",
            return_value=True,
        )
        mocker.patch("backend.services.user_service.get_supabase_admin_client", return_value=None)

        await delete_user_and_cleanup("user-1", "tenant-1")

    @pytest.mark.asyncio
    async def test_cleanup_revokes_api_keys_and_skips_supabase_without_email(self, mocker):
        mocker.patch(
            "backend.services.user_service.get_user_tenant_by_user_id",
            return_value={"user_id": "user-1", "user_email": None},
        )
        mocker.patch(
            "backend.services.user_service.soft_delete_user_tenant_by_user_id",
            return_value=True,
        )
        mock_revoke = mocker.patch("database.token_db.soft_delete_tokens_by_user")
        mock_get_admin = mocker.patch("backend.services.user_service.get_supabase_admin_client")

        await delete_user_and_cleanup("user-1", "tenant-1")

        mock_revoke.assert_called_once_with("user-1", "user-1")
        mock_get_admin.assert_not_called()


# Run tests when executed directly
if __name__ == "__main__":
    pytest.main([__file__])
