import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

consts_mock = MagicMock()
consts_mock.const = MagicMock()
consts_mock.const.DEFAULT_TENANT_ID = "default-tenant-id"
consts_mock.const.OAUTH_CALLBACK_BASE_URL = "http://localhost:3000"
sys.modules["consts"] = consts_mock
sys.modules["consts.const"] = consts_mock.const


class _OAuthProviderError(Exception):
    pass


class _OAuthLinkError(Exception):
    pass


exceptions_mock = MagicMock()
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

model_mock = MagicMock()


class _FakeOAuthProviderDefinition:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self):
        return f"FakeDef({self.name})"


model_mock.OAuthProviderDefinition = _FakeOAuthProviderDefinition
sys.modules["consts.model"] = model_mock

GITHUB_DEF = _FakeOAuthProviderDefinition(
    name="github",
    display_name="GitHub",
    icon="github",
    authorize_url="https://github.com/login/oauth/authorize",
    authorize_method="GET",
    authorize_params={"scope": "read:user user:email"},
    authorize_fragment="",
    authorize_param_map={
        "client_id": "client_id",
        "redirect_uri": "redirect_uri",
        "scope": "scope",
        "state": "state",
    },
    encode_redirect_uri=False,
    token_url="https://github.com/login/oauth/access_token",
    token_method="POST",
    token_params_map={
        "client_id": "client_id",
        "client_secret": "client_secret",
        "code": "code",
        "grant_type": "grant_type",
    },
    token_extra_params={},
    token_error_key="error",
    token_error_message_key="error_description",
    token_response_id_key=None,
    userinfo_url="https://api.github.com/user",
    userinfo_auth_scheme="Bearer",
    userinfo_params={},
    userinfo_field_map={
        "id": "id",
        "email": "email",
        "username": "login",
        "avatar_url": "avatar_url",
    },
    userinfo_needs_email_fetch=True,
    userinfo_email_url="https://api.github.com/user/emails",
    client_id_env="GITHUB_OAUTH_CLIENT_ID",
    client_secret_env="GITHUB_OAUTH_CLIENT_SECRET",
    enabled_check=None,
)

WECHAT_DEF = _FakeOAuthProviderDefinition(
    name="wechat",
    display_name="WeChat",
    icon="wechat",
    authorize_url="https://open.weixin.qq.com/connect/qrconnect",
    authorize_method="GET",
    authorize_params={"response_type": "code", "scope": "snsapi_login"},
    authorize_fragment="#wechat_redirect",
    authorize_param_map={
        "client_id": "appid",
        "redirect_uri": "redirect_uri",
        "scope": "scope",
        "state": "state",
    },
    encode_redirect_uri=True,
    token_url="https://api.weixin.qq.com/sns/oauth2/access_token",
    token_method="GET",
    token_params_map={
        "client_id": "appid",
        "client_secret": "secret",
        "code": "code",
        "grant_type": "grant_type",
    },
    token_extra_params={},
    token_error_key="errcode",
    token_error_message_key="errmsg",
    token_response_id_key="openid",
    userinfo_url="https://api.weixin.qq.com/sns/userinfo",
    userinfo_auth_scheme="",
    userinfo_params={"openid": "{openid}"},
    userinfo_field_map={
        "id": "openid",
        "email": "",
        "username": "nickname",
        "avatar_url": "headimgurl",
    },
    userinfo_needs_email_fetch=False,
    userinfo_email_url=None,
    client_id_env="WECHAT_OAUTH_APP_ID",
    client_secret_env="WECHAT_OAUTH_APP_SECRET",
    enabled_check="ENABLE_WECHAT_OAUTH",
)

oauth_providers_mock = MagicMock()
oauth_providers_mock.OAUTH_PROVIDER_REGISTRY = {
    "github": GITHUB_DEF,
    "wechat": WECHAT_DEF,
}


def _get_provider_definition(provider):
    if provider in oauth_providers_mock.OAUTH_PROVIDER_REGISTRY:
        return oauth_providers_mock.OAUTH_PROVIDER_REGISTRY[provider]
    raise KeyError(provider)


def _is_provider_enabled(definition):
    if definition.enabled_check:
        return os.getenv(definition.enabled_check, "false").lower() in (
            "true",
            "1",
            "yes",
        )
    client_id = os.getenv(definition.client_id_env, "")
    client_secret = os.getenv(definition.client_secret_env, "")
    return bool(client_id and client_secret)


def _get_all_provider_definitions():
    return dict(oauth_providers_mock.OAUTH_PROVIDER_REGISTRY)


oauth_providers_mock.get_provider_definition = _get_provider_definition
oauth_providers_mock.is_provider_enabled = _is_provider_enabled
oauth_providers_mock.get_all_provider_definitions = _get_all_provider_definitions
oauth_providers_mock.GITHUB_PROVIDER = GITHUB_DEF
oauth_providers_mock.WECHAT_PROVIDER = WECHAT_DEF
sys.modules["consts.oauth_providers"] = oauth_providers_mock

import services.oauth_service as oauth_service_module
from services.oauth_service import (
    create_or_update_oauth_account,
    ensure_user_tenant_exists,
    get_authorize_url,
    get_enabled_providers,
    get_supported_providers,
    list_linked_accounts,
    unlink_account,
)


class TestGetSupportedProviders(unittest.TestCase):
    def test_supported_providers_set(self):
        providers = get_supported_providers()
        self.assertEqual(providers, {"github", "wechat"})


