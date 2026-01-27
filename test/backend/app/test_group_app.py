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
from consts.model import (
    GroupCreateRequest, GroupUpdateRequest,
    GroupUserRequest, GroupListRequest, SetDefaultGroupRequest,
    GroupMembersUpdateRequest
)

# Import the modules we need
from fastapi.testclient import TestClient
from http import HTTPStatus
from fastapi import FastAPI

# Create a test client with a fresh FastAPI app
from apps.group_app import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestGroupCreation:
    """Test group creation endpoint"""

    def test_create_group_success(self):
        """Test successful group creation"""
        mock_group_info = {
            "group_id": 1,
            "group_name": "Test Group",
            "group_description": "Test Description",
            "tenant_id": "tenant-123",
            "created_by": "user-123"
        }

        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.create_group') as mock_create_group:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_create_group.return_value = mock_group_info

            request_data = {
                "tenant_id": "tenant-123",
                "group_name": "Test Group",
                "group_description": "Test Description"
            }

            response = client.post("/groups", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.CREATED
            data = response.json()
            assert data["message"] == "Group created successfully"
            assert data["data"] == mock_group_info
            mock_get_user.assert_called_once_with("Bearer token")
            mock_create_group.assert_called_once_with(
                tenant_id="tenant-123",
                group_name="Test Group",
                group_description="Test Description",
                user_id="user-123"
            )

    def test_create_group_unauthorized(self):
        """Test group creation with unauthorized access"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user:
            mock_get_user.side_effect = UnauthorizedError("Invalid token")

            request_data = {
                "tenant_id": "tenant-123",
                "group_name": "Test Group",
                "group_description": "Test Description"
            }

            response = client.post("/groups", json=request_data, headers={"Authorization": "Bearer invalid"})

            assert response.status_code == HTTPStatus.UNAUTHORIZED
            data = response.json()
            assert "Invalid token" in data["detail"]

    def test_create_group_validation_error(self):
        """Test group creation with validation error from service layer"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.create_group') as mock_create_group:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_create_group.side_effect = ValidationError("Group name already exists")

            request_data = {
                "tenant_id": "tenant-123",
                "group_name": "Existing Group",
                "group_description": "Test Description"
            }

            response = client.post("/groups", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.BAD_REQUEST
            data = response.json()
            assert "Group name already exists" in data["detail"]

    def test_create_group_unexpected_error(self):
        """Test group creation with unexpected error"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.create_group') as mock_create_group:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_create_group.side_effect = Exception("Database connection failed")

            request_data = {
                "tenant_id": "tenant-123",
                "group_name": "Test Group",
                "group_description": "Test Description"
            }

            response = client.post("/groups", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to create group"


class TestGroupRetrieval:
    """Test group retrieval endpoints"""

    def test_get_group_success(self):
        """Test successful group retrieval"""
        mock_group_info = {
            "group_id": 1,
            "group_name": "Test Group",
            "group_description": "Test Description",
            "tenant_id": "tenant-123"
        }

        with patch('apps.group_app.get_group_info') as mock_get_group:
            mock_get_group.return_value = mock_group_info

            response = client.get("/groups/1")

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Group retrieved successfully"
            assert data["data"] == mock_group_info
            mock_get_group.assert_called_once_with(1)

    def test_get_group_not_found(self):
        """Test group retrieval when group doesn't exist"""
        with patch('apps.group_app.get_group_info') as mock_get_group:
            mock_get_group.return_value = None

            response = client.get("/groups/999")

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Group 999 not found" in data["detail"]

    def test_get_group_unexpected_error(self):
        """Test group retrieval with unexpected error"""
        with patch('apps.group_app.get_group_info') as mock_get_group:
            mock_get_group.side_effect = Exception("Database error")

            response = client.get("/groups/1")

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to retrieve group"


class TestGroupListing:
    """Test group listing endpoint"""

    def test_get_groups_success(self):
        """Test successful group listing"""
        mock_groups = [
            {"group_id": 1, "group_name": "Group 1"},
            {"group_id": 2, "group_name": "Group 2"}
        ]
        mock_result = {"groups": mock_groups, "total": 2}

        with patch('apps.group_app.get_tenant_info') as mock_get_tenant, \
             patch('apps.group_app.get_groups_by_tenant') as mock_get_groups:

            mock_get_tenant.return_value = {"tenant_id": "tenant-123"}
            mock_get_groups.return_value = mock_result

            request_data = {
                "tenant_id": "tenant-123",
                "page": 1,
                "page_size": 20
            }

            response = client.post("/groups/list", json=request_data)

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Groups retrieved successfully"
            assert data["data"] == mock_groups
            assert data["pagination"]["page"] == 1
            assert data["pagination"]["page_size"] == 20
            assert data["pagination"]["total"] == 2
            assert data["pagination"]["total_pages"] == 1

    def test_get_groups_tenant_not_found(self):
        """Test group listing when tenant doesn't exist"""
        with patch('apps.group_app.get_tenant_info') as mock_get_tenant:
            mock_get_tenant.side_effect = NotFoundException("Tenant not found")

            request_data = {
                "tenant_id": "invalid-tenant",
                "page": 1,
                "page_size": 20
            }

            response = client.post("/groups/list", json=request_data)

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Tenant not found" in data["detail"]

    def test_get_groups_unexpected_error(self):
        """Test group listing with unexpected error"""
        with patch('apps.group_app.get_tenant_info') as mock_get_tenant, \
             patch('apps.group_app.get_groups_by_tenant') as mock_get_groups:

            mock_get_tenant.return_value = {"tenant_id": "tenant-123"}
            mock_get_groups.side_effect = Exception("Database error")

            request_data = {
                "tenant_id": "tenant-123",
                "page": 1,
                "page_size": 20
            }

            response = client.post("/groups/list", json=request_data)

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to retrieve groups"


class TestGroupUpdate:
    """Test group update endpoint"""

    def test_update_group_success(self):
        """Test successful group update"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.update_group') as mock_update_group:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_update_group.return_value = True

            request_data = {
                "group_name": "Updated Group",
                "group_description": "Updated Description"
            }

            response = client.put("/groups/1", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Group updated successfully"
            mock_update_group.assert_called_once_with(
                group_id=1,
                updates={"group_name": "Updated Group", "group_description": "Updated Description"},
                user_id="user-123"
            )

    def test_update_group_no_updates(self):
        """Test group update with no valid fields"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user:
            mock_get_user.return_value = ("user-123", "tenant-123")

            request_data = {}

            response = client.put("/groups/1", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.BAD_REQUEST
            data = response.json()
            assert "No valid fields provided for update" in data["detail"]

    def test_update_group_not_found(self):
        """Test group update when group doesn't exist"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.update_group') as mock_update_group:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_update_group.side_effect = NotFoundException("Group not found")

            request_data = {"group_name": "Updated Group"}

            response = client.put("/groups/999", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Group not found" in data["detail"]

    def test_update_group_unauthorized(self):
        """Test group update with unauthorized access"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user:
            mock_get_user.side_effect = UnauthorizedError("Invalid token")

            request_data = {"group_name": "Updated Group"}

            response = client.put("/groups/1", json=request_data, headers={"Authorization": "Bearer invalid"})

            assert response.status_code == HTTPStatus.UNAUTHORIZED
            data = response.json()
            assert "Invalid token" in data["detail"]


class TestGroupDeletion:
    """Test group deletion endpoint"""

    def test_delete_group_success(self):
        """Test successful group deletion"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.delete_group') as mock_delete_group:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_delete_group.return_value = True

            response = client.delete("/groups/1", headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Group deleted successfully"
            mock_delete_group.assert_called_once_with(group_id=1, user_id="user-123")

    def test_delete_group_not_found(self):
        """Test group deletion when group doesn't exist"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.delete_group') as mock_delete_group:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_delete_group.side_effect = NotFoundException("Group not found")

            response = client.delete("/groups/999", headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Group not found" in data["detail"]

    def test_delete_group_validation_error(self):
        """Test group deletion with validation error"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.delete_group') as mock_delete_group:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_delete_group.side_effect = ValidationError("Cannot delete group with active members")

            response = client.delete("/groups/1", headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.BAD_REQUEST
            data = response.json()
            assert "Cannot delete group with active members" in data["detail"]


class TestGroupMembership:
    """Test group membership endpoints"""

    def test_add_user_to_group_success(self):
        """Test successful user addition to group"""
        mock_result = {"user_id": "user-123", "group_id": 1}

        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.add_user_to_single_group') as mock_add_user:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_add_user.return_value = mock_result

            request_data = {"user_id": "user-123"}

            response = client.post("/groups/1/members", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "User added to group successfully"
            assert data["data"] == mock_result

    def test_add_user_to_group_invalid_request(self):
        """Test user addition with invalid request (group_ids provided)"""
        request_data = {
            "user_id": "user-123",
            "group_ids": [1, 2]
        }

        response = client.post("/groups/1/members", json=request_data, headers={"Authorization": "Bearer token"})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "group_ids should not be provided" in data["detail"]

    def test_add_user_to_group_not_found(self):
        """Test user addition when group or user doesn't exist"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.add_user_to_single_group') as mock_add_user:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_add_user.side_effect = NotFoundException("Group not found")

            request_data = {"user_id": "user-123"}

            response = client.post("/groups/999/members", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Group not found" in data["detail"]

    def test_remove_user_from_group_success(self):
        """Test successful user removal from group"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.remove_user_from_single_group') as mock_remove_user:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_remove_user.return_value = True

            response = client.delete("/groups/1/members/user-123", headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "User removed from group successfully"

    def test_remove_user_from_group_not_found(self):
        """Test user removal when group or user doesn't exist"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.remove_user_from_single_group') as mock_remove_user:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_remove_user.side_effect = NotFoundException("User not in group")

            response = client.delete("/groups/1/members/user-999", headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "User not in group" in data["detail"]

    def test_get_group_users_success(self):
        """Test successful retrieval of group users"""
        mock_users = [
            {"user_id": "user-1", "email": "user1@example.com"},
            {"user_id": "user-2", "email": "user2@example.com"}
        ]

        with patch('apps.group_app.get_group_users') as mock_get_users:
            mock_get_users.return_value = mock_users

            response = client.get("/groups/1/members")

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Group users retrieved successfully"
            assert data["data"] == mock_users

    def test_get_group_users_not_found(self):
        """Test group users retrieval when group doesn't exist"""
        with patch('apps.group_app.get_group_users') as mock_get_users:
            mock_get_users.side_effect = NotFoundException("Group not found")

            response = client.get("/groups/999/members")

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Group not found" in data["detail"]

    def test_update_group_members_success(self):
        """Test successful group members update"""
        mock_result = {
            "added": 2,
            "removed": 1,
            "unchanged": 3
        }

        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.update_group_members') as mock_update_members:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_update_members.return_value = mock_result

            request_data = {
                "user_ids": ["user-1", "user-2", "user-3"]
            }

            response = client.put("/groups/1/members", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Group members updated successfully"
            assert data["data"] == mock_result
            mock_update_members.assert_called_once_with(
                group_id=1,
                user_ids=["user-1", "user-2", "user-3"],
                current_user_id="user-456"
            )

    def test_update_group_members_not_found(self):
        """Test group members update when group doesn't exist"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.update_group_members') as mock_update_members:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_update_members.side_effect = NotFoundException("Group not found")

            request_data = {"user_ids": ["user-1", "user-2"]}

            response = client.put("/groups/999/members", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Group not found" in data["detail"]

    def test_update_group_members_validation_error(self):
        """Test group members update with validation error"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.update_group_members') as mock_update_members:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_update_members.side_effect = ValidationError("Invalid user IDs provided")

            request_data = {"user_ids": ["invalid-user"]}

            response = client.put("/groups/1/members", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.BAD_REQUEST
            data = response.json()
            assert "Invalid user IDs provided" in data["detail"]

    def test_update_group_members_unauthorized(self):
        """Test group members update with unauthorized access"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user:
            mock_get_user.side_effect = UnauthorizedError("Invalid token")

            request_data = {"user_ids": ["user-1", "user-2"]}

            response = client.put("/groups/1/members", json=request_data, headers={"Authorization": "Bearer invalid"})

            assert response.status_code == HTTPStatus.UNAUTHORIZED
            data = response.json()
            assert "Invalid token" in data["detail"]

    def test_update_group_members_service_unauthorized(self):
        """Test group members update with service-level unauthorized error"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.update_group_members') as mock_update_members:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_update_members.side_effect = UnauthorizedError("User does not have permission to update group members")

            request_data = {"user_ids": ["user-1", "user-2"]}

            response = client.put("/groups/1/members", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.UNAUTHORIZED
            data = response.json()
            assert "User does not have permission to update group members" in data["detail"]

    def test_update_group_members_unexpected_error(self):
        """Test group members update with unexpected error"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.update_group_members') as mock_update_members:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_update_members.side_effect = Exception("Database connection failed")

            request_data = {"user_ids": ["user-1", "user-2"]}

            response = client.put("/groups/1/members", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to update group members"


class TestBatchGroupMembership:
    """Test batch group membership endpoint"""

    def test_add_user_to_groups_success(self):
        """Test successful batch user addition to groups"""
        mock_results = [
            {"user_id": "user-123", "group_id": 1, "success": True},
            {"user_id": "user-123", "group_id": 2, "success": True}
        ]

        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.add_user_to_groups') as mock_add_batch:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_add_batch.return_value = mock_results

            request_data = {
                "user_id": "user-123",
                "group_ids": [1, 2]
            }

            response = client.post("/groups/members/batch", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Batch user addition completed"
            assert data["data"] == mock_results

    def test_add_user_to_groups_invalid_request(self):
        """Test batch user addition with invalid request (no group_ids)"""
        request_data = {"user_id": "user-123"}

        response = client.post("/groups/members/batch", json=request_data, headers={"Authorization": "Bearer token"})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert "group_ids is required for batch operations" in data["detail"]

    def test_add_user_to_groups_validation_error(self):
        """Test batch user addition with validation error"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.add_user_to_groups') as mock_add_batch:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_add_batch.side_effect = ValidationError("Invalid group IDs")

            request_data = {
                "user_id": "user-123",
                "group_ids": [1, 2]
            }

            response = client.post("/groups/members/batch", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.BAD_REQUEST
            data = response.json()
            assert "Invalid group IDs" in data["detail"]


class TestDefaultGroupManagement:
    """Test default group management endpoints"""

    def test_get_tenant_default_group_success(self):
        """Test successful retrieval of tenant default group"""
        with patch('apps.group_app.get_tenant_default_group_id') as mock_get_default:
            mock_get_default.return_value = 1

            response = client.get("/groups/tenants/tenant-123/default")

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Default group ID retrieved successfully"
            assert data["data"]["tenant_id"] == "tenant-123"
            assert data["data"]["default_group_id"] == 1

    def test_get_tenant_default_group_unexpected_error(self):
        """Test tenant default group retrieval with unexpected error"""
        with patch('apps.group_app.get_tenant_default_group_id') as mock_get_default:
            mock_get_default.side_effect = Exception("Database error")

            response = client.get("/groups/tenants/tenant-123/default")

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to retrieve default group"

    def test_set_tenant_default_group_success(self):
        """Test successful setting of tenant default group"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.set_tenant_default_group_id') as mock_set_default:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_set_default.return_value = True

            request_data = {"default_group_id": 2}

            response = client.put("/groups/tenants/tenant-123/default", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Default group set successfully"
            assert data["data"]["tenant_id"] == "tenant-123"
            assert data["data"]["default_group_id"] == 2

    def test_set_tenant_default_group_validation_error(self):
        """Test setting tenant default group with validation error"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.set_tenant_default_group_id') as mock_set_default:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_set_default.side_effect = ValidationError("Group does not belong to tenant")

            request_data = {"default_group_id": 999}

            response = client.put("/groups/tenants/tenant-123/default", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.BAD_REQUEST
            data = response.json()
            assert "Group does not belong to tenant" in data["detail"]

    def test_set_tenant_default_group_not_found(self):
        """Test setting tenant default group when tenant doesn't exist"""
        with patch('apps.group_app.get_current_user_id') as mock_get_user, \
             patch('apps.group_app.set_tenant_default_group_id') as mock_set_default:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_set_default.side_effect = NotFoundException("Tenant not found")

            request_data = {"default_group_id": 2}

            response = client.put("/groups/tenants/invalid-tenant/default", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Tenant not found" in data["detail"]
