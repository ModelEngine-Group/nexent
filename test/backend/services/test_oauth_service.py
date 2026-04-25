import sys
import os
import unittest
from unittest.mock import MagicMock, patch

test_dir = os.path.dirname(__file__)
backend_dir = os.path.abspath(os.path.join(test_dir, "../../../backend"))
sys.path.insert(0, backend_dir)

consts_mock = MagicMock()
consts_mock.const = MagicMock()
consts_mock.const.DEFAULT_TENANT_ID = "default-tenant-id"
consts_mock.const.OAUTH_CALLBACK_BASE_URL = "http://localhost:3000"
consts_mock.const.OAUTH_SSL_VERIFY = True
consts_mock.const.OAUTH_CA_BUNDLE = ""
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
        "redirect_uri": "redirect_uri",
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
    },
    userinfo_needs_email_fetch=False,
    userinfo_email_url=None,
    client_id_env="WECHAT_OAUTH_APP_ID",
    client_secret_env="WECHAT_OAUTH_APP_SECRET",
    enabled_check="ENABLE_WECHAT_OAUTH",
)

GDE_DEF = _FakeOAuthProviderDefinition(
    name="gde",
    display_name="Gde",
    icon="gde",
    authorize_url="https://gde.test/dspcas/oauth2.0/authorize",
    authorize_method="GET",
    authorize_params={},
    authorize_fragment="",
    authorize_param_map={"client_id": "client_id", "redirect_uri": "redirect_uri"},
    encode_redirect_uri=False,
    token_url="https://gde.test/dspcas/v2/oauth2.0/accessToken",
    token_method="POST",
    token_params_map={
        "client_id": "client_id",
        "client_secret": "secret",
        "code": "code",
        "grant_type": "grant_type",
        "redirect_uri": "redirect_uri",
    },
    token_extra_params={},
    token_error_key="errorCode",
    token_error_message_key="errorMessage",
    token_response_id_key=None,
    userinfo_url="https://gde.test/dspcas/oauth2.0/profile",
    userinfo_auth_scheme="Bearer",
    userinfo_params={"access_token": "{access_token}"},
    userinfo_field_map={"id": "attributes.userId", "email": "", "username": "id"},
    userinfo_needs_email_fetch=False,
    userinfo_email_url=None,
    client_id_env="GDE_OAUTH_CLIENT_ID",
    client_secret_env="GDE_OAUTH_CLIENT_SECRET",
    enabled_check=None,
)

oauth_providers_mock = MagicMock()
oauth_providers_mock.OAUTH_PROVIDER_REGISTRY = {
    "github": GITHUB_DEF,
    "wechat": WECHAT_DEF,
    "gde": GDE_DEF,
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
    exchange_code_for_provider_token,
    get_authorize_url,
    get_enabled_providers,
    get_provider_user_info,
    get_supported_providers,
    list_linked_accounts,
    parse_state,
    unlink_account,
    _resolve_field,
    _build_ssl_context,
)


class TestParseState(unittest.TestCase):
    def test_parses_full_state_with_link_user_id(self):
        result = parse_state("github:random_token:user-123")
        self.assertEqual(result["provider"], "github")
        self.assertEqual(result["token"], "random_token")
        self.assertEqual(result["link_user_id"], "user-123")

    def test_parses_state_without_link_user_id(self):
        result = parse_state("github:random_token")
        self.assertEqual(result["provider"], "github")
        self.assertEqual(result["token"], "random_token")
        self.assertEqual(result["link_user_id"], "")

    def test_parses_minimal_state(self):
        result = parse_state("github")
        self.assertEqual(result["provider"], "github")
        self.assertEqual(result["token"], "")
        self.assertEqual(result["link_user_id"], "")


class TestResolveField(unittest.TestCase):
    def test_resolves_simple_field(self):
        data = {"id": "12345", "email": "test@example.com"}
        result = _resolve_field(data, "id")
        self.assertEqual(result, "12345")

    def test_resolves_nested_field(self):
        data = {"attributes": {"userId": "abc"}}
        result = _resolve_field(data, "attributes.userId")
        self.assertEqual(result, "abc")

    def test_returns_none_for_missing_field(self):
        data = {"id": "12345"}
        result = _resolve_field(data, "email")
        self.assertIsNone(result)

    def test_returns_none_for_missing_nested_field(self):
        data = {"attributes": {"name": "test"}}
        result = _resolve_field(data, "attributes.userId")
        self.assertIsNone(result)


