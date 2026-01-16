import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os
from typing import Optional

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

# Mock external dependencies
sys.modules['boto3'] = MagicMock()
sys.modules['psycopg2'] = MagicMock()
sys.modules['supabase'] = MagicMock()

# Apply critical patches before importing any modules
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()

patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('database.client.MinioClient', return_value=minio_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Import exception classes and models
from consts.exceptions import NotFoundException, ValidationError, UnauthorizedError
from consts.model import TenantCreateRequest, TenantUpdateRequest

# Import the modules we need
from fastapi.testclient import TestClient
from http import HTTPStatus
from fastapi import FastAPI

# Create a test client with a fresh FastAPI app
from apps.tenant_app import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestTenantCreation:
    """Test tenant creation endpoint"""

    def test_create_tenant_success(self):
        """Test successful tenant creation"""
        mock_tenant_info = {
            "tenant_id": "tenant-123",
            "tenant_name": "Test Tenant",
            "created_by": "user-456",
            "created_at": "2024-01-01T00:00:00Z"
        }

        with patch('apps.tenant_app.get_current_user_id') as mock_get_user, \
             patch('apps.tenant_app.create_tenant') as mock_create_tenant:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_create_tenant.return_value = mock_tenant_info

            request_data = {
                "tenant_name": "Test Tenant"
            }

            response = client.post("/tenants", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.CREATED
            data = response.json()
            assert data["message"] == "Tenant created successfully"
            assert data["data"] == mock_tenant_info
            mock_get_user.assert_called_once_with("Bearer token")
            mock_create_tenant.assert_called_once_with(
                tenant_name="Test Tenant",
                created_by="user-456"
            )

    def test_create_tenant_unauthorized(self):
        """Test tenant creation with unauthorized access"""
        with patch('apps.tenant_app.get_current_user_id') as mock_get_user:
            mock_get_user.side_effect = UnauthorizedError("Invalid token")

            request_data = {
                "tenant_name": "Test Tenant"
            }

            response = client.post("/tenants", json=request_data, headers={"Authorization": "Bearer invalid"})

            assert response.status_code == HTTPStatus.UNAUTHORIZED
            data = response.json()
            assert "Invalid token" in data["detail"]

    def test_create_tenant_validation_error(self):
        """Test tenant creation with validation error"""
        with patch('apps.tenant_app.get_current_user_id') as mock_get_user, \
             patch('apps.tenant_app.create_tenant') as mock_create_tenant:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_create_tenant.side_effect = ValidationError("Tenant name already exists")

            request_data = {
                "tenant_name": "Existing Tenant"
            }

            response = client.post("/tenants", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.BAD_REQUEST
            data = response.json()
            assert "Tenant name already exists" in data["detail"]

    def test_create_tenant_unexpected_error(self):
        """Test tenant creation with unexpected error"""
        with patch('apps.tenant_app.get_current_user_id') as mock_get_user, \
             patch('apps.tenant_app.create_tenant') as mock_create_tenant:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_create_tenant.side_effect = Exception("Database connection failed")

            request_data = {
                "tenant_name": "Test Tenant"
            }

            response = client.post("/tenants", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to create tenant"


class TestTenantRetrieval:
    """Test tenant retrieval endpoints"""

    def test_get_tenant_success(self):
        """Test successful tenant retrieval"""
        mock_tenant_info = {
            "tenant_id": "tenant-123",
            "tenant_name": "Test Tenant",
            "created_by": "user-456",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z"
        }

        with patch('apps.tenant_app.get_tenant_info') as mock_get_tenant:
            mock_get_tenant.return_value = mock_tenant_info

            response = client.get("/tenants/tenant-123")

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Tenant retrieved successfully"
            assert data["data"] == mock_tenant_info
            mock_get_tenant.assert_called_once_with("tenant-123")

    def test_get_tenant_not_found(self):
        """Test tenant retrieval when tenant doesn't exist"""
        with patch('apps.tenant_app.get_tenant_info') as mock_get_tenant:
            mock_get_tenant.side_effect = NotFoundException("Tenant tenant-999 not found")

            response = client.get("/tenants/tenant-999")

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Tenant tenant-999 not found" in data["detail"]

    def test_get_tenant_unexpected_error(self):
        """Test tenant retrieval with unexpected error"""
        with patch('apps.tenant_app.get_tenant_info') as mock_get_tenant:
            mock_get_tenant.side_effect = Exception("Database error")

            response = client.get("/tenants/tenant-123")

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to retrieve tenant"

    def test_get_all_tenants_success(self):
        """Test successful retrieval of all tenants"""
        mock_tenants = [
            {
                "tenant_id": "tenant-123",
                "tenant_name": "Tenant 1",
                "created_by": "user-456"
            },
            {
                "tenant_id": "tenant-456",
                "tenant_name": "Tenant 2",
                "created_by": "user-789"
            }
        ]

        with patch('apps.tenant_app.get_all_tenants') as mock_get_all_tenants:
            mock_get_all_tenants.return_value = mock_tenants

            response = client.get("/tenants")

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Tenants retrieved successfully"
            assert data["data"] == mock_tenants
            mock_get_all_tenants.assert_called_once()

    def test_get_all_tenants_unexpected_error(self):
        """Test retrieval of all tenants with unexpected error"""
        with patch('apps.tenant_app.get_all_tenants') as mock_get_all_tenants:
            mock_get_all_tenants.side_effect = Exception("Database error")

            response = client.get("/tenants")

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to retrieve tenants"


class TestTenantUpdate:
    """Test tenant update endpoint"""

    def test_update_tenant_success(self):
        """Test successful tenant update"""
        mock_updated_tenant = {
            "tenant_id": "tenant-123",
            "tenant_name": "Updated Tenant Name",
            "created_by": "user-456",
            "updated_by": "user-789",
            "updated_at": "2024-01-03T00:00:00Z"
        }

        with patch('apps.tenant_app.get_current_user_id') as mock_get_user, \
             patch('apps.tenant_app.update_tenant_info') as mock_update_tenant:

            mock_get_user.return_value = ("user-789", "tenant-123")
            mock_update_tenant.return_value = mock_updated_tenant

            request_data = {
                "tenant_name": "Updated Tenant Name"
            }

            response = client.put("/tenants/tenant-123", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Tenant updated successfully"
            assert data["data"] == mock_updated_tenant
            mock_get_user.assert_called_once_with("Bearer token")
            mock_update_tenant.assert_called_once_with(
                tenant_id="tenant-123",
                tenant_name="Updated Tenant Name",
                updated_by="user-789"
            )

    def test_update_tenant_not_found(self):
        """Test tenant update when tenant doesn't exist"""
        with patch('apps.tenant_app.get_current_user_id') as mock_get_user, \
             patch('apps.tenant_app.update_tenant_info') as mock_update_tenant:

            mock_get_user.return_value = ("user-789", "tenant-123")
            mock_update_tenant.side_effect = NotFoundException("Tenant tenant-999 not found")

            request_data = {
                "tenant_name": "Updated Name"
            }

            response = client.put("/tenants/tenant-999", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Tenant tenant-999 not found" in data["detail"]

    def test_update_tenant_validation_error(self):
        """Test tenant update with validation error"""
        with patch('apps.tenant_app.get_current_user_id') as mock_get_user, \
             patch('apps.tenant_app.update_tenant_info') as mock_update_tenant:

            mock_get_user.return_value = ("user-789", "tenant-123")
            mock_update_tenant.side_effect = ValidationError("Tenant name already exists")

            request_data = {
                "tenant_name": "Existing Name"
            }

            response = client.put("/tenants/tenant-123", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.BAD_REQUEST
            data = response.json()
            assert "Tenant name already exists" in data["detail"]

    def test_update_tenant_unauthorized(self):
        """Test tenant update with unauthorized access"""
        with patch('apps.tenant_app.get_current_user_id') as mock_get_user:
            mock_get_user.side_effect = UnauthorizedError("Invalid token")

            request_data = {
                "tenant_name": "Updated Name"
            }

            response = client.put("/tenants/tenant-123", json=request_data, headers={"Authorization": "Bearer invalid"})

            assert response.status_code == HTTPStatus.UNAUTHORIZED
            data = response.json()
            assert "Invalid token" in data["detail"]

    def test_update_tenant_unexpected_error(self):
        """Test tenant update with unexpected error"""
        with patch('apps.tenant_app.get_current_user_id') as mock_get_user, \
             patch('apps.tenant_app.update_tenant_info') as mock_update_tenant:

            mock_get_user.return_value = ("user-789", "tenant-123")
            mock_update_tenant.side_effect = Exception("Database error")

            request_data = {
                "tenant_name": "Updated Name"
            }

            response = client.put("/tenants/tenant-123", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to update tenant"


class TestTenantDeletion:
    """Test tenant deletion endpoint"""

    def test_delete_tenant_not_implemented(self):
        """Test tenant deletion returns not implemented"""
        with patch('apps.tenant_app.get_current_user_id') as mock_get_user:
            mock_get_user.return_value = ("user-789", "tenant-123")

            response = client.delete("/tenants/tenant-123", headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.NOT_IMPLEMENTED
            data = response.json()
            assert "Tenant deletion is not yet implemented" in data["detail"]

    def test_delete_tenant_unauthorized(self):
        """Test tenant deletion with unauthorized access"""
        with patch('apps.tenant_app.get_current_user_id') as mock_get_user:
            mock_get_user.side_effect = UnauthorizedError("Invalid token")

            response = client.delete("/tenants/tenant-123", headers={"Authorization": "Bearer invalid"})

            assert response.status_code == HTTPStatus.UNAUTHORIZED
            data = response.json()
            assert "Invalid token" in data["detail"]

    def test_delete_tenant_unexpected_error(self):
        """Test tenant deletion with unexpected error during auth"""
        with patch('apps.tenant_app.get_current_user_id') as mock_get_user:
            mock_get_user.side_effect = Exception("Auth service error")

            response = client.delete("/tenants/tenant-123", headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to delete tenant"

