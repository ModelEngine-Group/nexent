"""
Unit tests for backend.services.user_service module
"""
import sys
import os

# Add backend path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

import pytest
from unittest.mock import patch, MagicMock

# Mock external dependencies before any imports
sys.modules['boto3'] = MagicMock()
sys.modules['psycopg2'] = MagicMock()
sys.modules['supabase'] = MagicMock()
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

# Import unit under test
from backend.services.user_service import get_users, update_user, delete_user_and_cleanup


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


class TestGetUsers:
    """Test cases for get_users function"""

    @pytest.mark.parametrize("page,page_size,expected_page,expected_page_size", [
        (1, 20, 1, 20),  # Default pagination
        (2, 10, 2, 10),  # Custom pagination
        (5, 50, 5, 50),  # Large page size
    ])
    def test_get_users_success(self, page, page_size, expected_page, expected_page_size):
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
            "total": 2,
            "total_pages": 1,
            "page": expected_page,
            "page_size": expected_page_size
        }

        # Execute
        result = get_users(tenant_id, page, page_size)

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
        assert result["total_pages"] == 1

        # Verify database call
        mock_db.assert_called_once_with(tenant_id, page, page_size, "created_at", "desc")

    def test_get_users_empty_result(self):
        """Test retrieving users when no users exist"""
        from backend.services import user_service
        mock_db = user_service.get_users_by_tenant_id
        mock_db.return_value = {
            "users": [],
            "total": 0,
            "total_pages": 0,
            "page": 1,
            "page_size": 20
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
            "total": 1,
            "total_pages": 1,
            "page": 1,
            "page_size": 20
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
            "total": 0,
            "total_pages": 0,
            "page": 1,
            "page_size": 20
        }

        result = get_users("tenant123")  # No page/page_size specified

        assert result["page"] == 1
        assert result["page_size"] == 20
        mock_db.assert_called_once_with("tenant123", 1, 20, 'created_at', 'desc')


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
        mock_build_config = mocker.patch(
            "backend.services.user_service.build_memory_config",
            return_value={"key": "value"}
        )
        mock_clear_memory = mocker.patch(
            "backend.services.user_service.clear_memory",
            new_callable=mocker.AsyncMock
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
        mock_build_config.assert_called_once_with(tenant_id)
        # clear_memory called for user and user_agent
        assert mock_clear_memory.call_count == 2
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
            "backend.services.user_service.build_memory_config",
            side_effect=Exception("config failed")
        )
        mocker.patch(
            "backend.services.user_service.clear_memory",
            new_callable=mocker.AsyncMock,
            side_effect=Exception("memory failed")
        )
        mocker.patch(
            "backend.services.user_service.get_supabase_admin_client",
            side_effect=Exception("admin failed")
        )

        user_id = "user123"
        tenant_id = "tenant456"

        # Should not raise, errors are logged and swallowed
        await delete_user_and_cleanup(user_id, tenant_id)


# Run tests when executed directly
if __name__ == "__main__":
    pytest.main([__file__])