class TestBuildSSLContext(unittest.TestCase):
    def test_returns_default_context_when_verify_enabled(self):
        ctx = _build_ssl_context()
        self.assertEqual(ctx.verify_mode, 2)

    def test_returns_no_verify_context_when_disabled(self):
        with patch.object(oauth_service_module, "OAUTH_SSL_VERIFY", False):
            ctx = _build_ssl_context()
            self.assertEqual(ctx.verify_mode, 0)
            self.assertEqual(ctx.check_hostname, False)


class TestGetSupportedProviders(unittest.TestCase):
    def test_supported_providers_set(self):
        providers = get_supported_providers()
        self.assertEqual(providers, {"github", "wechat", "gde"})


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

    def test_returns_github_authorize_url_with_link_user_id(self):
        with patch.dict(
            os.environ,
            {
                "GITHUB_OAUTH_CLIENT_ID": "gh_test_id",
                "GITHUB_OAUTH_CLIENT_SECRET": "gh_test_secret",
            },
            clear=False,
        ):
            url = get_authorize_url("github", link_user_id="user-123")

        self.assertIn("github.com/login/oauth/authorize", url)
        self.assertIn("user-123", url)

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


class TestExchangeCodeForProviderToken(unittest.TestCase):
    def test_raises_for_unsupported_provider(self):
        with self.assertRaises(_OAuthProviderError):
            exchange_code_for_provider_token("google", "code123")


class TestGetProviderUserInfo(unittest.TestCase):
    def test_raises_for_unsupported_provider(self):
        with self.assertRaises(_OAuthProviderError):
            get_provider_user_info("google", "token123")


class TestCreateOrUpdateOAuthAccount(unittest.TestCase):
    def test_creates_new_account_when_none_exists(self):
        oauth_account_db_mock.reset_mock()
        oauth_account_db_mock.get_oauth_account_by_provider.return_value = None
        oauth_account_db_mock.get_soft_deleted_oauth_account.return_value = None
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

    def test_reactivates_soft_deleted_account(self):
        oauth_account_db_mock.reset_mock()
        oauth_account_db_mock.get_oauth_account_by_provider.side_effect = [
            None,
            {"provider": "github", "provider_user_id": "12345", "user_id": "user-1"},
        ]
        oauth_account_db_mock.get_soft_deleted_oauth_account.return_value = {
            "provider": "github",
            "provider_user_id": "12345",
            "user_id": "user-1",
            "delete_flag": "Y",
        }
        oauth_account_db_mock.reactivate_oauth_account.return_value = True

        result = create_or_update_oauth_account(
            user_id="user-1",
            provider="github",
            provider_user_id="12345",
            email="octo@github.com",
            username="octocat",
        )

        oauth_account_db_mock.reactivate_oauth_account.assert_called_once_with(
            provider="github",
            provider_user_id="12345",
            user_id="user-1",
            provider_email="octo@github.com",
            provider_username="octocat",
            tenant_id="default-tenant-id",
        )
        oauth_account_db_mock.insert_oauth_account.assert_not_called()
        self.assertEqual(result["user_id"], "user-1")

    def test_updates_existing_account(self):
        oauth_account_db_mock.reset_mock()
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

    def test_raises_when_already_bound_to_other_user(self):
        oauth_account_db_mock.reset_mock()
        oauth_account_db_mock.get_oauth_account_by_provider.return_value = {
            "provider": "github",
            "provider_user_id": "12345",
            "user_id": "old-user",
        }

        with self.assertRaises(_OAuthLinkError):
            create_or_update_oauth_account(
                user_id="new-user",
                provider="github",
                provider_user_id="12345",
                email="octo@github.com",
                username="octocat",
            )

        oauth_account_db_mock.update_oauth_account_tokens.assert_not_called()
        oauth_account_db_mock.insert_oauth_account.assert_not_called()


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


class TestHTTPHelpers(unittest.TestCase):
    def test_http_post_json_returns_parsed_response(self):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"access_token": "test_token"}'
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_response)
        mock_cm.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_cm):
            import services.oauth_service as svc
            result = svc._http_post_json("https://test.com/token", {"code": "abc"})
            self.assertEqual(result["access_token"], "test_token")

    def test_http_get_json_returns_parsed_response(self):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"id": "12345", "login": "octocat"}'
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_response)
        mock_cm.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_cm):
            import services.oauth_service as svc
            result = svc._http_get_json("https://test.com/user")
            self.assertEqual(result["id"], "12345")

    def test_http_post_json_merges_headers(self):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"result": "ok"}'
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_response)
        mock_cm.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_cm) as mock_urlopen:
            import services.oauth_service as svc
            svc._http_post_json("https://test.com/token", {"code": "abc"}, headers={"X-Custom": "value"})
            self.assertTrue(mock_urlopen.called)

    def test_http_get_json_with_headers(self):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"result": "ok"}'
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_response)
        mock_cm.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_cm):
            import services.oauth_service as svc
            result = svc._http_get_json("https://test.com/user", headers={"Authorization": "Bearer token"})
            self.assertEqual(result["result"], "ok")


