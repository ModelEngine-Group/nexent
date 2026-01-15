import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import unittest
import sys
import os

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

# Mock external dependencies
sys.modules['boto3'] = MagicMock()

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.minio_client', minio_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Import exception classes
from consts.exceptions import NoInviteCodeException, IncorrectInviteCodeException, UserRegistrationException, UnauthorizedError
from supabase_auth.errors import AuthApiError, AuthWeakPasswordError

# Import the modules we need
from fastapi.testclient import TestClient
from http import HTTPStatus
from fastapi import FastAPI
from fastapi import HTTPException

# Create a test client with a fresh FastAPI app
from apps.user_management_app import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class MockUser:
    """Mock User class for testing"""
    
    def __init__(self, user_id, email):
        self.id = user_id
        self.email = email


class TestServiceHealth:
    """Test service health endpoint"""

    @patch('apps.user_management_app.check_auth_service_health')
    def test_service_health_available(self, mock_health_check):
        """Test when auth service is available"""
        mock_health_check.return_value = True

        response = client.get("/user/service_health")

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Auth service is available"
        mock_health_check.assert_called_once()

    @patch('apps.user_management_app.check_auth_service_health')
    def test_service_health_unavailable(self, mock_health_check):
        """Test when auth service is unavailable"""
        mock_health_check.side_effect = ConnectionError("Connection failed")

        response = client.get("/user/service_health")

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        data = response.json()
        assert data["detail"] == "Auth service is unavailable"
        mock_health_check.assert_called_once()

    @patch('apps.user_management_app.check_auth_service_health')
    def test_service_health_exception(self, mock_health_check):
        """Test when health check raises exception"""
        mock_health_check.side_effect = Exception("Connection error")

        response = client.get("/user/service_health")

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert data["detail"] == "Auth service is unavailable"
        mock_health_check.assert_called_once()


class TestUserSignup:
    """Test user signup endpoint"""

    def test_signup_success_regular_user(self):
        """Test successful regular user registration"""
        with patch('apps.user_management_app.signup_user') as mock_signup:
            mock_signup.return_value = {"user_id": "123", "email": "test@example.com"}

            response = client.post(
                "/user/signup",
                json={
                    "email": "test@example.com",
                    "password": "password123",
                    "is_admin": False,
                    "invite_code": None
                }
            )

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert "User account registered successfully" in data["message"]
            assert "data" in data
            mock_signup.assert_called_once_with(
                email="test@example.com",
                password="password123",
                is_admin=False,
                invite_code=None
            )

    def test_signup_success_admin_user(self):
        """Test successful admin user registration"""
        with patch('apps.user_management_app.signup_user') as mock_signup:
            mock_signup.return_value = {"user_id": "123", "email": "admin@example.com"}

            response = client.post(
                "/user/signup",
                json={
                    "email": "admin@example.com",
                    "password": "password123",
                    "is_admin": True,
                    "invite_code": "admin_code"
                }
            )

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert "Admin account registered successfully" in data["message"]
            assert "data" in data
            mock_signup.assert_called_once_with(
                email="admin@example.com",
                password="password123",
                is_admin=True,
                invite_code="admin_code"
            )

    def test_signup_no_invite_code_exception(self):
        """Test registration fails due to missing invite code"""
        with patch('apps.user_management_app.signup_user') as mock_signup:
            mock_signup.side_effect = NoInviteCodeException("No invite code configured")

            response = client.post(
                "/user/signup",
                json={
                    "email": "admin@example.com",
                    "password": "password123",
                    "is_admin": True,
                    "invite_code": None
                }
            )

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "INVITE_CODE_NOT_CONFIGURED"

    def test_signup_incorrect_invite_code_exception(self):
        """Test registration fails due to incorrect invite code"""
        with patch('apps.user_management_app.signup_user') as mock_signup:
            mock_signup.side_effect = IncorrectInviteCodeException("Invalid invite code")

            response = client.post(
                "/user/signup",
                json={
                    "email": "admin@example.com",
                    "password": "password123",
                    "is_admin": True,
                    "invite_code": "wrong_code"
                }
            )

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "INVITE_CODE_INVALID"

    def test_signup_registration_service_exception(self):
        """Test registration fails due to service error"""
        with patch('apps.user_management_app.signup_user') as mock_signup:
            mock_signup.side_effect = UserRegistrationException("Service error")

            response = client.post(
                "/user/signup",
                json={
                    "email": "test@example.com",
                    "password": "password123",
                    "is_admin": False,
                    "invite_code": None
                }
            )

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "REGISTRATION_SERVICE_ERROR"

    def test_signup_email_already_exists(self):
        """Test registration fails due to email already existing"""
        with patch('apps.user_management_app.signup_user') as mock_signup:
            mock_signup.side_effect = AuthApiError("Email already exists", 400, "email_exists")

            response = client.post(
                "/user/signup",
                json={
                    "email": "existing@example.com",
                    "password": "password123",
                    "is_admin": False,
                    "invite_code": None
                }
            )

            assert response.status_code == HTTPStatus.CONFLICT
            data = response.json()
            assert data["detail"] == "EMAIL_ALREADY_EXISTS"

    def test_signup_weak_password(self):
        """Test registration fails due to weak password"""
        with patch('apps.user_management_app.signup_user') as mock_signup:
            mock_signup.side_effect = AuthWeakPasswordError("Password too weak", 400, ["Password is too weak"])

            response = client.post(
                "/user/signup",
                json={
                    "email": "test@example.com",
                    "password": "weakpass",
                    "is_admin": False,
                    "invite_code": None
                }
            )

            assert response.status_code == HTTPStatus.NOT_ACCEPTABLE
            data = response.json()
            assert data["detail"] == "WEAK_PASSWORD"

    def test_signup_unknown_error(self):
        """Test registration fails due to unknown error"""
        with patch('apps.user_management_app.signup_user') as mock_signup:
            mock_signup.side_effect = Exception("Unknown error")

            response = client.post(
                "/user/signup",
                json={
                    "email": "test@example.com",
                    "password": "password123",
                    "is_admin": False,
                    "invite_code": None
                }
            )

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "UNKNOWN_ERROR"


