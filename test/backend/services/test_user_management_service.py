# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserved user metadata, permission and API-key unit contracts."""
import unittest
from unittest.mock import patch, MagicMock

from contracts.errors.exceptions import NoInviteCodeException, IncorrectInviteCodeException, UnauthorizedError
from contracts.constants.constants import ASSET_OWNER_ROLE, ASSET_OWNER_TENANT_ID
ASSET_OWNER_RESOURCES_ROUTE = "/asset-owner-resources"
from management.services.permission.identity.authentication import (
    get_provider_username, verify_invite_code, get_user_info,
    format_role_permissions, create_token, list_tokens_by_user, delete_token,
)

from gateway.authentication.auth import get_session_by_authorization

class TestGetProviderUsername(unittest.TestCase):
    """Test provider username lookup for linked OAuth accounts."""

    @patch('management.services.permission.identity.authentication.list_oauth_accounts_by_user_id')
    def test_returns_trimmed_username_for_matching_provider(self, mock_list_accounts):
        """Return the stored username after trimming surrounding whitespace."""
        mock_list_accounts.return_value = [
            {"provider": "github", "provider_username": "github-user"},
            {"provider": "cas", "provider_username": "  CAS User  "},
        ]

        result = get_provider_username("user123", "cas")

        self.assertEqual(result, "CAS User")
        mock_list_accounts.assert_called_once_with("user123")

    @patch('management.services.permission.identity.authentication.list_oauth_accounts_by_user_id')
    def test_returns_none_when_username_is_missing_or_provider_does_not_match(self, mock_list_accounts):
        """Return None when no linked account has a non-empty matching username."""
        mock_list_accounts.return_value = [
            {"provider": "github", "provider_username": "github-user"},
            {"provider": "cas", "provider_username": "   "},
        ]

        result = get_provider_username("user123", "cas")

        self.assertIsNone(result)

    @patch('management.services.permission.identity.authentication.list_oauth_accounts_by_user_id')
    def test_returns_none_when_accounts_cannot_be_loaded(self, mock_list_accounts):
        """Return None when the linked account lookup fails."""
        mock_list_accounts.side_effect = RuntimeError("database unavailable")

        result = get_provider_username("user123", "cas")

        self.assertIsNone(result)
        mock_list_accounts.assert_called_once_with("user123")


class TestVerifyInviteCode(unittest.IsolatedAsyncioTestCase):
    """Test verify_invite_code"""

    @patch('management.services.permission.identity.authentication.INVITE_CODE', 'correct-code')
    async def test_verify_invite_code_success(self):
        """Test successful invite code verification"""
        # Should not raise exception
        await verify_invite_code('correct-code')

    @patch('management.services.permission.identity.authentication.INVITE_CODE', None)
    async def test_verify_invite_code_no_system_code(self):
        """Test when system has no invite code configured"""
        with self.assertRaises(NoInviteCodeException) as context:
            await verify_invite_code('any-code')

        self.assertIn("The system has not configured the admin invite code", str(context.exception))

    @patch('management.services.permission.identity.authentication.INVITE_CODE', 'correct-code')
    async def test_verify_invite_code_no_user_code(self):
        """Test when user provides no invite code"""
        with self.assertRaises(IncorrectInviteCodeException) as context:
            await verify_invite_code(None)

        self.assertIn("Please enter the invite code", str(context.exception))

    @patch('management.services.permission.identity.authentication.INVITE_CODE', 'correct-code')
    async def test_verify_invite_code_wrong_code(self):
        """Test when user provides wrong invite code"""
        with self.assertRaises(IncorrectInviteCodeException) as context:
            await verify_invite_code('wrong-code')

        self.assertIn("Please enter the correct admin invite code", str(context.exception))


