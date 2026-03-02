import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

# Mock external dependencies
sys.modules['boto3'] = MagicMock()
sys.modules['nexent'] = MagicMock()
sys.modules['nexent.core'] = MagicMock()
sys.modules['nexent.core.agents'] = MagicMock()
# Create a mock ToolConfig class
from pydantic import BaseModel


class MockToolConfig(BaseModel):
    name: str = ""
    description: str = ""
    parameters: dict = {}


sys.modules['nexent.core.agents.agent_model'] = MagicMock()
sys.modules['nexent.core.agents.agent_model'].ToolConfig = MockToolConfig
sys.modules['nexent.storage'] = MagicMock()
sys.modules['nexent.storage.storage_client_factory'] = MagicMock()
sys.modules['nexent.storage.minio_config'] = MagicMock()

# Mock for memory_service import used in delete_user_and_cleanup
nexent_memory_service = MagicMock()
sys.modules['nexent.memory'] = MagicMock()
sys.modules['nexent.memory.memory_service'] = nexent_memory_service

# Patch storage factory and MinIO config validation to avoid errors during initialization
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('database.client.MinioClient', return_value=minio_mock).start()

# Import exception classes
from consts.exceptions import NotFoundException, ValidationError, UnauthorizedError

# Import the modules we need
from fastapi.testclient import TestClient
from http import HTTPStatus
from fastapi import FastAPI

# Create a test client with a fresh FastAPI app
from apps.user_app import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestGetUsersEndpoint:
    """Test get_users_endpoint (POST /users/list)"""

    def test_get_users_success(self):
        """Test successful user list retrieval"""
        with patch('apps.user_app.get_users') as mock_get_users:
            mock_get_users.return_value = {
                "users": [
                    {"id": "user1", "username": "user1@example.com", "role": "USER", "tenant_id": "tenant1"},
                    {"id": "user2", "username": "user2@example.com", "role": "ADMIN", "tenant_id": "tenant1"}
                ],
                "total": 2,
                "total_pages": 1
            }

            response = client.post(
                "/users/list",
                json={"tenant_id": "tenant1", "page": 1, "page_size": 20}
            )

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Users retrieved successfully"
            assert len(data["data"]) == 2
            assert data["pagination"]["total"] == 2
            assert data["pagination"]["page"] == 1
            assert data["pagination"]["page_size"] == 20
            assert data["pagination"]["total_pages"] == 1
            mock_get_users.assert_called_once_with("tenant1", 1, 20, "created_at", "desc")

    def test_get_users_empty_list(self):
        """Test user list retrieval with no users"""
        with patch('apps.user_app.get_users') as mock_get_users:
            mock_get_users.return_value = {
                "users": [],
                "total": 0,
                "total_pages": 0
            }

            response = client.post(
                "/users/list",
                json={"tenant_id": "tenant1", "page": 1, "page_size": 20}
            )

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Users retrieved successfully"
            assert len(data["data"]) == 0
            assert data["pagination"]["total"] == 0

    def test_get_users_with_pagination(self):
        """Test user list retrieval with custom pagination"""
        with patch('apps.user_app.get_users') as mock_get_users:
            mock_get_users.return_value = {
                "users": [
                    {"id": "user1", "username": "user1@example.com", "role": "USER", "tenant_id": "tenant1"}
                ],
                "total": 25,
                "total_pages": 3
            }

            response = client.post(
                "/users/list",
                json={"tenant_id": "tenant1", "page": 2, "page_size": 10}
            )

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["pagination"]["page"] == 2
            assert data["pagination"]["page_size"] == 10
            assert data["pagination"]["total"] == 25
            assert data["pagination"]["total_pages"] == 3
            mock_get_users.assert_called_once_with("tenant1", 2, 10, "created_at", "desc")

    def test_get_users_unexpected_error(self):
        """Test user list retrieval with unexpected error"""
        with patch('apps.user_app.get_users') as mock_get_users:
            mock_get_users.side_effect = Exception("Database connection failed")

            response = client.post(
                "/users/list",
                json={"tenant_id": "tenant1", "page": 1, "page_size": 20}
            )

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert "Failed to retrieve users" in data["detail"]
            assert "Database connection failed" in data["detail"]


class TestUpdateUserEndpoint:
    """Test update_user_endpoint (PUT /users/{user_id})"""

    def test_update_user_success(self):
        """Test successful user update"""
        with patch('apps.user_app.get_current_user_id') as mock_get_user_id, \
             patch('apps.user_app.update_user') as mock_update_user:

            mock_get_user_id.return_value = ("updater123", "tenant1")
            mock_update_user.return_value = {
                "id": "user1",
                "username": "user1@example.com",
                "role": "ADMIN"
            }

            response = client.put(
                "/users/user1",
                json={"role": "ADMIN"},
                headers={"Authorization": "Bearer token123"}
            )

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "User updated successfully"
            assert data["data"]["id"] == "user1"
            assert data["data"]["role"] == "ADMIN"
            mock_get_user_id.assert_called_once_with("Bearer token123")
            # Pydantic model includes all fields with None defaults
            mock_update_user.assert_called_once_with("user1", {"username": None, "email": None, "role": "ADMIN"}, "updater123")

    def test_update_user_validation_error(self):
        """Test user update with validation error"""
        with patch('apps.user_app.get_current_user_id') as mock_get_user_id, \
             patch('apps.user_app.update_user') as mock_update_user:

            mock_get_user_id.return_value = ("updater123", "tenant1")
            mock_update_user.side_effect = ValueError("Invalid role. Must be one of: ADMIN, DEV, USER")

            response = client.put(
                "/users/user1",
                json={"role": "INVALID_ROLE"},
                headers={"Authorization": "Bearer token123"}
            )

            # Pydantic validation catches invalid role pattern before reaching service
            assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
            data = response.json()
            # The error message will be from Pydantic validation
            assert "detail" in data

    def test_update_user_unexpected_error(self):
        """Test user update with unexpected error"""
        with patch('apps.user_app.get_current_user_id') as mock_get_user_id, \
             patch('apps.user_app.update_user') as mock_update_user:

            mock_get_user_id.return_value = ("updater123", "tenant1")
            mock_update_user.side_effect = Exception("Database connection failed")

            response = client.put(
                "/users/user1",
                json={"role": "ADMIN"},
                headers={"Authorization": "Bearer token123"}
            )

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert "Failed to update user" in data["detail"]
            assert "Database connection failed" in data["detail"]


