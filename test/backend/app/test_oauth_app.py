import sys
import os
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

test_dir = os.path.dirname(__file__)
backend_dir = os.path.abspath(os.path.join(test_dir, "../../../backend"))
sys.path.insert(0, backend_dir)

sys.modules["boto3"] = MagicMock()

consts_mock = MagicMock()
consts_mock.const = MagicMock()
consts_mock.const.GITHUB_OAUTH_CLIENT_ID = "test_id"
consts_mock.const.GITHUB_OAUTH_CLIENT_SECRET = "test_secret"
consts_mock.const.ENABLE_WECHAT_OAUTH = False
consts_mock.const.OAUTH_CALLBACK_BASE_URL = "http://localhost:3000"
consts_mock.const.SUPABASE_URL = "http://supabase.test"
consts_mock.const.DEFAULT_TENANT_ID = "default"
sys.modules["consts"] = consts_mock
sys.modules["consts.const"] = consts_mock.const

consts_model_mock = MagicMock()


class _OAuthCompleteRequest:
    def __init__(self, **data):
        self.email = data.get("email")
        self.password = data.get("password")
        self.invite_code = data.get("invite_code")


consts_model_mock.OAuthCompleteRequest = _OAuthCompleteRequest
sys.modules["consts.model"] = consts_model_mock

oauth_providers_mock = MagicMock()
oauth_providers_mock.get_all_provider_definitions.return_value = {
    "github": MagicMock(),
    "wechat": MagicMock(),
}
sys.modules["consts.oauth_providers"] = oauth_providers_mock


class _OAuthProviderError(Exception):
    pass


class _OAuthLinkError(Exception):
    pass


class _UnauthorizedError(Exception):
    pass


exceptions_mock = MagicMock()
exceptions_mock.OAuthProviderError = _OAuthProviderError
exceptions_mock.OAuthLinkError = _OAuthLinkError
exceptions_mock.UnauthorizedError = _UnauthorizedError
sys.modules["consts.exceptions"] = exceptions_mock

sys.modules["database"] = MagicMock()
database_oauth_mock = MagicMock()
database_oauth_mock.get_oauth_account_by_provider = MagicMock(return_value=None)
database_oauth_mock.get_soft_deleted_oauth_account = MagicMock(return_value=None)
sys.modules["database.oauth_account_db"] = database_oauth_mock
sys.modules["database.user_tenant_db"] = MagicMock()
sys.modules["database.client"] = MagicMock()
sys.modules["database.db_models"] = MagicMock()
sys.modules["backend.database"] = MagicMock()
sys.modules["backend.database.client"] = MagicMock()
sys.modules["backend.database.db_models"] = MagicMock()
sys.modules["utils"] = MagicMock()
sys.modules["utils.token_encryption"] = MagicMock()
sys.modules["utils.config_utils"] = MagicMock()

auth_utils_mock = MagicMock()
auth_utils_mock.get_current_user_id = MagicMock(return_value=("user-1", "t-1"))
auth_utils_mock.get_jwt_expiry_seconds = MagicMock(return_value=3600)
auth_utils_mock.calculate_expires_at = MagicMock(return_value=1735689600)
auth_utils_mock.get_supabase_admin_client = MagicMock()
auth_utils_mock.generate_session_jwt = MagicMock(return_value="eyJ.mock.jwt.token")
sys.modules["utils.auth_utils"] = auth_utils_mock

oauth_service_mock = MagicMock()
oauth_service_mock.parse_state = MagicMock(
    return_value={"provider": "github", "token": "tok", "link_user_id": ""}
)
oauth_service_mock.generate_pending_oauth_token = MagicMock(return_value="pending.jwt")
oauth_service_mock.find_supabase_user_id_by_email = MagicMock(return_value=None)
oauth_service_mock.complete_pending_oauth_account = AsyncMock()
sys.modules["services"] = MagicMock()
sys.modules["services.oauth_service"] = oauth_service_mock