class TestGetProviderUserInfoEdgeCases(unittest.TestCase):
    def test_returns_email_from_primary_in_emails_list(self):
        mock_user_resp = MagicMock()
        mock_user_resp.read.return_value = b'{"id": "12345", "login": "octocat"}'
        mock_emails_resp = MagicMock()
        mock_emails_resp.read.return_value = b'[{"email": "secondary@github.com", "primary": false}, {"email": "primary@github.com", "primary": true}]'
        
        mock_cm1 = MagicMock()
        mock_cm1.__enter__ = MagicMock(return_value=mock_user_resp)
        mock_cm1.__exit__ = MagicMock(return_value=False)
        mock_cm2 = MagicMock()
        mock_cm2.__enter__ = MagicMock(return_value=mock_emails_resp)
        mock_cm2.__exit__ = MagicMock(return_value=False)
        
        with patch("urllib.request.urlopen", side_effect=[mock_cm1, mock_cm2]):
            env = {
                "GITHUB_OAUTH_CLIENT_ID": "id",
                "GITHUB_OAUTH_CLIENT_SECRET": "secret",
            }
            with patch.dict(os.environ, env, clear=False):
                result = get_provider_user_info("github", "test_token")

        self.assertEqual(result["email"], "primary@github.com")

    def test_returns_first_email_when_no_primary(self):
        mock_user_resp = MagicMock()
        mock_user_resp.read.return_value = b'{"id": "12345", "login": "octocat"}'
        mock_emails_resp = MagicMock()
        mock_emails_resp.read.return_value = b'[{"email": "first@github.com"}]'
        
        mock_cm1 = MagicMock()
        mock_cm1.__enter__ = MagicMock(return_value=mock_user_resp)
        mock_cm1.__exit__ = MagicMock(return_value=False)
        mock_cm2 = MagicMock()
        mock_cm2.__enter__ = MagicMock(return_value=mock_emails_resp)
        mock_cm2.__exit__ = MagicMock(return_value=False)
        
        with patch("urllib.request.urlopen", side_effect=[mock_cm1, mock_cm2]):
            env = {
                "GITHUB_OAUTH_CLIENT_ID": "id",
                "GITHUB_OAUTH_CLIENT_SECRET": "secret",
            }
            with patch.dict(os.environ, env, clear=False):
                result = get_provider_user_info("github", "test_token")

        self.assertEqual(result["email"], "first@github.com")

    def test_fallback_email_when_no_email_found(self):
        mock_user_resp = MagicMock()
        mock_user_resp.read.return_value = b'{"id": "12345", "login": "testuser"}'
        mock_emails_resp = MagicMock()
        mock_emails_resp.read.return_value = b'[]'
        
        mock_cm1 = MagicMock()
        mock_cm1.__enter__ = MagicMock(return_value=mock_user_resp)
        mock_cm1.__exit__ = MagicMock(return_value=False)
        mock_cm2 = MagicMock()
        mock_cm2.__enter__ = MagicMock(return_value=mock_emails_resp)
        mock_cm2.__exit__ = MagicMock(return_value=False)
        
        with patch("urllib.request.urlopen", side_effect=[mock_cm1, mock_cm2]):
            env = {
                "GITHUB_OAUTH_CLIENT_ID": "id",
                "GITHUB_OAUTH_CLIENT_SECRET": "secret",
            }
            with patch.dict(os.environ, env, clear=False):
                result = get_provider_user_info("github", "test_token")

        self.assertEqual(result["email"], "testuser@nexent.com")

    def test_wechat_does_not_fetch_emails(self):
        mock_user_resp = MagicMock()
        mock_user_resp.read.return_value = b'{"openid": "wx123", "nickname": "wechat_user"}'
        
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_user_resp)
        mock_cm.__exit__ = MagicMock(return_value=False)
        
        with patch("urllib.request.urlopen", return_value=mock_cm):
            env = {
                "ENABLE_WECHAT_OAUTH": "true",
                "WECHAT_OAUTH_APP_ID": "id",
                "WECHAT_OAUTH_APP_SECRET": "secret",
            }
            with patch.dict(os.environ, env, clear=False):
                result = get_provider_user_info("wechat", "test_token", openid="wx123")

        self.assertEqual(result["id"], "wx123")
        self.assertEqual(result["username"], "wechat_user")

    def test_resolves_nested_field_path(self):
        mock_user_resp = MagicMock()
        mock_user_resp.read.return_value = b'{"attributes": {"userId": "nested123"}, "id": "testuser"}'
        
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_user_resp)
        mock_cm.__exit__ = MagicMock(return_value=False)
        
        with patch("urllib.request.urlopen", return_value=mock_cm):
            env = {
                "GDE_URL": "https://gde.test",
                "GDE_OAUTH_CLIENT_ID": "id",
                "GDE_OAUTH_CLIENT_SECRET": "secret",
            }
            with patch.dict(os.environ, env, clear=False):
                result = get_provider_user_info("gde", "test_token")

        self.assertEqual(result["id"], "nested123")