class TestGetEnabledProviders(unittest.TestCase):
    def test_returns_github_when_configured(self):
        with patch.dict(
            os.environ,
            {"GITHUB_OAUTH_CLIENT_ID": "id", "GITHUB_OAUTH_CLIENT_SECRET": "secret"},
            clear=False,
        ):
            providers = get_enabled_providers()

        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["name"], "github")
        self.assertTrue(providers[0]["enabled"])

    def test_returns_empty_when_nothing_configured(self):
        env = {
            k: ""
            for k in [
                "GITHUB_OAUTH_CLIENT_ID",
                "GITHUB_OAUTH_CLIENT_SECRET",
                "WECHAT_OAUTH_APP_ID",
                "WECHAT_OAUTH_APP_SECRET",
            ]
        }
        env["ENABLE_WECHAT_OAUTH"] = "false"
        with patch.dict(os.environ, env, clear=False):
            providers = get_enabled_providers()

        self.assertEqual(len(providers), 0)

    def test_returns_both_when_all_configured(self):
        env = {
            "GITHUB_OAUTH_CLIENT_ID": "id",
            "GITHUB_OAUTH_CLIENT_SECRET": "secret",
            "ENABLE_WECHAT_OAUTH": "true",
            "WECHAT_OAUTH_APP_ID": "wx_id",
            "WECHAT_OAUTH_APP_SECRET": "wx_secret",
        }
        with patch.dict(os.environ, env, clear=False):
            providers = get_enabled_providers()

        self.assertEqual(len(providers), 2)
        names = [p["name"] for p in providers]
        self.assertIn("github", names)
        self.assertIn("wechat", names)


class TestGetAuthorizeUrl(unittest.TestCase):
    def test_returns_github_authorize_url(self):
        with patch.dict(
            os.environ,
            {
                "GITHUB_OAUTH_CLIENT_ID": "gh_test_id",
                "GITHUB_OAUTH_CLIENT_SECRET": "gh_test_secret",
            },
            clear=False,
        ):
            url = get_authorize_url("github")

        self.assertIn("github.com/login/oauth/authorize", url)
        self.assertIn("client_id=gh_test_id", url)
        self.assertIn("redirect_uri=", url)
        self.assertIn("state=github", url)

    def test_returns_wechat_authorize_url(self):
        env = {
            "WECHAT_OAUTH_APP_ID": "wx_test_id",
            "WECHAT_OAUTH_APP_SECRET": "wx_test_secret",
            "ENABLE_WECHAT_OAUTH": "true",
        }
        with patch.dict(os.environ, env, clear=False):
            url = get_authorize_url("wechat")

        self.assertIn("open.weixin.qq.com/connect/qrconnect", url)
        self.assertIn("appid=wx_test_id", url)
        self.assertTrue(url.endswith("#wechat_redirect"))

    def test_unsupported_provider_raises(self):
        with self.assertRaises(_OAuthProviderError):
            get_authorize_url("google")

    def test_unconfigured_provider_raises(self):
        with patch.dict(
            os.environ,
            {"GITHUB_OAUTH_CLIENT_ID": "", "GITHUB_OAUTH_CLIENT_SECRET": ""},
            clear=False,
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
        oauth_account_db_mock.get_oauth_account_by_provider.side_effect = [
            {"provider": "github", "provider_user_id": "12345", "user_id": "user-1"},
            {
                "provider": "github",
                "provider_user_id": "12345",
                "user_id": "user-1",
                "updated": True,
            },
        ]

        result = create_or_update_oauth_account(
            user_id="user-1",
            provider="github",
            provider_user_id="12345",
            username="new_name",
        )

        oauth_account_db_mock.update_oauth_account_tokens.assert_called_once()
        self.assertTrue(result.get("updated"))

    def test_rebinds_when_user_id_changed(self):
        oauth_account_db_mock.get_oauth_account_by_provider.side_effect = [
            {"provider": "github", "provider_user_id": "12345", "user_id": "old-user"},
            {"provider": "github", "provider_user_id": "12345", "user_id": "new-user"},
        ]

        result = create_or_update_oauth_account(
            user_id="new-user",
            provider="github",
            provider_user_id="12345",
            email="octo@github.com",
            username="octocat",
        )

        oauth_account_db_mock.rebind_oauth_account.assert_called_once_with(
            provider="github",
            provider_user_id="12345",
            new_user_id="new-user",
            provider_email="octo@github.com",
            provider_username="octocat",
            tenant_id="default-tenant-id",
        )
        oauth_account_db_mock.update_oauth_account_tokens.assert_not_called()
        self.assertEqual(result["user_id"], "new-user")


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
        oauth_account_db_mock.delete_oauth_account.return_value = True

        result = unlink_account("user-1", "github")

        self.assertTrue(result)

    def test_raises_when_last_account_no_password(self):
        oauth_account_db_mock.count_oauth_accounts_by_user_id.return_value = 1

        with self.assertRaises(_OAuthLinkError):
            unlink_account("user-1", "github")

    def test_allows_last_unlink_when_has_password(self):
        oauth_account_db_mock.count_oauth_accounts_by_user_id.return_value = 1
        oauth_account_db_mock.delete_oauth_account.return_value = True

        result = unlink_account("user-1", "github", has_password_auth=True)

        self.assertTrue(result)

    def test_raises_when_account_not_found(self):
        oauth_account_db_mock.count_oauth_accounts_by_user_id.return_value = 2
        oauth_account_db_mock.delete_oauth_account.return_value = False

        with self.assertRaises(_OAuthLinkError):
            unlink_account("user-1", "github")


if __name__ == "__main__":
    unittest.main()