nexent_mock = MagicMock()
sys.modules["nexent"] = nexent_mock
sys.modules["nexent.storage"] = MagicMock()
sys.modules["nexent.storage.storage_client_factory"] = MagicMock()
sys.modules["nexent.storage.minio_config"] = MagicMock()

storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch(
    "nexent.storage.storage_client_factory.create_storage_client_from_config",
    return_value=storage_client_mock,
).start()
patch(
    "nexent.storage.minio_config.MinIOStorageConfig.validate", lambda self: None
).start()
patch("database.client.MinioClient", return_value=minio_mock).start()
patch("database.client.MinioClient", return_value=minio_mock).start()
patch("database.client.minio_client", minio_mock).start()

from fastapi.testclient import TestClient
from fastapi import FastAPI
from http import HTTPStatus

from apps.oauth_app import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestGetProviders(unittest.TestCase):
    def test_returns_provider_list(self):
        oauth_service_mock.get_enabled_providers.return_value = [
            {
                "name": "github",
                "display_name": "GitHub",
                "icon": "github",
                "enabled": True,
            }
        ]

        response = client.get("/user/oauth/providers")

        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data["message"], "success")
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(data["data"][0]["name"], "github")

    def test_returns_empty_list(self):
        oauth_service_mock.get_enabled_providers.return_value = []

        response = client.get("/user/oauth/providers")

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()["data"], [])


class TestAuthorize(unittest.TestCase):
    def test_redirects_to_provider(self):
        oauth_service_mock.get_authorize_url.return_value = (
            "https://github.com/login/oauth/authorize?client_id=test_id"
        )

        response = client.get(
            "/user/oauth/authorize?provider=github", follow_redirects=False
        )

        self.assertEqual(response.status_code, HTTPStatus.FOUND)
        self.assertIn("github.com", response.headers["location"])

    def test_returns_400_for_unsupported_provider(self):
        oauth_service_mock.get_authorize_url.side_effect = _OAuthProviderError(
            "Unsupported"
        )

        response = client.get("/user/oauth/authorize?provider=google")

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

        oauth_service_mock.get_authorize_url.side_effect = None

    def test_returns_500_on_unexpected_error(self):
        oauth_service_mock.get_authorize_url.side_effect = Exception("Unexpected")

        response = client.get("/user/oauth/authorize?provider=github")

        self.assertEqual(response.status_code, HTTPStatus.INTERNAL_SERVER_ERROR)

        oauth_service_mock.get_authorize_url.side_effect = None