class TestExchangeCodeForProviderTokenWithMock(unittest.TestCase):
    def test_exchange_with_post_method(self):
        mock_token_resp = MagicMock()
        mock_token_resp.read.return_value = b'{"access_token": "gh_token_123"}'
        
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_token_resp)
        mock_cm.__exit__ = MagicMock(return_value=False)
        
        with patch("urllib.request.urlopen", return_value=mock_cm):
            env = {
                "GITHUB_OAUTH_CLIENT_ID": "test_id",
                "GITHUB_OAUTH_CLIENT_SECRET": "test_secret",
            }
            with patch.dict(os.environ, env, clear=False):
                result = exchange_code_for_provider_token("github", "code123")

        self.assertEqual(result["access_token"], "gh_token_123")

    def test_exchange_with_get_method(self):
        mock_token_resp = MagicMock()
        mock_token_resp.read.return_value = b'{"access_token": "wx_token_456", "openid": "wx_openid"}'
        
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_token_resp)
        mock_cm.__exit__ = MagicMock(return_value=False)
        
        with patch("urllib.request.urlopen", return_value=mock_cm):
            env = {
                "ENABLE_WECHAT_OAUTH": "true",
                "WECHAT_OAUTH_APP_ID": "wx_id",
                "WECHAT_OAUTH_APP_SECRET": "wx_secret",
            }
            with patch.dict(os.environ, env, clear=False):
                result = exchange_code_for_provider_token("wechat", "code456")

        self.assertEqual(result["access_token"], "wx_token_456")
        self.assertEqual(result["openid"], "wx_openid")

    def test_raises_on_provider_error_response(self):
        mock_token_resp = MagicMock()
        mock_token_resp.read.return_value = b'{"errcode": 40001, "errmsg": "invalid code"}'
        
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_token_resp)
        mock_cm.__exit__ = MagicMock(return_value=False)
        
        with patch("urllib.request.urlopen", return_value=mock_cm):
            env = {
                "ENABLE_WECHAT_OAUTH": "true",
                "WECHAT_OAUTH_APP_ID": "wx_id",
                "WECHAT_OAUTH_APP_SECRET": "wx_secret",
            }
            with patch.dict(os.environ, env, clear=False):
                with self.assertRaises(_OAuthProviderError):
                    exchange_code_for_provider_token("wechat", "bad_code")


class TestGetAuthorizeUrlEdgeCases(unittest.TestCase):
    def test_includes_authorize_params(self):
        env = {
            "GITHUB_OAUTH_CLIENT_ID": "gh_test_id",
            "GITHUB_OAUTH_CLIENT_SECRET": "gh_test_secret",
        }
        with patch.dict(os.environ, env, clear=False):
            url = get_authorize_url("github")

        self.assertIn("scope=", url)

    def test_wechat_includes_fragment(self):
        env = {
            "ENABLE_WECHAT_OAUTH": "true",
            "WECHAT_OAUTH_APP_ID": "wx_test_id",
            "WECHAT_OAUTH_APP_SECRET": "wx_test_secret",
        }
        with patch.dict(os.environ, env, clear=False):
            url = get_authorize_url("wechat")

        self.assertTrue(url.endswith("#wechat_redirect"))

    def test_includes_state_token(self):
        env = {
            "GITHUB_OAUTH_CLIENT_ID": "gh_test_id",
            "GITHUB_OAUTH_CLIENT_SECRET": "gh_test_secret",
        }
        with patch.dict(os.environ, env, clear=False):
            url = get_authorize_url("github")

        self.assertIn("state=github", url)


if __name__ == "__main__":
    unittest.main()