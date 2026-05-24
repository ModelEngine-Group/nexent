"""
Unit tests for backend.apps.tenant_app module.
"""
import sys
import os

# Add test/backend/app to sys.path for conftest import
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Import conftest from the same directory to set up mocks
import conftest  # noqa: F401 - needed for module-level mocks

# Add backend path for backend imports
backend_path = os.path.join(current_dir, "../../../backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from http import HTTPStatus

from fastapi.testclient import TestClient
from fastapi import FastAPI

from apps.tenant_app import router
from consts.exceptions import NotFoundException, ValidationError, UnauthorizedError


app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestCreateTenantEndpoint:
    """Test POST /tenants endpoint"""

    def test_create_tenant_success(self, mocker):
        """Test successful tenant creation"""
        mock_tenant_info = {
            "tenant_id": "tenant-123",
            "tenant_name": "Test Tenant",
            "created_by": "user-456",
            "created_at": "2024-01-01T00:00:00Z"
        }

        mocker.patch("apps.tenant_app.get_current_user_id", return_value=("user-456", "tenant-123"))
        mocker.patch("apps.tenant_app.create_tenant", return_value=mock_tenant_info)

        response = client.post(
            "/tenants",
            json={"tenant_name": "Test Tenant"},
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        assert data["message"] == "Tenant created successfully"
        assert data["data"] == mock_tenant_info

    def test_create_tenant_with_all_fields(self, mocker):
        """Test tenant creation with skill_ids, skill_names, and locale"""
        mock_tenant_info = {
            "tenant_id": "tenant-123",
            "tenant_name": "Test Tenant",
            "created_by": "user-456",
            "created_at": "2024-01-01T00:00:00Z"
        }

        mocker.patch("apps.tenant_app.get_current_user_id", return_value=("user-456", "tenant-123"))
        mock_create = mocker.patch("apps.tenant_app.create_tenant", return_value=mock_tenant_info)

        response = client.post(
            "/tenants",
            json={
                "tenant_name": "Test Tenant",
                "skill_ids": [1, 2],
                "skill_names": ["skill-a", "skill-b"],
                "locale": "en"
            },
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.CREATED
        mock_create.assert_called_once_with(
            tenant_name="Test Tenant",
            created_by="user-456",
            skill_ids=[1, 2],
            skill_names=["skill-a", "skill-b"],
            locale="en"
        )

    def test_create_tenant_unauthorized(self, mocker):
        """Test tenant creation with invalid token"""
        mocker.patch("apps.tenant_app.get_current_user_id", side_effect=UnauthorizedError("Invalid token"))

        response = client.post(
            "/tenants",
            json={"tenant_name": "Test Tenant"},
            headers={"Authorization": "Bearer invalid"}
        )

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert "Invalid token" in response.json()["detail"]

    def test_create_tenant_validation_error(self, mocker):
        """Test tenant creation with validation error"""
        mocker.patch("apps.tenant_app.get_current_user_id", return_value=("user-456", "tenant-123"))
        mocker.patch("apps.tenant_app.create_tenant", side_effect=ValidationError("Tenant name already exists"))

        response = client.post(
            "/tenants",
            json={"tenant_name": "Existing Tenant"},
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "Tenant name already exists" in response.json()["detail"]

    def test_create_tenant_unexpected_error(self, mocker):
        """Test tenant creation with unexpected error"""
        mocker.patch("apps.tenant_app.get_current_user_id", return_value=("user-456", "tenant-123"))
        mocker.patch("apps.tenant_app.create_tenant", side_effect=Exception("Database connection failed"))

        response = client.post(
            "/tenants",
            json={"tenant_name": "Test Tenant"},
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Failed to create tenant"


class TestGetTenantEndpoint:
    """Test GET /tenants/{tenant_id} endpoint"""

    def test_get_tenant_success(self, mocker):
        """Test successful tenant retrieval"""
        mock_tenant_info = {
            "tenant_id": "tenant-123",
            "tenant_name": "Test Tenant",
            "created_by": "user-456",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z"
        }

        mocker.patch("apps.tenant_app.get_tenant_info", return_value=mock_tenant_info)

        response = client.get("/tenants/tenant-123")

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Tenant retrieved successfully"
        assert data["data"] == mock_tenant_info

    def test_get_tenant_not_found(self, mocker):
        """Test tenant retrieval when tenant doesn't exist"""
        mocker.patch("apps.tenant_app.get_tenant_info", side_effect=NotFoundException("Tenant tenant-999 not found"))

        response = client.get("/tenants/tenant-999")

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert "Tenant tenant-999 not found" in response.json()["detail"]

    def test_get_tenant_unexpected_error(self, mocker):
        """Test tenant retrieval with unexpected error"""
        mocker.patch("apps.tenant_app.get_tenant_info", side_effect=Exception("Database error"))

        response = client.get("/tenants/tenant-123")

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Failed to retrieve tenant"


class TestGetAllTenantsEndpoint:
    """Test POST /tenants/tenant-list endpoint"""

    def test_get_all_tenants_success(self, mocker):
        """Test successful retrieval of all tenants with pagination"""
        mock_tenants = [
            {"tenant_id": "tenant-123", "tenant_name": "Tenant 1", "created_by": "user-456"},
            {"tenant_id": "tenant-456", "tenant_name": "Tenant 2", "created_by": "user-789"}
        ]

        mocker.patch("apps.tenant_app.get_tenants_paginated", return_value={
            "data": mock_tenants,
            "total": 2,
            "page": 1,
            "page_size": 20,
            "total_pages": 1
        })

        response = client.post("/tenants/tenant-list", json={"page": 1, "page_size": 20})

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Tenants retrieved successfully"
        assert data["data"] == mock_tenants
        assert data["total"] == 2
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert data["total_pages"] == 1

    def test_get_all_tenants_pagination(self, mocker):
        """Test tenant list with custom pagination parameters"""
        mocker.patch("apps.tenant_app.get_tenants_paginated", return_value={
            "data": [],
            "total": 100,
            "page": 2,
            "page_size": 10,
            "total_pages": 10
        })

        response = client.post("/tenants/tenant-list", json={"page": 2, "page_size": 10})

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["page"] == 2
        assert data["page_size"] == 10
        assert data["total"] == 100
        assert data["total_pages"] == 10

    def test_get_all_tenants_unexpected_error(self, mocker):
        """Test retrieval of all tenants with unexpected error"""
        mocker.patch("apps.tenant_app.get_tenants_paginated", side_effect=Exception("Database error"))

        response = client.post("/tenants/tenant-list", json={"page": 1, "page_size": 20})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Failed to retrieve tenants"


class TestUpdateTenantEndpoint:
    """Test PUT /tenants/{tenant_id} endpoint"""

    def test_update_tenant_success(self, mocker):
        """Test successful tenant update"""
        mock_updated_tenant = {
            "tenant_id": "tenant-123",
            "tenant_name": "Updated Tenant Name",
            "created_by": "user-456",
            "updated_by": "user-789",
            "updated_at": "2024-01-03T00:00:00Z"
        }

        mocker.patch("apps.tenant_app.get_current_user_id", return_value=("user-789", "tenant-123"))
        mocker.patch("apps.tenant_app.update_tenant_info", return_value=mock_updated_tenant)

        response = client.put(
            "/tenants/tenant-123",
            json={"tenant_name": "Updated Tenant Name"},
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Tenant updated successfully"
        assert data["data"] == mock_updated_tenant

    def test_update_tenant_not_found(self, mocker):
        """Test tenant update when tenant doesn't exist"""
        mocker.patch("apps.tenant_app.get_current_user_id", return_value=("user-789", "tenant-123"))
        mocker.patch("apps.tenant_app.update_tenant_info", side_effect=NotFoundException("Tenant tenant-999 not found"))

        response = client.put(
            "/tenants/tenant-999",
            json={"tenant_name": "Updated Name"},
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert "Tenant tenant-999 not found" in response.json()["detail"]

    def test_update_tenant_validation_error(self, mocker):
        """Test tenant update with validation error"""
        mocker.patch("apps.tenant_app.get_current_user_id", return_value=("user-789", "tenant-123"))
        mocker.patch("apps.tenant_app.update_tenant_info", side_effect=ValidationError("Tenant name already exists"))

        response = client.put(
            "/tenants/tenant-123",
            json={"tenant_name": "Existing Name"},
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "Tenant name already exists" in response.json()["detail"]

    def test_update_tenant_unauthorized(self, mocker):
        """Test tenant update with unauthorized access"""
        mocker.patch("apps.tenant_app.get_current_user_id", side_effect=UnauthorizedError("Invalid token"))

        response = client.put(
            "/tenants/tenant-123",
            json={"tenant_name": "Updated Name"},
            headers={"Authorization": "Bearer invalid"}
        )

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert "Invalid token" in response.json()["detail"]

    def test_update_tenant_unexpected_error(self, mocker):
        """Test tenant update with unexpected error"""
        mocker.patch("apps.tenant_app.get_current_user_id", return_value=("user-789", "tenant-123"))
        mocker.patch("apps.tenant_app.update_tenant_info", side_effect=Exception("Database error"))

        response = client.put(
            "/tenants/tenant-123",
            json={"tenant_name": "Updated Name"},
            headers={"Authorization": "Bearer token"}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Failed to update tenant"


class TestDeleteTenantEndpoint:
    """Test DELETE /tenants/{tenant_id} endpoint"""

    def test_delete_tenant_success(self, mocker):
        """Test successful tenant deletion"""
        mocker.patch("apps.tenant_app.get_current_user_id", return_value=("user-789", "tenant-123"))
        mock_delete = mocker.patch("apps.tenant_app.delete_tenant", new_callable=AsyncMock, return_value=True)

        response = client.delete("/tenants/tenant-123", headers={"Authorization": "Bearer token"})

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["message"] == "Tenant deleted successfully"
        assert data["data"]["tenant_id"] == "tenant-123"

    def test_delete_tenant_not_found(self, mocker):
        """Test tenant deletion when tenant doesn't exist"""
        mocker.patch("apps.tenant_app.get_current_user_id", return_value=("user-789", "tenant-123"))
        mocker.patch("apps.tenant_app.delete_tenant", new_callable=AsyncMock, side_effect=NotFoundException("Tenant tenant-999 not found"))

        response = client.delete("/tenants/tenant-999", headers={"Authorization": "Bearer token"})

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert "Tenant tenant-999 not found" in response.json()["detail"]

    def test_delete_tenant_validation_error(self, mocker):
        """Test tenant deletion with validation error"""
        mocker.patch("apps.tenant_app.get_current_user_id", return_value=("user-789", "tenant-123"))
        mocker.patch("apps.tenant_app.delete_tenant", new_callable=AsyncMock, side_effect=ValidationError("Cannot delete tenant with active resources"))

        response = client.delete("/tenants/tenant-123", headers={"Authorization": "Bearer token"})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "Cannot delete tenant with active resources" in response.json()["detail"]

    def test_delete_tenant_unauthorized(self, mocker):
        """Test tenant deletion with unauthorized access"""
        mocker.patch("apps.tenant_app.get_current_user_id", side_effect=UnauthorizedError("Invalid token"))

        response = client.delete("/tenants/tenant-123", headers={"Authorization": "Bearer invalid"})

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert "Invalid token" in response.json()["detail"]

    def test_delete_tenant_unexpected_error(self, mocker):
        """Test tenant deletion with unexpected error"""
        mocker.patch("apps.tenant_app.get_current_user_id", return_value=("user-789", "tenant-123"))
        mocker.patch("apps.tenant_app.delete_tenant", new_callable=AsyncMock, side_effect=Exception("Database error"))

        response = client.delete("/tenants/tenant-123", headers={"Authorization": "Bearer token"})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Failed to delete tenant"