class TestLink(unittest.TestCase):
    def test_redirects_to_provider_with_link_user_id(self):
        oauth_service_mock.reset_mock()
        oauth_service_mock.get_authorize_url.return_value = (
            "https://github.com/login/oauth/authorize?client_id=test_id&state=github:token:user-1"
        )

        response = client.get(
            "/user/oauth/link?provider=github",
            headers={"Authorization": "Bearer valid_token"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, HTTPStatus.FOUND)
        self.assertIn("github.com", response.headers["location"])
        oauth_service_mock.get_authorize_url.assert_called_once_with("github", link_user_id="user-1")

    def test_returns_401_without_auth(self):
        response = client.get("/user/oauth/link?provider=github")

        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

    @patch("apps.oauth_app.get_current_user_id")
    def test_returns_401_for_invalid_token(self, mock_get_user):
        mock_get_user.side_effect = _UnauthorizedError("Invalid token")

        response = client.get(
            "/user/oauth/link?provider=github",
            headers={"Authorization": "Bearer invalid"},
        )

        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        mock_get_user.side_effect = None

    def test_returns_400_for_unsupported_provider(self):
        oauth_service_mock.get_authorize_url.side_effect = _OAuthProviderError(
            "Unsupported provider"
        )

        response = client.get(
            "/user/oauth/link?provider=google",
            headers={"Authorization": "Bearer valid_token"},
        )

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        oauth_service_mock.get_authorize_url.side_effect = None

    def test_returns_500_on_unexpected_error(self):
        oauth_service_mock.get_authorize_url.side_effect = Exception("Unexpected")

        response = client.get(
            "/user/oauth/link?provider=github",
            headers={"Authorization": "Bearer valid_token"},
        )

        self.assertEqual(response.status_code, HTTPStatus.INTERNAL_SERVER_ERROR)
        oauth_service_mock.get_authorize_url.side_effect = None


class TestCallback(unittest.TestCase):
    def setUp(self):
        oauth_service_mock.find_supabase_user_id_by_email.return_value = None

    def test_returns_error_when_provider_error(self):
        response = client.get(
            "/user/oauth/callback?provider=github&error=access_denied&error_description=User+cancelled"
        )

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        data = response.json()
        self.assertEqual(data["data"]["oauth_error"], "access_denied")

    def test_returns_error_when_no_code(self):
        response = client.get("/user/oauth/callback?provider=github")

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        data = response.json()
        self.assertEqual(data["data"]["oauth_error"], "no_code")

    def test_returns_error_for_unsupported_provider(self):
        response = client.get("/user/oauth/callback?provider=google&code=abc123")

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        data = response.json()
        self.assertEqual(data["data"]["oauth_error"], "unsupported_provider")

    def test_success_returns_session_data(self):
        oauth_service_mock.reset_mock()
        oauth_service_mock.parse_state.return_value = {"provider": "github", "token": "tok", "link_user_id": ""}
        database_oauth_mock.get_oauth_account_by_provider.return_value = {
            "provider": "github",
            "provider_user_id": "12345",
            "user_id": "user-uuid-123",
        }
        database_oauth_mock.get_soft_deleted_oauth_account.return_value = None
        oauth_service_mock.exchange_code_for_provider_token.return_value = {
            "access_token": "ghu_provider_token_123",
        }
        oauth_service_mock.get_provider_user_info.return_value = {
            "id": "12345",
            "email": "octocat@github.com",
            "username": "octocat",
        }

        auth_utils_mock.generate_session_jwt.return_value = "eyJ.mock.jwt.token"

        response = client.get("/user/oauth/callback?provider=github&code=valid_code")

        if response.status_code != HTTPStatus.OK:
            print("Response:", response.json())
        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertIn("session", data["data"])
        self.assertEqual(data["data"]["user"]["email"], "octocat@github.com")
        self.assertEqual(
            data["data"]["session"]["access_token"],
            "eyJ.mock.jwt.token",
        )
        self.assertEqual(data["data"]["session"]["expires_in_seconds"], 3600)

        auth_utils_mock.get_supabase_admin_client.return_value = MagicMock()

    def test_new_unbound_oauth_requires_account_completion(self):
        oauth_service_mock.reset_mock()
        oauth_service_mock.parse_state.return_value = {"provider": "github", "token": "tok", "link_user_id": ""}
        database_oauth_mock.get_oauth_account_by_provider.return_value = None
        database_oauth_mock.get_soft_deleted_oauth_account.return_value = None
        oauth_service_mock.exchange_code_for_provider_token.return_value = {
            "access_token": "ghu_provider_token_456",
        }
        oauth_service_mock.get_provider_user_info.return_value = {
            "id": "67890",
            "email": "newuser@github.com",
            "username": "newuser",
        }

        mock_empty_resp = MagicMock()
        mock_empty_resp.users = []

        mock_new_user = MagicMock()
        mock_new_user.id = "new-uuid-456"

        mock_admin_client = MagicMock()
        mock_admin_client.auth.admin.list_users.return_value = mock_empty_resp
        mock_admin_client.auth.admin.create_user.return_value = MagicMock(
            user=mock_new_user
        )

        auth_utils_mock.get_supabase_admin_client.return_value = mock_admin_client
        auth_utils_mock.generate_session_jwt.return_value = "eyJ.new.jwt.token"

        response = client.get("/user/oauth/callback?provider=github&code=new_code")

        if response.status_code != HTTPStatus.OK:
            print("Response:", response.json())
        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertTrue(data["data"]["requires_account_completion"])
        self.assertEqual(data["data"]["pending_token"], "pending.jwt")
        self.assertEqual(data["data"]["provider_email"], "newuser@github.com")
        oauth_service_mock.find_supabase_user_id_by_email.assert_called_once_with(
            mock_admin_client,
            "newuser@github.com",
        )
        mock_admin_client.auth.admin.create_user.assert_not_called()

        auth_utils_mock.get_supabase_admin_client.return_value = MagicMock()

    def test_unbound_oauth_with_existing_email_links_existing_account(self):
        oauth_service_mock.reset_mock()
        oauth_service_mock.parse_state.return_value = {"provider": "github", "token": "tok", "link_user_id": ""}
        database_oauth_mock.get_oauth_account_by_provider.return_value = None
        database_oauth_mock.get_soft_deleted_oauth_account.return_value = None
        oauth_service_mock.exchange_code_for_provider_token.return_value = {
            "access_token": "ghu_provider_token_existing",
        }
        oauth_service_mock.get_provider_user_info.return_value = {
            "id": "67891",
            "email": "existing@example.com",
            "username": "existing-user",
        }
        oauth_service_mock.find_supabase_user_id_by_email.return_value = "existing-user-id"
        oauth_service_mock.ensure_user_tenant_exists.return_value = {
            "user_id": "existing-user-id",
            "tenant_id": "t-1",
        }
        oauth_service_mock.create_or_update_oauth_account.return_value = {
            "provider": "github",
            "provider_user_id": "67891",
            "user_id": "existing-user-id",
        }
        mock_admin_client = MagicMock()
        auth_utils_mock.get_supabase_admin_client.return_value = mock_admin_client
        auth_utils_mock.generate_session_jwt.return_value = "eyJ.existing.jwt"

        response = client.get("/user/oauth/callback?provider=github&code=existing_code")

        if response.status_code != HTTPStatus.OK:
            print("Response:", response.json())
        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertNotIn("requires_account_completion", data["data"])
        self.assertEqual(data["data"]["user"]["id"], "existing-user-id")
        self.assertEqual(data["data"]["user"]["email"], "existing@example.com")
        self.assertEqual(data["data"]["session"]["access_token"], "eyJ.existing.jwt")

        oauth_service_mock.generate_pending_oauth_token.assert_not_called()
        oauth_service_mock.find_supabase_user_id_by_email.assert_called_once_with(
            mock_admin_client,
            "existing@example.com",
        )
        oauth_service_mock.create_or_update_oauth_account.assert_called_once_with(
            user_id="existing-user-id",
            provider="github",
            provider_user_id="67891",
            email="existing@example.com",
            username="existing-user",
        )

        auth_utils_mock.get_supabase_admin_client.return_value = MagicMock()

    def test_returns_500_on_token_exchange_failure(self):
        oauth_service_mock.exchange_code_for_provider_token.side_effect = Exception(
            "Token exchange failed"
        )

        response = client.get("/user/oauth/callback?provider=github&code=bad_code")

        self.assertEqual(response.status_code, HTTPStatus.INTERNAL_SERVER_ERROR)
        data = response.json()
        self.assertEqual(data["data"]["oauth_error"], "callback_failed")

        oauth_service_mock.exchange_code_for_provider_token.side_effect = None

    def test_returns_500_on_exception(self):
        oauth_service_mock.exchange_code_for_provider_token.side_effect = Exception(
            "Network error"
        )

        response = client.get("/user/oauth/callback?provider=github&code=crash_code")

        self.assertEqual(response.status_code, HTTPStatus.INTERNAL_SERVER_ERROR)
        data = response.json()
        self.assertEqual(data["data"]["oauth_error"], "callback_failed")

        oauth_service_mock.exchange_code_for_provider_token.side_effect = None

    def test_success_with_link_user_id_binding(self):
        """Callback with link_user_id should bind OAuth to that user directly."""
        oauth_service_mock.reset_mock()
        database_oauth_mock.reset_mock()
        oauth_service_mock.parse_state.return_value = {
            "provider": "github",
            "token": "tok",
            "link_user_id": "existing-user-uuid",
        }
        oauth_service_mock.exchange_code_for_provider_token.return_value = {
            "access_token": "ghu_provider_token",
        }
        oauth_service_mock.get_provider_user_info.return_value = {
            "id": "12345",
            "email": "octocat@github.com",
            "username": "octocat",
        }
        oauth_service_mock.ensure_user_tenant_exists.return_value = {
            "user_id": "existing-user-uuid",
            "tenant_id": "t-1",
        }
        oauth_service_mock.create_or_update_oauth_account.return_value = {
            "provider": "github",
            "provider_user_id": "12345",
            "user_id": "existing-user-uuid",
        }
        auth_utils_mock.generate_session_jwt.return_value = "eyJ.bind.jwt"

        response = client.get(
            "/user/oauth/callback?provider=github&code=bind_code&state=github:tok:existing-user-uuid"
        )

        if response.status_code != HTTPStatus.OK:
            print("Response:", response.json())
        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data["data"]["user"]["id"], "existing-user-uuid")
        self.assertEqual(data["data"]["user"]["email"], "octocat@github.com")

        # Should NOT call database lookup when link_user_id is present
        database_oauth_mock.get_oauth_account_by_provider.assert_not_called()

        # Should bind to the specified user
        oauth_service_mock.create_or_update_oauth_account.assert_called_once_with(
            user_id="existing-user-uuid",
            provider="github",
            provider_user_id="12345",
            email="octocat@github.com",
            username="octocat",
        )

    def test_link_user_id_binding_returns_specific_error_when_already_bound(self):
        oauth_service_mock.reset_mock()
        database_oauth_mock.reset_mock()
        oauth_service_mock.parse_state.return_value = {
            "provider": "github",
            "token": "tok",
            "link_user_id": "existing-user-uuid",
        }
        oauth_service_mock.exchange_code_for_provider_token.return_value = {
            "access_token": "ghu_provider_token",
        }
        oauth_service_mock.get_provider_user_info.return_value = {
            "id": "12345",
            "email": "octocat@github.com",
            "username": "octocat",
        }
        oauth_service_mock.create_or_update_oauth_account.side_effect = _OAuthLinkError(
            "This github account is already bound to another user"
        )

        response = client.get(
            "/user/oauth/callback?provider=github&code=bind_code&state=github:tok:existing-user-uuid"
        )

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        data = response.json()
        self.assertEqual(data["data"]["oauth_error"], "oauth_account_already_bound")
        self.assertEqual(
            data["data"]["oauth_error_description"],
            "OAuth account is already bound to another user",
        )

        oauth_service_mock.create_or_update_oauth_account.side_effect = None

    def test_success_with_already_bound_oauth_account(self):
        """Callback with existing binding should use that user_id without Supabase lookup."""
        oauth_service_mock.reset_mock()
        database_oauth_mock.reset_mock()
        auth_utils_mock.reset_mock()
        auth_utils_mock.get_current_user_id.return_value = ("user-1", "t-1")
        auth_utils_mock.get_jwt_expiry_seconds.return_value = 3600
        auth_utils_mock.calculate_expires_at.return_value = 1735689600
        auth_utils_mock.generate_session_jwt.return_value = "eyJ.bound.jwt"
        oauth_service_mock.parse_state.return_value = {
            "provider": "github",
            "token": "tok",
            "link_user_id": "",
        }
        database_oauth_mock.get_oauth_account_by_provider.return_value = {
            "provider": "github",
            "provider_user_id": "12345",
            "user_id": "bound-user-uuid",
        }
        oauth_service_mock.exchange_code_for_provider_token.return_value = {
            "access_token": "ghu_provider_token",
        }
        oauth_service_mock.get_provider_user_info.return_value = {
            "id": "12345",
            "email": "octocat@github.com",
            "username": "octocat",
        }
        oauth_service_mock.ensure_user_tenant_exists.return_value = {
            "user_id": "bound-user-uuid",
            "tenant_id": "t-1",
        }
        oauth_service_mock.create_or_update_oauth_account.return_value = {
            "provider": "github",
            "provider_user_id": "12345",
            "user_id": "bound-user-uuid",
        }

        response = client.get(
            "/user/oauth/callback?provider=github&code=login_code&state=github:tok"
        )

        if response.status_code != HTTPStatus.OK:
            print("Response:", response.json())
        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data["data"]["user"]["id"], "bound-user-uuid")

        auth_utils_mock.get_supabase_admin_client.assert_not_called()
        oauth_service_mock.create_or_update_oauth_account.assert_called_once()