class TestUserSignin:
    """Test user signin endpoint"""

    def test_signin_success(self):
        """Test successful user login"""
        with patch('apps.user_management_app.signin_user') as mock_signin:
            mock_signin.return_value = {
                "message": "Login successful",
                "data": {"access_token": "token123", "user_id": "123"}
            }

            response = client.post(
                "/user/signin",
                json={
                    "email": "test@example.com",
                    "password": "password123"
                }
            )

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Login successful"
            assert "access_token" in data["data"]
            mock_signin.assert_called_once_with(
                email="test@example.com",
                password="password123"
            )

    def test_signin_invalid_credentials(self):
        """Test login with invalid credentials"""
        with patch('apps.user_management_app.signin_user') as mock_signin:
            mock_signin.side_effect = AuthApiError("Invalid credentials", 400, "invalid_credentials")

            response = client.post(
                "/user/signin",
                json={
                    "email": "test@example.com",
                    "password": "wrong_password"
                }
            )

            assert response.status_code == HTTPStatus.UNAUTHORIZED
            data = response.json()
            assert data["detail"] == "Email or password error"

    def test_signin_unknown_error(self):
        """Test login with unknown error"""
        with patch('apps.user_management_app.signin_user') as mock_signin:
            mock_signin.side_effect = Exception("Database error")

            response = client.post(
                "/user/signin",
                json={
                    "email": "test@example.com",
                    "password": "password123"
                }
            )

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Login failed"


