import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

# Add path for correct imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(current_dir, "../../../backend"))

# Environment variables are now configured in conftest.py

boto3_mock = MagicMock()
minio_client_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()

from fastapi.testclient import TestClient
from http import HTTPStatus
from fastapi import FastAPI, HTTPException

# Create a test client with a fresh FastAPI app
from apps.mock_user_management_app import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestServiceHealth:
    """Test service health endpoint with full coverage"""

    def test_service_health_success(self):
        """Test normal service health check"""
        response = client.get("/user/service_health")

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Auth service is available"

    @patch('apps.mock_user_management_app.JSONResponse', side_effect=Exception("Simulated error"))
    def test_service_health_exception_path(self, mock_json_response):
        """Test service health exception handling path"""
        response = client.get("/user/service_health")
        
        # When JSONResponse fails, FastAPI should return 500
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Service health check failed" in data["detail"]


class TestUserSignup:
    """Test user signup endpoint with comprehensive coverage"""

    def test_signup_regular_user(self):
        """Test successful regular user registration"""
        response = client.post(
            "/user/signup",
            json={
                "email": "user@example.com",
                "password": "password123",
                "is_admin": False,
                "invite_code": None
            }
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert "User account registered successfully" in data["message"]
        assert "Please start experiencing the AI assistant service" in data["message"]
        assert data["data"]["user"]["role"] == "user"
        assert data["data"]["registration_type"] == "user"

    def test_signup_admin_user(self):
        """Test successful admin user registration"""
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
        assert "You now have system management permissions" in data["message"]
        assert data["data"]["user"]["role"] == "admin"
        assert data["data"]["registration_type"] == "admin"

    def test_signup_response_structure(self):
        """Test complete response structure"""
        response = client.post(
            "/user/signup",
            json={
                "email": "test@example.com",
                "password": "password123",
                "is_admin": False,
                "invite_code": None
            }
        )

        data = response.json()
        
        # Verify complete structure
        assert "message" in data
        assert "data" in data
        
        user_data = data["data"]
        assert "user" in user_data
        assert "session" in user_data
        assert "registration_type" in user_data
        
        user = user_data["user"]
        assert "id" in user
        assert "email" in user
        assert "role" in user
        
        session = user_data["session"]
        assert "access_token" in session
        assert "refresh_token" in session
        assert "expires_at" in session
        assert "expires_in_seconds" in session

    @patch('apps.mock_user_management_app.JSONResponse', side_effect=Exception("Test exception"))
    def test_signup_exception_handling(self, mock_json_response):
        """Test signup exception handling"""
        response = client.post(
            "/user/signup",
            json={
                "email": "error@example.com",
                "password": "password123",
                "is_admin": False,
                "invite_code": None
            }
        )
        
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "User registration failed" in data["detail"]


class TestUserSignin:
    """Test user signin endpoint"""

    def test_signin_success(self):
        """Test successful user login"""
        response = client.post(
            "/user/signin",
            json={
                "email": "test@example.com",
                "password": "password123"
            }
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Login successful, session validity is 10 years"
        assert data["data"]["user"]["email"] == "test@example.com"
        assert data["data"]["session"]["access_token"] == "mock_access_token"

    @patch('apps.mock_user_management_app.JSONResponse', side_effect=Exception("Signin error"))
    def test_signin_exception_handling(self, mock_json_response):
        """Test signin exception handling"""
        response = client.post(
            "/user/signin",
            json={
                "email": "error@example.com",
                "password": "password123"
            }
        )
        
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "User login failed" in data["detail"]


class TestRefreshToken:
    """Test refresh token endpoint"""

    def test_refresh_token_success(self):
        """Test successful token refresh"""
        response = client.post(
            "/user/refresh_token",
            json={"refresh_token": "old_refresh_token"},
            headers={"Authorization": "Bearer old_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Token refresh successful"
        
        session = data["data"]["session"]
        assert "mock_access_token_" in session["access_token"]
        assert "mock_refresh_token_" in session["refresh_token"]
        assert session["expires_in_seconds"] == 315360000

    @patch('apps.mock_user_management_app.datetime')
    def test_refresh_token_with_new_timestamp(self, mock_datetime):
        """Test refresh token generates new timestamp"""
        from datetime import datetime, timedelta
        mock_now = datetime(2024, 1, 1, 12, 0, 0)
        mock_datetime.now.return_value = mock_now
        mock_datetime.timedelta = timedelta
        
        response = client.post(
            "/user/refresh_token",
            json={"refresh_token": "test_token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        session = data["data"]["session"]
        
        # Verify new timestamp is used in token generation
        expected_timestamp = int((mock_now + timedelta(days=3650)).timestamp())
        assert str(expected_timestamp) in session["access_token"]
        assert str(expected_timestamp) in session["refresh_token"]

    @patch('apps.mock_user_management_app.JSONResponse', side_effect=Exception("Time error"))
    def test_refresh_token_exception_handling(self, mock_json_response):
        """Test refresh token exception handling"""
        response = client.post(
            "/user/refresh_token",
            json={"refresh_token": "error_token"}
        )
        
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Token refresh failed" in data["detail"]


class TestLogout:
    """Test logout endpoint"""

    def test_logout_success(self):
        """Test successful logout"""
        response = client.post(
            "/user/logout",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Logout successful"

    @patch('apps.mock_user_management_app.JSONResponse', side_effect=Exception("Logout error"))
    def test_logout_exception_handling(self, mock_json_response):
        """Test logout exception handling"""
        response = client.post("/user/logout")
        
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "User logout failed" in data["detail"]


class TestGetSession:
    """Test get session endpoint"""

    def test_get_session_success(self):
        """Test successful session retrieval"""
        response = client.get(
            "/user/session",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Session is valid"
        assert data["data"]["user"]["id"] == "user_id"
        assert data["data"]["user"]["email"] == "mock@example.com"
        assert data["data"]["user"]["role"] == "admin"

    @patch('apps.mock_user_management_app.JSONResponse', side_effect=Exception("Session error"))
    def test_get_session_exception_handling(self, mock_json_response):
        """Test session retrieval exception handling"""
        response = client.get("/user/session")
        
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Session validation failed" in data["detail"]


class TestGetCurrentUserId:
    """Test get current user ID endpoint"""

    def test_get_user_id_success(self):
        """Test successful user ID retrieval"""
        response = client.get(
            "/user/current_user_id",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Get user ID successfully"
        assert data["data"]["user_id"] == "user_id"

    @patch('apps.mock_user_management_app.JSONResponse', side_effect=Exception("User ID error"))
    def test_get_user_id_exception_handling(self, mock_json_response):
        """Test user ID retrieval exception handling"""
        response = client.get("/user/current_user_id")
        
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Failed to get user ID" in data["detail"]


class TestRequestValidation:
    """Test request validation for required fields"""

    def test_signup_missing_required_fields(self):
        """Test signup with missing required fields"""
        response = client.post(
            "/user/signup",
            json={"email": "test@example.com"}  # Missing password, is_admin
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_signin_missing_required_fields(self):
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


class TestIntegrationFlow:
    """Test complete user flow integration"""

    def test_complete_user_flow(self):
        """Test complete user registration and authentication flow"""
        # 1. Register user
        signup_response = client.post(
            "/user/signup",
            json={
                "email": "flow@example.com",
                "password": "password123",
                "is_admin": False,
                "invite_code": None
            }
        )
        assert signup_response.status_code == HTTPStatus.OK
        token = signup_response.json()["data"]["session"]["access_token"]

        # 2. Sign in user
        signin_response = client.post(
            "/user/signin",
            json={
                "email": "flow@example.com",
                "password": "password123"
            }
        )
        assert signin_response.status_code == HTTPStatus.OK

        # 3. Get session
        session_response = client.get(
            "/user/session",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert session_response.status_code == HTTPStatus.OK

        # 4. Get user ID
        user_id_response = client.get(
            "/user/current_user_id",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert user_id_response.status_code == HTTPStatus.OK

        # 5. Refresh token
        refresh_response = client.post(
            "/user/refresh_token",
            json={"refresh_token": "mock_refresh_token"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert refresh_response.status_code == HTTPStatus.OK

        # 6. Logout
        logout_response = client.post(
            "/user/logout",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert logout_response.status_code == HTTPStatus.OK


class TestMockDataConsistency:
    """Test mock data consistency and behavior"""

    def test_mock_user_data_consistency(self):
        """Test that mock user data is consistent"""
        # Get session multiple times
        responses = []
        for _ in range(3):
            response = client.get("/user/session")
            responses.append(response.json())
        
        # All responses should have the same user data
        for response in responses:
            assert response["data"]["user"]["id"] == "user_id"
            assert response["data"]["user"]["email"] == "mock@example.com"
            assert response["data"]["user"]["role"] == "admin"

    def test_mock_session_longevity(self):
        """Test that mock sessions have 10-year expiration"""
        response = client.post(
            "/user/refresh_token",
            json={"refresh_token": "test_token"}
        )
        
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        session = data["data"]["session"]
        
        # Mock sessions should have 10-year expiration (315360000 seconds)
        assert session["expires_in_seconds"] == 315360000

    def test_signup_email_reflection(self):
        """Test that signup reflects the input email"""
        test_emails = ["user1@test.com", "user2@test.com", "admin@test.com"]
        
        for email in test_emails:
            response = client.post(
                "/user/signup",
                json={
                    "email": email,
                    "password": "password123",
                    "is_admin": False,
                    "invite_code": None
                }
            )
            
            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["data"]["user"]["email"] == email

    def test_signin_email_reflection(self):
        """Test that signin reflects the input email"""
        test_emails = ["signin1@test.com", "signin2@test.com"]
        
        for email in test_emails:
            response = client.post(
                "/user/signin",
                json={
                    "email": email,
                    "password": "password123"
                }
            )
            
            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["data"]["user"]["email"] == email


class TestGetCurrentUserInfo:
    """Test get current user info endpoint"""

    @patch('apps.mock_user_management_app.get_user_info', new_callable=AsyncMock)
    def test_get_user_info_success(self, mock_get_user_info):
        """Test successful user information retrieval"""
        # Setup mock to return valid user info
        mock_user_info = {
            "user": {
                "user_id": "user_id",
                "group_ids": [1, 2, 3],
                "tenant_id": "tenant_id",
                "user_email": "mock@example.com",
                "user_role": "admin",
                "permissions": ["agent:create", "agent:read"],
                "accessibleRoutes": ["chat", "agents"]
            }
        }
        mock_get_user_info.return_value = mock_user_info

        response = client.get(
            "/user/current_user_info",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Success"
        assert data["data"] == mock_user_info
        assert data["data"]["user"]["user_id"] == "user_id"
        assert data["data"]["user"]["group_ids"] == [1, 2, 3]
        assert data["data"]["user"]["tenant_id"] == "tenant_id"
        mock_get_user_info.assert_called_once_with("user_id")

    @patch('apps.mock_user_management_app.get_user_info', new_callable=AsyncMock)
    def test_get_user_info_not_found(self, mock_get_user_info):
        """Test user information not found (returns None)"""
        # Setup mock to return None (user not found)
        mock_get_user_info.return_value = None

        response = client.get(
            "/user/current_user_info",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        data = response.json()
        assert "User not logged in or session invalid" in data["detail"]
        mock_get_user_info.assert_called_once_with("user_id")

    @patch('apps.mock_user_management_app.get_user_info', new_callable=AsyncMock)
    def test_get_user_info_unauthorized_error(self, mock_get_user_info):
        """Test UnauthorizedError exception handling"""
        from consts.exceptions import UnauthorizedError
        
        # Setup mock to raise UnauthorizedError
        mock_get_user_info.side_effect = UnauthorizedError("User information not found")

        response = client.get(
            "/user/current_user_info",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        data = response.json()
        assert "User not logged in or session invalid" in data["detail"]
        mock_get_user_info.assert_called_once_with("user_id")

    @patch('apps.mock_user_management_app.get_user_info', new_callable=AsyncMock)
    def test_get_user_info_general_exception(self, mock_get_user_info):
        """Test general exception handling"""
        # Setup mock to raise a general exception
        mock_get_user_info.side_effect = Exception("Database connection error")

        response = client.get(
            "/user/current_user_info",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert "Get user information failed" in data["detail"]
        mock_get_user_info.assert_called_once_with("user_id")

    @patch('apps.mock_user_management_app.get_user_info', new_callable=AsyncMock)
    def test_get_user_info_response_structure(self, mock_get_user_info):
        """Test complete response structure"""
        mock_user_info = {
            "user": {
                "user_id": "user_id",
                "group_ids": [],
                "tenant_id": "tenant_id",
                "user_email": "test@example.com",
                "user_role": "user",
                "permissions": [],
                "accessibleRoutes": []
            }
        }
        mock_get_user_info.return_value = mock_user_info

        response = client.get(
            "/user/current_user_info",
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        
        # Verify complete structure
        assert "message" in data
        assert "data" in data
        assert data["message"] == "Success"
        
        user_data = data["data"]["user"]
        assert "user_id" in user_data
        assert "group_ids" in user_data
        assert "tenant_id" in user_data
        assert "user_email" in user_data
        assert "user_role" in user_data
        assert "permissions" in user_data
        assert "accessibleRoutes" in user_data


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=apps.mock_user_management_app", "--cov-report=term-missing"]) 