class TestGetAccounts(unittest.TestCase):
    def test_returns_accounts_with_auth(self):
        oauth_service_mock.list_linked_accounts.return_value = [
            {
                "provider": "github",
                "provider_username": "octocat",
                "linked_at": "2025-01-01",
            }
        ]

        response = client.get(
            "/user/oauth/accounts",
            headers={"Authorization": "Bearer valid_token"},
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(len(data["data"]), 1)

    def test_returns_401_without_auth(self):
        response = client.get("/user/oauth/accounts")

        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

    @patch("apps.oauth_app.get_current_user_id")
    def test_returns_401_for_invalid_token(self, mock_get_user):
        mock_get_user.side_effect = _UnauthorizedError("Invalid token")

        response = client.get(
            "/user/oauth/accounts",
            headers={"Authorization": "Bearer invalid"},
        )

        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

        mock_get_user.side_effect = None


class TestDeleteAccount(unittest.TestCase):
    def setUp(self):
        oauth_service_mock.unlink_account.side_effect = None

    def test_unlinks_successfully(self):
        oauth_service_mock.unlink_account.reset_mock()
        oauth_service_mock.unlink_account.return_value = True

        response = client.delete(
            "/user/oauth/accounts/github",
            headers={"Authorization": "Bearer valid_token"},
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertTrue(data["data"]["unlinked"])
        oauth_service_mock.unlink_account.assert_called_once_with("user-1", "github")

    def test_returns_401_without_auth(self):
        response = client.delete("/user/oauth/accounts/github")

        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

    @patch("apps.oauth_app.get_current_user_id")
    def test_returns_400_when_account_not_found(self, mock_get_user):
        mock_get_user.return_value = ("user-1", "t-1")
        oauth_service_mock.unlink_account.side_effect = _OAuthLinkError(
            "No linked github account found"
        )

        response = client.delete(
            "/user/oauth/accounts/github",
            headers={"Authorization": "Bearer valid"},
        )

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

        oauth_service_mock.unlink_account.side_effect = None


class TestCallbackPagination(unittest.TestCase):
    def setUp(self):
        oauth_service_mock.find_supabase_user_id_by_email.return_value = None

    def test_finds_user_on_second_page(self):
        oauth_service_mock.reset_mock()
        database_oauth_mock.reset_mock()
        auth_utils_mock.reset_mock()
        auth_utils_mock.get_current_user_id.return_value = ("user-1", "t-1")
        auth_utils_mock.get_jwt_expiry_seconds.return_value = 3600
        auth_utils_mock.calculate_expires_at.return_value = 1735689600
        auth_utils_mock.generate_session_jwt.return_value = "eyJ.page2.jwt"
        oauth_service_mock.parse_state.return_value = {"provider": "github", "token": "tok", "link_user_id": ""}
        database_oauth_mock.get_oauth_account_by_provider.return_value = None
        database_oauth_mock.get_soft_deleted_oauth_account.return_value = None
        oauth_service_mock.exchange_code_for_provider_token.return_value = {"access_token": "ghu_token"}
        oauth_service_mock.get_provider_user_info.return_value = {
            "id": "12345",
            "email": "page2user@github.com",
            "username": "page2user",
        }
        oauth_service_mock.ensure_user_tenant_exists.return_value = {"user_id": "page2-uuid", "tenant_id": "t-1"}
        oauth_service_mock.create_or_update_oauth_account.return_value = {
            "provider": "github",
            "provider_user_id": "12345",
            "user_id": "page2-uuid",
        }
        oauth_service_mock.find_supabase_user_id_by_email.return_value = "page2-uuid"

        mock_admin_client = MagicMock()
        auth_utils_mock.get_supabase_admin_client.return_value = mock_admin_client

        response = client.get("/user/oauth/callback?provider=github&code=page2_code&state=github:tok")

        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data["data"]["user"]["id"], "page2-uuid")
        self.assertEqual(data["data"]["user"]["email"], "page2user@github.com")
        oauth_service_mock.find_supabase_user_id_by_email.assert_called_once_with(
            mock_admin_client,
            "page2user@github.com",
        )

        auth_utils_mock.get_supabase_admin_client.return_value = MagicMock()

    def test_stops_pagination_when_less_than_100_users(self):
        oauth_service_mock.reset_mock()
        database_oauth_mock.reset_mock()
        auth_utils_mock.reset_mock()
        auth_utils_mock.get_current_user_id.return_value = ("user-1", "t-1")
        auth_utils_mock.get_jwt_expiry_seconds.return_value = 3600
        auth_utils_mock.calculate_expires_at.return_value = 1735689600
        auth_utils_mock.generate_session_jwt.return_value = "eyJ.new.jwt"
        oauth_service_mock.parse_state.return_value = {"provider": "github", "token": "tok", "link_user_id": ""}
        database_oauth_mock.get_oauth_account_by_provider.return_value = None
        database_oauth_mock.get_soft_deleted_oauth_account.return_value = None
        oauth_service_mock.exchange_code_for_provider_token.return_value = {"access_token": "ghu_token"}
        oauth_service_mock.get_provider_user_info.return_value = {
            "id": "67890",
            "email": "newuser@github.com",
            "username": "newuser",
        }
        oauth_service_mock.ensure_user_tenant_exists.return_value = {"user_id": "new-uuid", "tenant_id": "t-1"}
        oauth_service_mock.create_or_update_oauth_account.return_value = {
            "provider": "github",
            "provider_user_id": "67890",
            "user_id": "new-uuid",
        }

        mock_empty_resp = MagicMock()
        mock_empty_resp.users = []
        mock_empty_resp.__len__ = lambda self: 0

        mock_new_user = MagicMock()
        mock_new_user.id = "new-uuid"

        mock_admin_client = MagicMock()
        mock_admin_client.auth.admin.list_users.return_value = mock_empty_resp
        mock_admin_client.auth.admin.create_user.return_value = MagicMock(user=mock_new_user)
        auth_utils_mock.get_supabase_admin_client.return_value = mock_admin_client

        response = client.get("/user/oauth/callback?provider=github&code=short_page_code&state=github:tok")

        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertTrue(data["data"]["requires_account_completion"])
        oauth_service_mock.find_supabase_user_id_by_email.assert_called_once_with(
            mock_admin_client,
            "newuser@github.com",
        )
        mock_admin_client.auth.admin.create_user.assert_not_called()

        auth_utils_mock.get_supabase_admin_client.return_value = MagicMock()


class TestCallbackEmailFallback(unittest.TestCase):
    def test_creates_user_with_oauth_fallback_email(self):
        oauth_service_mock.reset_mock()
        database_oauth_mock.reset_mock()
        auth_utils_mock.reset_mock()
        auth_utils_mock.get_current_user_id.return_value = ("user-1", "t-1")
        auth_utils_mock.get_jwt_expiry_seconds.return_value = 3600
        auth_utils_mock.calculate_expires_at.return_value = 1735689600
        auth_utils_mock.generate_session_jwt.return_value = "eyJ.noemail.jwt"
        oauth_service_mock.parse_state.return_value = {"provider": "github", "token": "tok", "link_user_id": ""}
        database_oauth_mock.get_oauth_account_by_provider.return_value = None
        database_oauth_mock.get_soft_deleted_oauth_account.return_value = None
        oauth_service_mock.exchange_code_for_provider_token.return_value = {"access_token": "ghu_token"}
        oauth_service_mock.get_provider_user_info.return_value = {
            "id": "99999",
            "email": "",
            "username": "noemail_user",
        }
        oauth_service_mock.ensure_user_tenant_exists.return_value = {"user_id": "noemail-uuid", "tenant_id": "t-1"}
        oauth_service_mock.create_or_update_oauth_account.return_value = {
            "provider": "github",
            "provider_user_id": "99999",
            "user_id": "noemail-uuid",
        }

        mock_empty_resp = MagicMock()
        mock_empty_resp.users = []
        mock_empty_resp.__len__ = lambda self: 0

        mock_new_user = MagicMock()
        mock_new_user.id = "noemail-uuid"

        mock_admin_client = MagicMock()
        mock_admin_client.auth.admin.list_users.return_value = mock_empty_resp
        mock_admin_client.auth.admin.create_user.return_value = MagicMock(user=mock_new_user)
        auth_utils_mock.get_supabase_admin_client.return_value = mock_admin_client

        response = client.get("/user/oauth/callback?provider=github&code=noemail_code&state=github:tok")

        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertTrue(data["data"]["requires_account_completion"])
        self.assertTrue(data["data"]["email_required"])
        self.assertEqual(data["data"]["provider_email"], "")
        oauth_service_mock.find_supabase_user_id_by_email.assert_not_called()

        auth_utils_mock.get_supabase_admin_client.return_value = MagicMock()


class TestCompleteOAuth(unittest.TestCase):
    def test_pending_returns_provider_info(self):
        pending_info = {
            "provider": "github",
            "provider_username": "octocat",
            "provider_email": "",
            "email_required": True,
        }

        with patch("apps.oauth_app.get_pending_oauth_info", return_value=pending_info):
            response = client.get(
                "/user/oauth/pending",
                headers={"X-OAuth-Pending-Token": "pending.jwt"},
            )

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertTrue(response.json()["data"]["email_required"])

    def test_pending_returns_401_when_missing_or_invalid(self):
        with patch(
            "apps.oauth_app.get_pending_oauth_info",
            side_effect=_OAuthLinkError("expired"),
        ):
            response = client.get("/user/oauth/pending")

        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

    def test_complete_returns_session_data(self):
        complete_mock = AsyncMock(
            return_value={
                "user": {"id": "new-user", "email": "new@example.com", "role": "USER"},
                "session": {
                    "access_token": "jwt",
                    "refresh_token": "",
                    "expires_at": 1735689600,
                    "expires_in_seconds": 3600,
                },
            }
        )

        with patch("apps.oauth_app.complete_pending_oauth_account", new=complete_mock):
            response = client.post(
                "/user/oauth/complete",
                headers={"X-OAuth-Pending-Token": "pending.jwt"},
                json={
                    "email": "new@example.com",
                    "password": "secret1",
                    "invite_code": "ABC123",
                },
            )

        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data["data"]["user"]["id"], "new-user")
        self.assertEqual(data["data"]["session"]["expires_in_seconds"], 3600)
        complete_mock.assert_awaited_once_with(
            pending_token="pending.jwt",
            email="new@example.com",
            password="secret1",
            invite_code="ABC123",
        )

    def test_complete_returns_conflict_for_existing_email(self):
        complete_mock = AsyncMock(
            side_effect=_OAuthLinkError(
                "Email already exists. Please log in with email and password."
            )
        )

        with patch("apps.oauth_app.complete_pending_oauth_account", new=complete_mock):
            response = client.post(
                "/user/oauth/complete",
                headers={"X-OAuth-Pending-Token": "pending.jwt"},
                json={
                    "email": "taken@example.com",
                    "password": "secret1",
                    "invite_code": "ABC123",
                },
            )

        self.assertEqual(response.status_code, HTTPStatus.CONFLICT)


class TestGetAccounts(unittest.TestCase):
    def test_returns_500_on_service_error(self):
        oauth_service_mock.list_linked_accounts.side_effect = Exception("Database error")

        response = client.get(
            "/user/oauth/accounts",
            headers={"Authorization": "Bearer valid_token"},
        )

        self.assertEqual(response.status_code, HTTPStatus.INTERNAL_SERVER_ERROR)

        oauth_service_mock.list_linked_accounts.side_effect = None


if __name__ == "__main__":
    unittest.main()