class TestGetSessionByAuthorization(unittest.IsolatedAsyncioTestCase):
    """Test get_session_by_authorization"""

    @patch('gateway.authentication.auth.validate_token')
    async def test_get_session_success(self, mock_validate_token):
        """Test successful session retrieval"""
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.email = "test@example.com"
        mock_user.user_metadata = {"role": "admin"}
        mock_validate_token.return_value = (True, mock_user)

        result = await get_session_by_authorization("Bearer token")

        expected = {
            "user": {
                "id": "user-123",
                "email": "test@example.com",
                "role": "admin"
            }
        }
        self.assertEqual(result, expected)

    @patch('gateway.authentication.auth.validate_token')
    async def test_get_session_default_role(self, mock_validate_token):
        """Test session retrieval with default role"""
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.email = "test@example.com"
        mock_user.user_metadata = None
        mock_validate_token.return_value = (True, mock_user)

        result = await get_session_by_authorization("Bearer token")

        self.assertEqual(result["user"]["role"], "user")

    @patch('gateway.authentication.auth.validate_token')
    async def test_get_session_invalid_token(self, mock_validate_token):
        """Test session retrieval with invalid token"""
        mock_validate_token.return_value = (False, None)

        with self.assertRaises(UnauthorizedError) as context:
            await get_session_by_authorization("Bearer invalid-token")

        self.assertEqual(str(context.exception), "Session is invalid or expired")


class TestFormatRolePermissions(unittest.TestCase):
    """Test format_role_permissions function"""

    def test_format_role_permissions_resource_only(self):
        """Test formatting with only RESOURCE permissions"""
        permissions = [
            {
                "permission_category": "RESOURCE",
                "permission_type": "agent",
                "permission_subtype": "create"
            },
            {
                "permission_category": "RESOURCE",
                "permission_type": "agent",
                "permission_subtype": "read"
            }
        ]

        result = format_role_permissions(permissions)

        assert result["permissions"] == ["agent:create", "agent:read"]
        assert result["accessibleRoutes"] == []

    def test_format_role_permissions_lowercases_mixed_case_types(self):
        """Test formatting normalizes uppercase permission types to lower-case"""
        permissions = [
            {
                "permission_category": "RESOURCE",
                "permission_type": "KB.CAPACITY",
                "permission_subtype": "READ"
            },
            {
                "permission_category": "RESOURCE",
                "permission_type": "KB",
                "permission_subtype": "CREATE"
            }
        ]

        result = format_role_permissions(permissions)

        assert result["permissions"] == ["kb.capacity:read", "kb:create"]
        assert result["accessibleRoutes"] == []

    def test_format_role_permissions_LEFT_NAV_MENU_only(self):
        """Test formatting with only LEFT_NAV_MENU permissions"""
        permissions = [
            {
                "permission_type": "LEFT_NAV_MENU",
                "permission_subtype": "chat"
            },
            {
                "permission_type": "LEFT_NAV_MENU",
                "permission_subtype": "agents"
            }
        ]

        result = format_role_permissions(permissions)

        assert result["permissions"] == []
        assert result["accessibleRoutes"] == ["chat", "agents"]

    def test_format_role_permissions_mixed(self):
        """Test formatting with mixed permission types"""
        permissions = [
            {
                "permission_category": "RESOURCE",
                "permission_type": "agent",
                "permission_subtype": "create"
            },
            {
                "permission_type": "LEFT_NAV_MENU",
                "permission_subtype": "chat"
            },
            {
                "permission_category": "OTHER",
                "permission_type": "SOME_TYPE",
                "permission_subtype": "ignored"
            }
        ]

        result = format_role_permissions(permissions)

        assert result["permissions"] == ["agent:create"]
        assert result["accessibleRoutes"] == ["chat"]

    def test_format_role_permissions_empty(self):
        """Test formatting with empty permissions list"""
        permissions = []

        result = format_role_permissions(permissions)

        assert result["permissions"] == []
        assert result["accessibleRoutes"] == []

    def test_format_role_permissions_missing_fields(self):
        """Test formatting with missing fields"""
        permissions = [
            {
                "permission_category": "RESOURCE",
                "permission_type": "agent"
                # missing permission_subtype
            },
            {
                "permission_type": "LEFT_NAV_MENU"
                # missing permission_subtype
            }
        ]

        result = format_role_permissions(permissions)

        assert result["permissions"] == []
        assert result["accessibleRoutes"] == []


