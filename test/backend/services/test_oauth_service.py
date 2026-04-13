import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

consts_mock = MagicMock()
consts_mock.const = MagicMock()
consts_mock.const.GITHUB_OAUTH_CLIENT_ID = "test_github_id"
consts_mock.const.GITHUB_OAUTH_CLIENT_SECRET = "test_github_secret"
consts_mock.const.ENABLE_WECHAT_OAUTH = False
consts_mock.const.WECHAT_OAUTH_APP_ID = ""
consts_mock.const.WECHAT_OAUTH_APP_SECRET = ""
consts_mock.const.OAUTH_CALLBACK_BASE_URL = "http://localhost:3000"
consts_mock.const.SUPABASE_URL = "http://localhost:8000"
consts_mock.const.DEFAULT_TENANT_ID = "default-tenant-id"
sys.modules["consts"] = consts_mock
sys.modules["consts.const"] = consts_mock.const

exceptions_mock = MagicMock()


class _OAuthProviderError(Exception):
    pass


class _OAuthLinkError(Exception):
    pass


exceptions_mock.OAuthProviderError = _OAuthProviderError
exceptions_mock.OAuthLinkError = _OAuthLinkError
sys.modules["consts.exceptions"] = exceptions_mock

oauth_account_db_mock = MagicMock()
sys.modules["database.oauth_account_db"] = oauth_account_db_mock

db_pkg = MagicMock()
db_pkg.oauth_account_db = oauth_account_db_mock
sys.modules["database"] = db_pkg

user_tenant_db_mock = MagicMock()
sys.modules["database.user_tenant_db"] = user_tenant_db_mock
db_pkg.user_tenant_db = user_tenant_db_mock

token_encryption_mock = MagicMock()
token_encryption_mock.encrypt_token.side_effect = lambda x: (
    f"encrypted_{x}" if x else None
)
sys.modules["utils.token_encryption"] = token_encryption_mock

utils_pkg = MagicMock()
utils_pkg.token_encryption = token_encryption_mock
sys.modules["utils"] = utils_pkg

import services.oauth_service as oauth_service_module
from services.oauth_service import (
    SUPPORTED_PROVIDERS,
    create_or_update_oauth_account,
    ensure_user_tenant_exists,
    get_authorize_url,
    get_enabled_providers,
    list_linked_accounts,
    unlink_account,
)

sys.modules["utils.token_encryption"] = token_encryption_mock
if "utils" not in sys.modules:
    sys.modules["utils"] = MagicMock()

from services.oauth_service import (
    SUPPORTED_PROVIDERS,
    create_or_update_oauth_account,
    ensure_user_tenant_exists,
    get_authorize_url,
    get_enabled_providers,
    list_linked_accounts,
    unlink_account,
)


class TestGetEnabledProviders(unittest.TestCase):
    def test_returns_github_when_configured(self):
        with (
            patch.object(oauth_service_module, "GITHUB_OAUTH_CLIENT_ID", "id"),
            patch.object(oauth_service_module, "GITHUB_OAUTH_CLIENT_SECRET", "secret"),
            patch.object(oauth_service_module, "ENABLE_WECHAT_OAUTH", False),
        ):
            providers = get_enabled_providers()

        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["name"], "github")
        self.assertTrue(providers[0]["enabled"])

    def test_returns_empty_when_nothing_configured(self):
        with (
            patch.object(oauth_service_module, "GITHUB_OAUTH_CLIENT_ID", ""),
            patch.object(oauth_service_module, "GITHUB_OAUTH_CLIENT_SECRET", ""),
            patch.object(oauth_service_module, "ENABLE_WECHAT_OAUTH", False),
        ):
            providers = get_enabled_providers()

        self.assertEqual(len(providers), 0)

    def test_returns_both_when_all_configured(self):
        with (
            patch.object(oauth_service_module, "GITHUB_OAUTH_CLIENT_ID", "id"),
            patch.object(oauth_service_module, "GITHUB_OAUTH_CLIENT_SECRET", "secret"),
            patch.object(oauth_service_module, "ENABLE_WECHAT_OAUTH", True),
            patch.object(oauth_service_module, "WECHAT_OAUTH_APP_ID", "wx_id"),
            patch.object(oauth_service_module, "WECHAT_OAUTH_APP_SECRET", "wx_secret"),
        ):
            providers = get_enabled_providers()

        self.assertEqual(len(providers), 2)
        names = [p["name"] for p in providers]
        self.assertIn("github", names)
        self.assertIn("wechat", names)


class TestGetAuthorizeUrl(unittest.TestCase):
    def test_returns_github_authorize_url(self):
        with (
            patch.object(oauth_service_module, "GITHUB_OAUTH_CLIENT_ID", "gh_test_id"),
            patch.object(
                oauth_service_module, "GITHUB_OAUTH_CLIENT_SECRET", "gh_test_secret"
            ),
            patch.object(
                oauth_service_module, "OAUTH_CALLBACK_BASE_URL", "http://localhost:3000"
            ),
        ):
            url = get_authorize_url("github")

        self.assertIn("github.com/login/oauth/authorize", url)
        self.assertIn("client_id=gh_test_id", url)
        self.assertIn("redirect_uri=", url)
        self.assertIn("state=github", url)

    def test_unsupported_provider_raises(self):
        with self.assertRaises(_OAuthProviderError):
            get_authorize_url("google")

    def test_unconfigured_provider_raises(self):
        with (
            patch.object(oauth_service_module, "GITHUB_OAUTH_CLIENT_ID", ""),
            patch.object(oauth_service_module, "GITHUB_OAUTH_CLIENT_SECRET", ""),
        ):
            with self.assertRaises(_OAuthProviderError):
                get_authorize_url("github")