class TestDeleteUserEndpoint:
    """Test delete_user_endpoint (DELETE /users/{user_id})"""

    def test_delete_user_success(self):
        """Test successful user deletion with complete cleanup"""
        with patch('apps.user_app.get_current_user_id') as mock_get_user_id, \
             patch('apps.user_app.get_user_tenant_by_user_id') as mock_get_tenant, \
             patch('apps.user_app.delete_user_and_cleanup') as mock_cleanup:

            mock_get_user_id.return_value = ("deleter123", "tenant1")
            mock_get_tenant.return_value = {"tenant_id": "tenant1", "user_id": "user1", "user_email": "user1@example.com"}
            mock_cleanup.return_value = None

            response = client.delete(
                "/users/user1",
                headers={"Authorization": "Bearer token123"}
            )

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "User deleted successfully"
            mock_get_user_id.assert_called_once_with("Bearer token123")
            mock_get_tenant.assert_called_once_with("user1")
            mock_cleanup.assert_called_once_with("user1", "tenant1")

    def test_delete_user_validation_error(self):
        """Test user deletion with user not found"""
        with patch('apps.user_app.get_current_user_id') as mock_get_user_id, \
             patch('apps.user_app.get_user_tenant_by_user_id') as mock_get_tenant:

            mock_get_user_id.return_value = ("deleter123", "tenant1")
            mock_get_tenant.return_value = None  # User not found

            response = client.delete(
                "/users/user1",
                headers={"Authorization": "Bearer token123"}
            )

            assert response.status_code == HTTPStatus.BAD_REQUEST
            data = response.json()
            assert "User user1 not found" in data["detail"]

    def test_delete_user_unexpected_error(self):
        """Test user deletion with unexpected error"""
        with patch('apps.user_app.get_current_user_id') as mock_get_user_id, \
             patch('apps.user_app.get_user_tenant_by_user_id') as mock_get_tenant, \
             patch('apps.user_app.delete_user_and_cleanup') as mock_cleanup:

            mock_get_user_id.return_value = ("deleter123", "tenant1")
            mock_get_tenant.return_value = {"tenant_id": "tenant1", "user_id": "user1", "user_email": "user1@example.com"}
            mock_cleanup.side_effect = Exception("Database connection failed")

            response = client.delete(
                "/users/user1",
                headers={"Authorization": "Bearer token123"}
            )

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert "Failed to delete user" in data["detail"]
            assert "Database connection failed" in data["detail"]


class TestDataValidation:
    """Test data validation for user endpoints"""

    def test_list_users_invalid_page(self):
        """Test list users with invalid page number"""
        response = client.post(
            "/users/list",
            json={"tenant_id": "tenant1", "page": 0, "page_size": 20}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_list_users_invalid_page_size(self):
        """Test list users with invalid page size"""
        response = client.post(
            "/users/list",
            json={"tenant_id": "tenant1", "page": 1, "page_size": 0}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_list_users_page_size_too_large(self):
        """Test list users with page size too large"""
        response = client.post(
            "/users/list",
            json={"tenant_id": "tenant1", "page": 1, "page_size": 101}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_update_user_invalid_role(self):
        """Test update user with invalid role pattern"""
        with patch('apps.user_app.get_current_user_id') as mock_get_user_id:
            mock_get_user_id.return_value = ("updater123", "tenant1")

            response = client.put(
                "/users/user1",
                json={"role": "invalid_role"},
                headers={"Authorization": "Bearer token123"}
            )

            # Pydantic validation catches invalid role pattern and returns 422
            assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_update_user_empty_update_data(self):
        """Test update user with empty update data"""
        with patch('apps.user_app.get_current_user_id') as mock_get_user_id, \
             patch('apps.user_app.update_user') as mock_update_user:

            mock_get_user_id.return_value = ("updater123", "tenant1")
            mock_update_user.return_value = {
                "id": "user1",
                "username": "user1@example.com",
                "role": "USER"
            }

            response = client.put(
                "/users/user1",
                json={},  # Empty update data
                headers={"Authorization": "Bearer token123"}
            )

            assert response.status_code == HTTPStatus.OK
            # Pydantic model converts empty dict to dict with None values for all optional fields
            mock_update_user.assert_called_once_with("user1", {"username": None, "email": None, "role": None}, "updater123")


if __name__ == "__main__":
    pytest.main([__file__])