class TestCreateToken(unittest.IsolatedAsyncioTestCase):
    """Tests for create_token function in user_management_service."""

    @patch('management.db.identity.token.soft_delete_tokens_by_user')
    @patch('management.db.client.get_db_session')
    @patch('management.services.permission.identity.authentication.create_token_record')
    @patch('management.services.permission.identity.authentication.generate_access_key')
    def test_create_token_success(
        self,
        mock_generate_access_key,
        mock_create_token_record,
        mock_get_db_session,
        mock_soft_delete_tokens,
    ):
        """Test successful token creation."""
        from management.services.permission.identity import authentication as ums

        mock_generate_access_key.return_value = "nexent-abc123"
        mock_create_token_record.return_value = {
            "token_id": 1,
            "access_key": "nexent-abc123",
            "user_id": "user-123"
        }

        # This module replaces database.token_db with a MagicMock, so the mask
        # helper is stubbed to assert the display value is derived, not guessed.
        with patch(
            'management.services.permission.identity.authentication.mask_access_key',
            side_effect=lambda key: f"masked:{key}",
        ):
            result = ums.create_token("user-123")

        assert result["token_id"] == 1
        assert result["access_key"] == "nexent-abc123"
        assert result["user_id"] == "user-123"
        # The masked value is what a client renders, so it ships next to the key.
        assert result["masked_access_key"] == "masked:nexent-abc123"
        assert result["can_copy"] is True
        mock_generate_access_key.assert_called_once()
        session = mock_get_db_session.return_value.__enter__.return_value
        mock_soft_delete_tokens.assert_called_once_with("user-123", "user-123", session)
        mock_create_token_record.assert_called_once_with(
            "nexent-abc123", "user-123", created_by="user-123", db_session=session
        )


class TestListTokensByUser(unittest.IsolatedAsyncioTestCase):
    """Tests for list_tokens_by_user function in user_management_service."""

    @patch('management.services.permission.identity.authentication.mask_access_key',
            side_effect=lambda key: f"masked:{key}")
    @patch('management.services.permission.identity.authentication.list_tokens_by_user_record')
    def test_list_tokens_by_user_success(self, mock_list_tokens, mock_mask_access_key):
        """Test successful token listing."""
        from management.services.permission.identity import authentication as ums

        mock_list_tokens.return_value = [
            {"token_id": 1, "access_key": "nexent-key1", "user_id": "user-123"},
            {"token_id": 2, "access_key": "nexent-key2", "user_id": "user-123"}
        ]

        result = ums.list_tokens_by_user("user-123", "USER")

        assert len(result) == 2
        # A role that may not copy sees the masked value in both fields, so a
        # client renders and (had it been allowed) copies the same safe value.
        assert result[0]["access_key"] == "masked:nexent-key1"
        assert [t["masked_access_key"] for t in result] == [
            "masked:nexent-key1",
            "masked:nexent-key2",
        ]
        assert result[0]["can_copy"] is False
        assert mock_mask_access_key.call_count == 2
        # The record layer masks by default, so the opt-out is part of the contract.
        mock_list_tokens.assert_called_once_with("user-123", mask=False)

    @patch('management.services.permission.identity.authentication.mask_access_key',
            side_effect=lambda key: f"masked:{key}")
    @patch('management.services.permission.identity.authentication.list_tokens_by_user_record')
    def test_list_tokens_by_user_admin_receives_complete_key(self, mock_list_tokens, mock_mask_access_key):
        from management.services.permission.identity import authentication as ums

        stored_key = "nexent-7593775c8d8798ae7565495b"
        mock_list_tokens.return_value = [
            {"token_id": 1, "access_key": stored_key, "user_id": "user-123"}
        ]

        result = ums.list_tokens_by_user("user-123", "ADMIN")

        assert result[0]["access_key"] == stored_key
        # Only the display value stays masked for a copy-capable role.
        assert result[0]["masked_access_key"] == f"masked:{stored_key}"
        assert result[0]["can_copy"] is True
        mock_mask_access_key.assert_called_once_with(stored_key)
        # Regression guard for the reported defect: administrators could copy a
        # masked key ("nexent****11bb") because the record layer was never asked
        # for the stored value.
        mock_list_tokens.assert_called_once_with("user-123", mask=False)

    @patch('management.services.permission.identity.authentication.mask_access_key',
            side_effect=lambda key: f"masked:{key}")
    @patch('management.services.permission.identity.authentication.list_tokens_by_user_record')
    def test_list_tokens_by_user_dev_masks_middle(self, mock_list_tokens, mock_mask_access_key):
        from management.services.permission.identity import authentication as ums

        mock_list_tokens.return_value = [
            {"token_id": 1, "access_key": "nexent-1234567890abcdef", "user_id": "user-123"}
        ]

        result = ums.list_tokens_by_user("user-123", "DEV")

        assert result[0]["access_key"] == "masked:nexent-1234567890abcdef"
        assert result[0]["masked_access_key"] == "masked:nexent-1234567890abcdef"
        assert result[0]["can_copy"] is False
        mock_mask_access_key.assert_called_once_with("nexent-1234567890abcdef")

    @patch('management.services.permission.identity.authentication.list_tokens_by_user_record')
    def test_list_tokens_by_user_empty(self, mock_list_tokens):
        """Test listing tokens when user has none."""
        from management.services.permission.identity import authentication as ums

        mock_list_tokens.return_value = []

        result = ums.list_tokens_by_user("user-no-tokens", "USER")

        assert result == []