class TestCreateOrUpdateOAuthAccount(unittest.TestCase):
    def test_creates_new_account_when_none_exists(self):
        oauth_account_db_mock.get_oauth_account_by_provider.return_value = None
        oauth_account_db_mock.insert_oauth_account.return_value = {
            "provider": "github",
            "provider_user_id": "12345",
        }

        result = create_or_update_oauth_account(
            user_id="user-1",
            provider="github",
            provider_user_id="12345",
            email="octo@github.com",
        )

        oauth_account_db_mock.insert_oauth_account.assert_called_once()
        self.assertEqual(result["provider"], "github")

    def test_updates_existing_account(self):
        oauth_account_db_mock.get_oauth_account_by_provider.return_value = {
            "provider": "github",
            "provider_user_id": "12345",
        }
        oauth_account_db_mock.get_oauth_account_by_provider.reset_mock()
        oauth_account_db_mock.get_oauth_account_by_provider.side_effect = [
            {"provider": "github", "provider_user_id": "12345"},
            {"provider": "github", "provider_user_id": "12345", "updated": True},
        ]

        result = create_or_update_oauth_account(
            user_id="user-1",
            provider="github",
            provider_user_id="12345",
            username="new_name",
        )

        oauth_account_db_mock.update_oauth_account_tokens.assert_called_once()
        self.assertTrue(result.get("updated"))


class TestEnsureUserTenantExists(unittest.TestCase):
    def test_returns_existing_tenant(self):
        user_tenant_db_mock.get_user_tenant_by_user_id.reset_mock()
        user_tenant_db_mock.insert_user_tenant.reset_mock()
        user_tenant_db_mock.get_user_tenant_by_user_id.side_effect = None
        user_tenant_db_mock.get_user_tenant_by_user_id.return_value = {
            "user_id": "user-1",
            "tenant_id": "t-1",
        }

        result = ensure_user_tenant_exists("user-1", "test@example.com")

        self.assertEqual(result["tenant_id"], "t-1")
        user_tenant_db_mock.insert_user_tenant.assert_not_called()

    def test_creates_tenant_when_missing(self):
        user_tenant_db_mock.get_user_tenant_by_user_id.reset_mock()
        user_tenant_db_mock.insert_user_tenant.reset_mock()
        user_tenant_db_mock.get_user_tenant_by_user_id.side_effect = [
            None,
            {"user_id": "user-1", "tenant_id": "default-tenant-id"},
        ]

        result = ensure_user_tenant_exists("user-1", "test@example.com")

        user_tenant_db_mock.insert_user_tenant.assert_called_once()
        self.assertEqual(result["tenant_id"], "default-tenant-id")

        user_tenant_db_mock.get_user_tenant_by_user_id.side_effect = None
        user_tenant_db_mock.get_user_tenant_by_user_id.return_value = {
            "user_id": "user-1",
            "tenant_id": "t-1",
        }


class TestListLinkedAccounts(unittest.TestCase):
    def test_transforms_db_results(self):
        oauth_account_db_mock.list_oauth_accounts_by_user_id.return_value = [
            {
                "provider": "github",
                "provider_username": "octocat",
                "provider_email": "octo@github.com",
                "provider_avatar_url": "https://avatar.url",
                "create_time": "2025-01-01T00:00:00",
            }
        ]

        result = list_linked_accounts("user-1")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["provider"], "github")
        self.assertEqual(result[0]["provider_username"], "octocat")
        self.assertIn("linked_at", result[0])

    def test_returns_empty_list(self):
        oauth_account_db_mock.list_oauth_accounts_by_user_id.return_value = []

        result = list_linked_accounts("user-1")

        self.assertEqual(len(result), 0)


class TestUnlinkAccount(unittest.TestCase):
    def test_success_with_multiple_accounts(self):
        oauth_account_db_mock.count_oauth_accounts_by_user_id.return_value = 2
        oauth_account_db_mock.soft_delete_oauth_account.return_value = True

        result = unlink_account("user-1", "github")

        self.assertTrue(result)

    def test_raises_when_last_account(self):
        oauth_account_db_mock.count_oauth_accounts_by_user_id.return_value = 1

        with self.assertRaises(_OAuthLinkError):
            unlink_account("user-1", "github")

    def test_raises_when_account_not_found(self):
        oauth_account_db_mock.count_oauth_accounts_by_user_id.return_value = 2
        oauth_account_db_mock.soft_delete_oauth_account.return_value = False

        with self.assertRaises(_OAuthLinkError):
            unlink_account("user-1", "github")


class TestSupportedProviders(unittest.TestCase):
    def test_supported_providers_set(self):
        self.assertEqual(SUPPORTED_PROVIDERS, {"github", "wechat"})


if __name__ == "__main__":
    unittest.main()