class TestRefreshToken:
    """Test refresh token endpoint"""

    def test_refresh_token_success(self):
        """Test successful token refresh"""
        with patch('apps.user_management_app.refresh_user_token') as mock_refresh:
            mock_refresh.return_value = {"access_token": "new_token", "refresh_token": "new_refresh"}

            response = client.post(
                "/user/refresh_token",
                json={"refresh_token": "old_refresh_token"},
                headers={"Authorization": "Bearer old_token"}
            )

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Token refresh successful"
            assert "session" in data["data"]
            mock_refresh.assert_called_once_with("Bearer old_token", "old_refresh_token")

    def test_refresh_token_no_authorization(self):
        """Test token refresh without authorization header"""
        response = client.post(
            "/user/refresh_token",
            json={"refresh_token": "refresh_token"}
        )

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        data = response.json()
        assert data["detail"] == "No authorization token provided"

    def test_refresh_token_no_refresh_token(self):
        """Test token refresh without refresh token in body"""
        response = client.post(
            "/user/refresh_token",
            json={},
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        data = response.json()
        assert data["detail"] == "No refresh token provided"

    def test_refresh_token_error(self):
        """Test token refresh with error"""
        with patch('apps.user_management_app.refresh_user_token') as mock_refresh:
            mock_refresh.side_effect = Exception("Refresh failed")

            response = client.post(
                "/user/refresh_token",
                json={"refresh_token": "refresh_token"},
                headers={"Authorization": "Bearer token"}
            )

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Refresh token failed"


class TestLogout:
    """Test logout endpoint"""

    @patch('apps.user_management_app.get_authorized_client')
    def test_logout_success(self, mock_get_client):
        """Test successful logout"""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        response = client.post(
            "/user/logout",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Logout successful"
        mock_get_client.assert_called_once_with("Bearer token")
        mock_client.auth.sign_out.assert_called_once()

    def test_logout_no_authorization(self):
        """Test logout without authorization header"""
        response = client.post("/user/logout")

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Logout successful"

    @patch('apps.user_management_app.get_authorized_client')
    def test_logout_signout_error_ignored(self, mock_get_client):
        """Test logout ignores sign_out errors and still succeeds"""
        mock_client = MagicMock()
        mock_client.auth.sign_out.side_effect = Exception("network")
        mock_get_client.return_value = mock_client

        response = client.post(
            "/user/logout",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Logout successful"
        mock_get_client.assert_called_once_with("Bearer token")
        mock_client.auth.sign_out.assert_called_once()

    @patch('apps.user_management_app.get_authorized_client')
    def test_logout_error(self, mock_get_client):
        """Test logout with error"""
        mock_get_client.side_effect = Exception("Logout error")

        response = client.post(
            "/user/logout",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert data["detail"] == "Logout failed!"


class TestGetSession:
    """Test get session endpoint"""

    @patch('apps.user_management_app.get_session_by_authorization')
    def test_get_session_success(self, mock_get_session):
        """Test successful session retrieval"""
        mock_get_session.return_value = {
            "user_id": "123",
            "email": "test@example.com",
            "expires_at": "2024-01-01T00:00:00Z"
        }

        response = client.get(
            "/user/session",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Session is valid"
        assert "user_id" in data["data"]
        mock_get_session.assert_called_once_with("Bearer token")

    def test_get_session_no_authorization(self):
        """Test session retrieval without authorization header"""
        response = client.get("/user/session")

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "User not logged in"
        assert data["data"] is None

    @patch('apps.user_management_app.get_session_by_authorization')
    def test_get_session_invalid(self, mock_get_session):
        """Test session retrieval with invalid session"""
        mock_get_session.side_effect = UnauthorizedError("Invalid session")

        response = client.get(
            "/user/session",
            headers={"Authorization": "Bearer invalid_token"}
        )

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        data = response.json()
        assert data["detail"] == "User not logged in or session invalid"

    @patch('apps.user_management_app.get_session_by_authorization')
    def test_get_session_error(self, mock_get_session):
        """Test session retrieval with general error"""
        mock_get_session.side_effect = Exception("Database error")

        response = client.get(
            "/user/session",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert data["detail"] == "Get user session failed"


class TestGetCurrentUserId:
    """Test get current user ID endpoint"""

    @patch('apps.user_management_app.validate_token')
    def test_get_user_id_success_valid_token(self, mock_validate):
        """Test successful user ID retrieval with valid token"""
        mock_user = MockUser("user123", "test@example.com")
        mock_validate.return_value = (True, mock_user)

        response = client.get(
            "/user/current_user_id",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Get user ID successfully"
        assert data["data"]["user_id"] == "user123"
        mock_validate.assert_called_once_with("Bearer token")

    @patch('apps.user_management_app.validate_token')
    @patch('apps.user_management_app.get_current_user_id')
    def test_get_user_id_success_parsed_from_token(self, mock_get_user_id, mock_validate):
        """Test successful user ID retrieval by parsing token"""
        mock_validate.return_value = (False, None)
        mock_get_user_id.return_value = ("user123", "tenant456")

        response = client.get(
            "/user/current_user_id",
            headers={"Authorization": "Bearer expired_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Successfully parsed user ID from token"
        assert data["data"]["user_id"] == "user123"
        mock_validate.assert_called_once_with("Bearer expired_token")
        mock_get_user_id.assert_called_once_with("Bearer expired_token")

    @patch('apps.user_management_app.validate_token')
    @patch('apps.user_management_app.get_current_user_id')
    def test_get_user_id_invalid_session(self, mock_get_user_id, mock_validate):
        """Test user ID retrieval with invalid session"""
        mock_validate.return_value = (False, None)
        mock_get_user_id.return_value = (None, None)

        response = client.get(
            "/user/current_user_id",
            headers={"Authorization": "Bearer invalid_token"}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        data = response.json()
        assert data["detail"] == "User not logged in or session invalid"

    def test_get_user_id_no_authorization(self):
        """Test user ID retrieval without authorization header"""
        response = client.get("/user/current_user_id")

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "User not logged in"
        assert data["data"]["user_id"] is None

    @patch('apps.user_management_app.validate_token')
    def test_get_user_id_error(self, mock_validate):
        """Test user ID retrieval with general error"""
        mock_validate.side_effect = Exception("Token validation error")

        response = client.get(
            "/user/current_user_id",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert data["detail"] == "Get user ID failed"


class TestRevokeUserAccount:
    """Tests for the /user/revoke endpoint"""

    @patch('apps.user_management_app.revoke_regular_user', new_callable=AsyncMock)
    @patch('apps.user_management_app.validate_token')
    @patch('apps.user_management_app.get_current_user_id')
    def test_revoke_success_regular_user(self, mock_get_ids, mock_validate, mock_revoke):
        mock_get_ids.return_value = ("user123", "tenant456")
        user = MagicMock()
        user.user_metadata = {"role": "user"}
        mock_validate.return_value = (True, user)

        response = client.post(
            "/user/revoke", headers={"Authorization": "Bearer token"})

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "User account revoked"
        mock_revoke.assert_awaited_once_with(
            user_id="user123", tenant_id="tenant456")

    @patch('apps.user_management_app.validate_token')
    @patch('apps.user_management_app.get_current_user_id')
    def test_revoke_forbidden_admin(self, mock_get_ids, mock_validate):
        mock_get_ids.return_value = ("admin123", "tenant456")
        user = MagicMock()
        user.user_metadata = {"role": "admin"}
        mock_validate.return_value = (True, user)

        response = client.post(
            "/user/revoke", headers={"Authorization": "Bearer token"})

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json()[
            "detail"] == "Admin account cannot be deleted via this endpoint"

    def test_revoke_no_authorization(self):
        response = client.post("/user/revoke")
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json()["detail"] == "No authorization token provided"

    @patch('apps.user_management_app.validate_token')
    @patch('apps.user_management_app.get_current_user_id')
    def test_revoke_invalid_session(self, mock_get_ids, mock_validate):
        mock_get_ids.return_value = ("user123", "tenant456")
        mock_validate.return_value = (False, None)

        response = client.post(
            "/user/revoke", headers={"Authorization": "Bearer invalid"})

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json()[
            "detail"] == "User not logged in or session invalid"

    @patch('apps.user_management_app.revoke_regular_user', new_callable=AsyncMock)
    @patch('apps.user_management_app.validate_token')
    @patch('apps.user_management_app.get_current_user_id')
    def test_revoke_error(self, mock_get_ids, mock_validate, mock_revoke):
        mock_get_ids.return_value = ("user123", "tenant456")
        user = MagicMock()
        user.user_metadata = {"role": "user"}
        mock_validate.return_value = (True, user)
        mock_revoke.side_effect = Exception("boom")

        response = client.post(
            "/user/revoke", headers={"Authorization": "Bearer token"})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "User revoke failed"


class TestIntegration:
    """Integration tests for user management flow"""

    @patch('apps.user_management_app.signup_user')
    @patch('apps.user_management_app.signin_user')
    @patch('apps.user_management_app.get_session_by_authorization')
    @patch('apps.user_management_app.get_authorized_client')
    def test_complete_user_flow(self, mock_get_client, mock_get_session, mock_signin, mock_signup):
        """Test complete user registration and authentication flow"""
        # 1. Register user
        mock_signup.return_value = {"user_id": "123", "email": "test@example.com"}
        signup_response = client.post(
            "/user/signup",
            json={
                "email": "test@example.com",
                "password": "password123",
                "is_admin": False,
                "invite_code": None
            }
        )
        assert signup_response.status_code == HTTPStatus.OK

        # 2. Sign in user
        mock_signin.return_value = {
            "message": "Login successful",
            "data": {"access_token": "token123", "user_id": "123"}
        }
        signin_response = client.post(
            "/user/signin",
            json={
                "email": "test@example.com",
                "password": "password123"
            }
        )
        assert signin_response.status_code == HTTPStatus.OK

        # 3. Get session
        mock_get_session.return_value = {
            "user_id": "123",
            "email": "test@example.com",
            "expires_at": "2024-01-01T00:00:00Z"
        }
        session_response = client.get(
            "/user/session",
            headers={"Authorization": "Bearer token123"}
        )
        assert session_response.status_code == HTTPStatus.OK

        # 4. Logout
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        logout_response = client.post(
            "/user/logout",
            headers={"Authorization": "Bearer token123"}
        )
        assert logout_response.status_code == HTTPStatus.OK


class TestDataValidation:
    """Test data validation"""

    def test_signup_missing_fields(self):
        """Test signup with missing required fields"""
        response = client.post(
            "/user/signup",
            json={"email": "test@example.com"}  # Missing password
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_signin_missing_fields(self):
        """Test signin with missing required fields"""
        response = client.post(
            "/user/signin",
            json={"email": "test@example.com"}  # Missing password
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_signup_invalid_email_format(self):
        """Test signup with invalid email format"""
        response = client.post(
            "/user/signup",
            json={
                "email": "invalid-email",
                "password": "password123",
                "is_admin": False,
                "invite_code": None
            }
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


class TestGetRolePermissions(unittest.TestCase):
    """Test get role permissions endpoint"""

    @patch('apps.user_management_app.get_permissions_by_role')
    def test_get_role_permissions_success(self, mock_get_permissions):
        """Test successfully getting role permissions"""
        # Setup mock data
        mock_permissions_data = {
            "user_role": "USER",
            "permissions": [
                {
                    "role_permission_id": 1,
                    "permission_category": "KNOWLEDGE_BASE",
                    "permission_type": "KNOWLEDGE",
                    "permission_subtype": "READ"
                },
                {
                    "role_permission_id": 2,
                    "permission_category": "AGENT_MANAGEMENT",
                    "permission_type": "AGENT",
                    "permission_subtype": "READ"
                }
            ],
            "total_permissions": 2,
            "message": "Successfully retrieved 2 permissions for role USER"
        }
        mock_get_permissions.return_value = mock_permissions_data

        # Execute
        response = client.get("/user/role_permissions/USER")

        # Assert
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Successfully retrieved 2 permissions for role USER"
        assert data["data"]["user_role"] == "USER"
        assert len(data["data"]["permissions"]) == 2
        assert data["data"]["total_permissions"] == 2
        mock_get_permissions.assert_called_once_with("USER")

    @patch('apps.user_management_app.get_permissions_by_role')
    def test_get_role_permissions_admin_role(self, mock_get_permissions):
        """Test getting permissions for ADMIN role"""
        # Setup mock data for ADMIN role
        mock_permissions_data = {
            "user_role": "ADMIN",
            "permissions": [
                {
                    "role_permission_id": 3,
                    "permission_category": "USER_MANAGEMENT",
                    "permission_type": "USER",
                    "permission_subtype": "CRUD"
                }
            ],
            "total_permissions": 1,
            "message": "Successfully retrieved 1 permissions for role ADMIN"
        }
        mock_get_permissions.return_value = mock_permissions_data

        # Execute
        response = client.get("/user/role_permissions/ADMIN")

        # Assert
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["data"]["user_role"] == "ADMIN"
        assert data["data"]["total_permissions"] == 1
        mock_get_permissions.assert_called_once_with("ADMIN")

    @patch('apps.user_management_app.get_permissions_by_role')
    def test_get_role_permissions_empty_result(self, mock_get_permissions):
        """Test getting permissions for role with no permissions"""
        # Setup mock data for role with no permissions
        mock_permissions_data = {
            "user_role": "NEW_ROLE",
            "permissions": [],
            "total_permissions": 0,
            "message": "Successfully retrieved 0 permissions for role NEW_ROLE"
        }
        mock_get_permissions.return_value = mock_permissions_data

        # Execute
        response = client.get("/user/role_permissions/NEW_ROLE")

        # Assert
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["data"]["user_role"] == "NEW_ROLE"
        assert len(data["data"]["permissions"]) == 0
        assert data["data"]["total_permissions"] == 0

    @patch('apps.user_management_app.get_permissions_by_role')
    def test_get_role_permissions_error(self, mock_get_permissions):
        """Test error handling for role permissions endpoint"""
        # Setup mock to raise exception
        mock_get_permissions.side_effect = Exception("Database connection failed")

        # Execute
        response = client.get("/user/role_permissions/USER")

        # Assert
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to retrieve permissions for role USER" in data["detail"]


if __name__ == "__main__":
    pytest.main([__file__]) 