class TestDeleteToken(unittest.IsolatedAsyncioTestCase):
    """Tests for delete_token function in user_management_service."""

    @patch('management.services.permission.identity.authentication.delete_token_record')
    def test_delete_token_success(self, mock_delete_token):
        """Test successful token deletion."""
        from management.services.permission.identity import authentication as ums

        mock_delete_token.return_value = True

        result = ums.delete_token(1, "user-123")

        assert result is True
        mock_delete_token.assert_called_once_with(1, "user-123")

    @patch('management.services.permission.identity.authentication.delete_token_record')
    def test_delete_token_not_found(self, mock_delete_token):
        """Test deleting non-existent token."""
        from management.services.permission.identity import authentication as ums

        mock_delete_token.return_value = False

        result = ums.delete_token(999, "user-123")

        assert result is False


class TestGetUserInfo(unittest.IsolatedAsyncioTestCase):
    @patch('management.services.permission.identity.authentication.as_dict')
    @patch('management.services.permission.identity.authentication.format_role_permissions')
    @patch('management.services.permission.identity.authentication.get_db_session')
    @patch('management.services.permission.identity.authentication.get_user_tenant_by_user_id')
    @patch('management.services.permission.identity.authentication.query_group_ids_by_user')
    async def test_get_user_info_success(self, mock_query_group_ids, mock_get_user_tenant, mock_get_db_session, mock_format_permissions, mock_as_dict):
        """Test getting user information successfully"""
        # Setup mocks
        mock_get_user_tenant.return_value = {
            "tenant_id": "test_tenant",
            "user_role": "ADMIN",
            "user_email": "test@example.com"
        }
        mock_query_group_ids.return_value = [1, 2, 3]

        # Mock database session and query
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [
            MagicMock(),  # First permission record
            MagicMock()   # Second permission record
        ]
        mock_get_db_session.return_value.__enter__.return_value = mock_session
        mock_get_db_session.return_value.__exit__.return_value = None

        # Mock as_dict calls for permission records
        mock_as_dict.side_effect = [
            {"permission_category": "RESOURCE", "permission_type": "agent", "permission_subtype": "create"},
            {"permission_type": "LEFT_NAV_MENU", "permission_subtype": "chat"}
        ]

        mock_format_permissions.return_value = {
            "permissions": ["agent:create"],
            "accessibleRoutes": ["chat"]
        }

        # Execute
        result = await get_user_info("test_user")

        # Assert
        assert result is not None
        assert result["user"]["user_id"] == "test_user"
        assert result["user"]["group_ids"] == [1, 2, 3]
        assert result["user"]["tenant_id"] == "test_tenant"
        assert result["user"]["user_email"] == "test@example.com"
        assert result["user"]["user_role"] == "ADMIN"
        assert result["user"]["permissions"] == ["agent:create"]
        assert result["user"]["accessibleRoutes"] == ["chat"]

        mock_get_user_tenant.assert_called_once_with("test_user")
        mock_query_group_ids.assert_called_once_with("test_user")
        mock_format_permissions.assert_called_once_with([
            {"permission_category": "RESOURCE", "permission_type": "agent",
                "permission_subtype": "create"},
            {"permission_type": "LEFT_NAV_MENU", "permission_subtype": "chat"}
        ])


    @patch('management.services.permission.identity.authentication.get_user_tenant_by_user_id')
    @patch('management.services.permission.identity.authentication.query_group_ids_by_user')
    async def test_get_user_info_exception_handling(self, mock_query_group_ids, mock_get_user_tenant):
        """Test get_user_info handles exceptions gracefully"""
        # Setup mocks to raise exception
        mock_get_user_tenant.side_effect = Exception("Database error")

        # Execute
        result = await get_user_info("test_user")

        # Assert
        assert result is None


