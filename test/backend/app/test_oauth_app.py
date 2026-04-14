import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

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

sys.modules["consts.model"] = MagicMock()

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
sys.modules["database.oauth_account_db"] = MagicMock()
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


class TestCallback(unittest.TestCase):
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
        oauth_service_mock.get_oauth_account_by_provider.return_value = None
        oauth_service_mock.exchange_code_for_provider_token.return_value = {
            "access_token": "ghu_provider_token_123",
        }
        oauth_service_mock.get_provider_user_info.return_value = {
            "id": "12345",
            "email": "octocat@github.com",
            "username": "octocat",
        }

        mock_existing_user = MagicMock()
        mock_existing_user.id = "user-uuid-123"
        mock_existing_user.email = "octocat@github.com"

        mock_users_resp = MagicMock()
        mock_users_resp.users = [mock_existing_user]

        mock_admin_client = MagicMock()
        mock_admin_client.auth.admin.list_users.return_value = mock_users_resp

        auth_utils_mock.get_supabase_admin_client.return_value = mock_admin_client
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

    def test_success_creates_new_user_when_not_found(self):
        oauth_service_mock.get_oauth_account_by_provider.return_value = None
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
        self.assertEqual(data["data"]["user"]["email"], "newuser@github.com")
        mock_admin_client.auth.admin.create_user.assert_called_once()

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
        mock_identity = MagicMock()
        mock_identity.provider = "email"

        mock_user = MagicMock()
        mock_user.identities = [mock_identity]
        mock_user.app_metadata = MagicMock()
        mock_user.app_metadata.get = MagicMock(return_value="email")

        mock_user_resp = MagicMock()
        mock_user_resp.user = mock_user

        mock_admin = MagicMock()
        mock_admin.auth.admin.get_user_by_id.return_value = mock_user_resp
        auth_utils_mock.get_supabase_admin_client.return_value = mock_admin
        oauth_service_mock.count_oauth_accounts_by_user_id.return_value = 2

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
        oauth_service_mock.unlink_account.assert_called_once()

    def test_returns_401_without_auth(self):
        response = client.delete("/user/oauth/accounts/github")

        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

    @patch("apps.oauth_app.get_current_user_id")
    def test_returns_400_when_last_account(self, mock_get_user):
        mock_get_user.return_value = ("user-1", "t-1")
        oauth_service_mock.unlink_account.side_effect = _OAuthLinkError(
            "Cannot unlink last"
        )

        response = client.delete(
            "/user/oauth/accounts/github",
            headers={"Authorization": "Bearer valid"},
        )

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

        oauth_service_mock.unlink_account.side_effect = None


if __name__ == "__main__":
    unittest.main()
