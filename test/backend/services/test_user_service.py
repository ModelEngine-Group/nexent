# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""
Unit tests for management.services.permission.identity.users module
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from contracts.errors.exceptions import ForbiddenError, NotFoundException, RoleAssignmentConflict
from management.services.permission.identity import users as user_service
from management.services.permission.identity.users import (
    delete_user_and_cleanup,
    get_users,
    get_users_for_requester,
    update_user,
    update_user_for_requester,
)


@pytest.fixture(autouse=True)
def private_cleanup_collaborators(mocker):
    mocker.patch('management.services.permission.identity.users.enrich_cas_usernames')
    for name in ('remove_user_from_all_groups', 'soft_delete_all_configs_by_user_id',
                 'soft_delete_all_conversations_by_user', 'soft_delete_all_oauth_accounts_by_user_id',
                 'soft_delete_tokens_by_user'):
        mocker.patch('management.services.permission.identity.users.' + name, return_value=0)
    mocker.patch("management.services.permission.identity.users.prepare_private_cleanup", new_callable=AsyncMock)
    mocker.patch("management.services.permission.identity.users.execute_private_cleanup", new_callable=AsyncMock, return_value=None)


class TestUserAuthorization:
    """Test role and tenant enforcement for user management."""

    def test_admin_can_list_own_tenant(self, mocker):
        mock_get_users = mocker.patch(
            "management.services.permission.identity.users.get_users",
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
            "management.services.permission.identity.users.get_user_tenant_by_user_id",
            return_value={"tenant_id": "tenant-1", "user_role": "USER"},
        )
        mock_update = mocker.patch(
            "management.services.permission.identity.users.update_user",
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
        mocker.patch("management.services.permission.identity.users.get_user_tenant_by_user_id", return_value=target)

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
        mocker.patch("management.services.permission.identity.users.get_user_tenant_by_user_id", return_value=None)

        with pytest.raises(NotFoundException, match="not found"):
            await update_user_for_requester(
                "missing",
                {"role": "USER"},
                updated_by="su-1",
                requester_tenant_id="tenant-1",
                requester_role="SU",
            )


@pytest.fixture(autouse=True)
def reset_mocks(mocker):
    for name in ('get_users_by_tenant_id', 'get_user_tenant_by_user_id',
                 'soft_delete_user_tenant_by_user_id', 'remove_user_from_all_groups'):
        mocker.patch('management.services.permission.identity.users.' + name)
    mocker.patch('management.services.permission.identity.users.query_groups_by_users', return_value={})


class TestGetUsers:
    """Test cases for get_users function"""

    @pytest.mark.parametrize("page,page_size,expected_page,expected_page_size", [
        (1, 20, 1, 20),  # Default pagination
        (2, 10, 2, 10),  # Custom pagination
        (5, 50, 5, 50),  # Large page size
    ])
    def test_get_users_success_with_pagination(self, page, page_size, expected_page, expected_page_size):
        """Test successfully retrieving users with various pagination settings"""
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
    @pytest.mark.parametrize("values,legacy", [({"role": "DEV"}, True), ({"roles": ["DEV", "OPS"]}, False)])
    async def test_delegates_atomic_assignment(self, mocker, values, legacy):
        assigned = ("DEV",) if legacy else ("DEV", "OPS")
        replace = mocker.patch("management.services.permission.identity.users.replace_roles", return_value={
            "user_id": "target", "user_email": "user@example.com", "user_role": "DEV", "roles": assigned})
        result = await update_user("target", values, "actor")
        assert result["roles"] == list(assigned)
        assert result["role"] == "DEV"
        replace.assert_called_once_with("actor", "target", values.get("roles", values.get("role")), legacy=legacy)

    @pytest.mark.parametrize("values", [{}, {"username": "ignored"}])
    async def test_missing_role_is_rejected(self, values):
        with pytest.raises(ValueError, match="required"):
            await update_user("target", values, "actor")

    async def test_atomic_assignment_failure_propagates(self, mocker):
        mocker.patch("management.services.permission.identity.users.replace_roles", side_effect=RoleAssignmentConflict("last administrator"))
        with pytest.raises(RoleAssignmentConflict):
            await update_user("target", {"roles": ["USER"]}, "actor")


class TestDeleteUserAndCleanup:
    """Test cases for delete_user_and_cleanup function"""

    @pytest.mark.asyncio
    async def test_delete_user_and_cleanup_success(self, mocker):
        """Test successful complete user deletion and cleanup"""
        # Mock all the dependencies
        mock_soft_delete_tenant = mocker.patch(
            "management.services.permission.identity.users.soft_delete_user_tenant_by_user_id",
            return_value=True
        )
        mock_remove_groups = mocker.patch(
            "management.services.permission.identity.users.remove_user_from_all_groups",
            return_value=1
        )
        mock_soft_delete_configs = mocker.patch(
            "management.services.permission.identity.users.soft_delete_all_configs_by_user_id"
        )
        mock_soft_delete_convs = mocker.patch(
            "management.services.permission.identity.users.soft_delete_all_conversations_by_user",
            return_value=5
        )
        mock_soft_delete_oauth = mocker.patch(
            "management.services.permission.identity.users.soft_delete_all_oauth_accounts_by_user_id",
            return_value=0
        )
        mock_get_admin = mocker.patch(
            "management.services.permission.identity.users.delete_account"
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
        mock_get_admin.assert_called_once_with(user_id)

    @pytest.mark.asyncio
    async def test_delete_user_and_cleanup_best_effort(self, mocker):
        """Test that errors in individual steps don't fail the entire cleanup"""
        # Mock all dependencies with exceptions
        mocker.patch(
            "management.services.permission.identity.users.soft_delete_user_tenant_by_user_id",
            side_effect=Exception("tenant deletion failed")
        )
        mocker.patch(
            "management.services.permission.identity.users.remove_user_from_all_groups",
            side_effect=Exception("groups removal failed")
        )
        mocker.patch(
            "management.services.permission.identity.users.soft_delete_all_configs_by_user_id",
            side_effect=Exception("configs failed")
        )
        mocker.patch(
            "management.services.permission.identity.users.soft_delete_all_conversations_by_user",
            side_effect=Exception("convs failed")
        )
        mocker.patch(
            "management.services.permission.identity.users.soft_delete_all_oauth_accounts_by_user_id",
            side_effect=Exception("oauth failed")
        )
        mocker.patch(
            "management.services.permission.identity.users.delete_account",
            return_value=None
        )

        user_id = "user123"
        tenant_id = "tenant456"

        # A denied core deletion must never continue to credential/resource deletion.
        with pytest.raises(Exception, match="tenant deletion failed"):
            await delete_user_and_cleanup(user_id, tenant_id)



class TestCoverageGaps:
    """Cover authorization and cleanup fallback branches."""

    def test_superuser_can_list_any_tenant(self, mocker):
        mock_get_users = mocker.patch(
            "management.services.permission.identity.users.get_users",
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
            "management.services.permission.identity.users.get_users",
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
            "management.services.permission.identity.users.get_user_tenant_by_user_id",
            return_value={"tenant_id": "tenant-2", "user_role": "SU"},
        )
        mock_update = mocker.patch(
            "management.services.permission.identity.users.update_user",
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
    async def test_cleanup_disables_local_account(self, mocker):
        mocker.patch(
            "management.services.permission.identity.users.soft_delete_user_tenant_by_user_id",
            return_value=True,
        )
        mocker.patch("management.services.permission.identity.users.delete_account", return_value=None)

        await delete_user_and_cleanup("user-1", "tenant-1")

    @pytest.mark.asyncio
    async def test_cleanup_revokes_api_keys_and_disables_account_without_email(self, mocker):
        mocker.patch(
            "management.services.permission.identity.users.get_user_tenant_by_user_id",
            return_value={"user_id": "user-1", "user_email": None},
        )
        mocker.patch(
            "management.services.permission.identity.users.soft_delete_user_tenant_by_user_id",
            return_value=True,
        )
        mock_revoke = mocker.patch("management.services.permission.identity.users.soft_delete_tokens_by_user")
        mock_get_admin = mocker.patch("management.services.permission.identity.users.delete_account")

        await delete_user_and_cleanup("user-1", "tenant-1")

        mock_revoke.assert_called_once_with("user-1", "user-1")
        mock_get_admin.assert_called_once_with("user-1")


# Run tests when executed directly
if __name__ == "__main__":
    pytest.main([__file__])