class TestAssetOwnerUserManagementtest_format_role_permissions_excludes_asset_owner_route_when_disabled(unittest.IsolatedAsyncioTestCase):
    @patch("management.services.permission.asset_owner.ENABLE_ASSET_OWNER_ROLE", False)
    @patch("management.services.permission.identity.authentication.filter_accessible_routes_for_asset_owner_feature")
    def test_format_role_permissions_excludes_asset_owner_route_when_disabled(
        self, mock_filter_routes,
    ):
        import management.services.permission.asset_owner as aov

        mock_filter_routes.side_effect = aov.filter_accessible_routes_for_asset_owner_feature
        from management.services.permission.identity.authentication import format_role_permissions

        permissions = [
            {
                "permission_category": "MENU",
                "permission_type": "LEFT_NAV_MENU",
                "permission_subtype": ASSET_OWNER_RESOURCES_ROUTE,
            },
            {
                "permission_category": "MENU",
                "permission_type": "LEFT_NAV_MENU",
                "permission_subtype": "/home",
            },
        ]
        result = format_role_permissions(permissions)
        assert ASSET_OWNER_RESOURCES_ROUTE not in result["accessibleRoutes"]
        assert "/home" in result["accessibleRoutes"]


class TestAssetOwnerUserManagementtest_get_user_info_resolves_asset_owner_virtual_tenant(unittest.IsolatedAsyncioTestCase):
    @patch("management.services.permission.identity.authentication.query_group_ids_by_user")
    @patch("management.services.permission.identity.authentication.get_user_tenant_by_user_id")
    @patch("management.services.permission.identity.authentication.get_db_session")
    async def test_get_user_info_resolves_asset_owner_virtual_tenant(
        self,
        mock_get_db_session,
        mock_get_user_tenant,
        mock_query_groups,
    ):
        from management.services.permission.identity.authentication import get_user_info

        mock_get_user_tenant.return_value = {
            "user_id": "ao-user",
            "user_role": ASSET_OWNER_ROLE,
            "user_email": "owner@example.com",
            "tenant_id": "",
        }
        mock_query_groups.return_value = []

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.all.return_value = []
        mock_get_db_session.return_value.__enter__.return_value = mock_session

        result = await get_user_info("ao-user")

        assert result is not None
        assert result["user"]["tenant_id"] == ASSET_OWNER_TENANT_ID
