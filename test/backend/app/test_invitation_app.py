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
from consts.exceptions import NotFoundException, ValidationError, UnauthorizedError, DuplicateError
from consts.model import (
    InvitationCreateRequest, InvitationUpdateRequest, InvitationListRequest
)

# Import the modules we need
from fastapi.testclient import TestClient
from http import HTTPStatus
from fastapi import FastAPI

# Create a test client with a fresh FastAPI app
from apps.invitation_app import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestInvitationListing:
    """Test invitation listing endpoint"""

    def test_list_invitations_success(self):
        """Test successful invitation listing"""
        mock_result = [
            {
                "invitation_id": 1,
                "invitation_code": "ABC123",
                "code_type": "single_use",
                "tenant_id": "tenant-123",
                "capacity": 10,
                "used_count": 2
            },
            {
                "invitation_id": 2,
                "invitation_code": "DEF456",
                "code_type": "multi_use",
                "tenant_id": "tenant-123",
                "capacity": 50,
                "used_count": 15
            }
        ]

        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.get_invitations_list') as mock_list_invitations:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_list_invitations.return_value = mock_result

            request_data = {
                "tenant_id": "tenant-123",
                "page": 1,
                "page_size": 20
            }

            response = client.post("/invitations/list", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Invitation codes retrieved successfully"
            assert data["data"] == mock_result
            mock_get_user.assert_called_once_with("Bearer token")
            mock_list_invitations.assert_called_once_with(
                tenant_id="tenant-123",
                page=1,
                page_size=20,
                user_id="user-123",
                sort_by=None,
                sort_order=None
            )

    def test_list_invitations_with_sorting(self):
        """Test successful invitation listing with sorting parameters"""
        mock_result = [
            {
                "invitation_id": 1,
                "invitation_code": "ABC123",
                "code_type": "single_use",
                "tenant_id": "tenant-123",
                "capacity": 10,
                "used_count": 2,
                "update_time": "2024-01-02T10:00:00"
            }
        ]

        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.get_invitations_list') as mock_list_invitations:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_list_invitations.return_value = mock_result

            request_data = {
                "tenant_id": "tenant-123",
                "page": 1,
                "page_size": 20,
                "sort_by": "update_time",
                "sort_order": "desc"
            }

            response = client.post("/invitations/list", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Invitation codes retrieved successfully"
            assert data["data"] == mock_result
            mock_get_user.assert_called_once_with("Bearer token")
            mock_list_invitations.assert_called_once_with(
                tenant_id="tenant-123",
                page=1,
                page_size=20,
                user_id="user-123",
                sort_by="update_time",
                sort_order="desc"
            )

    def test_list_invitations_unauthorized(self):
        """Test invitation listing with unauthorized access"""
        with patch('apps.invitation_app.get_current_user_id') as mock_get_user:
            mock_get_user.side_effect = UnauthorizedError("Invalid token")

            request_data = {
                "tenant_id": "tenant-123",
                "page": 1,
                "page_size": 20
            }

            response = client.post("/invitations/list", json=request_data, headers={"Authorization": "Bearer invalid"})

            assert response.status_code == HTTPStatus.UNAUTHORIZED
            data = response.json()
            assert "Invalid token" in data["detail"]

    def test_list_invitations_unexpected_error(self):
        """Test invitation listing with unexpected error"""
        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.get_invitations_list') as mock_list_invitations:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_list_invitations.side_effect = Exception("Database error")

            request_data = {
                "tenant_id": "tenant-123",
                "page": 1,
                "page_size": 20
            }

            response = client.post("/invitations/list", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to retrieve invitation codes"


class TestInvitationCreation:
    """Test invitation creation endpoint"""

    def test_create_invitation_success(self):
        """Test successful invitation creation"""
        mock_invitation_info = {
            "invitation_id": 1,
            "invitation_code": "ABC123",
            "code_type": "single_use",
            "tenant_id": "tenant-123",
            "capacity": 10,
            "group_ids": [1, 2],
            "expiry_date": "2024-12-31T23:59:59Z",
            "created_by": "user-123"
        }

        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.create_invitation_code') as mock_create_invitation:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_create_invitation.return_value = mock_invitation_info

            request_data = {
                "tenant_id": "tenant-123",
                "code_type": "single_use",
                "invitation_code": "ABC123",
                "group_ids": [1, 2],
                "capacity": 10,
                "expiry_date": "2024-12-31T23:59:59Z"
            }

            response = client.post("/invitations", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.CREATED
            data = response.json()
            assert data["message"] == "Invitation code created successfully"
            assert data["data"] == mock_invitation_info

    def test_create_invitation_auto_generated_code(self):
        """Test invitation creation with auto-generated code"""
        mock_invitation_info = {
            "invitation_id": 1,
            "invitation_code": "AUTO456",
            "code_type": "multi_use",
            "tenant_id": "tenant-123",
            "capacity": 50
        }

        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.create_invitation_code') as mock_create_invitation:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_create_invitation.return_value = mock_invitation_info

            request_data = {
                "tenant_id": "tenant-123",
                "code_type": "multi_use",
                "capacity": 50
            }

            response = client.post("/invitations", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.CREATED
            data = response.json()
            assert data["data"]["invitation_code"] == "AUTO456"

    def test_create_invitation_user_not_found(self):
        """Test invitation creation when user is not found"""
        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.create_invitation_code') as mock_create_invitation:

            mock_get_user.return_value = ("user-999", "tenant-123")
            mock_create_invitation.side_effect = NotFoundException("User user-999 not found")

            request_data = {
                "tenant_id": "tenant-123",
                "code_type": "ADMIN_INVITE",
                "capacity": 10
            }

            response = client.post("/invitations", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "User user-999 not found" in data["detail"]

    def test_create_invitation_value_error(self):
        """Test invitation creation with value error"""
        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.create_invitation_code') as mock_create_invitation:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_create_invitation.side_effect = ValueError("Invalid code type")

            request_data = {
                "tenant_id": "tenant-123",
                "code_type": "invalid_type",
                "capacity": 10
            }

            response = client.post("/invitations", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.BAD_REQUEST
            data = response.json()
            assert "Invalid code type" in data["detail"]

    def test_create_invitation_duplicate_code(self):
        """Test invitation creation with duplicate invitation code returns 409 Conflict"""
        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.create_invitation_code') as mock_create_invitation:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_create_invitation.side_effect = DuplicateError("Invitation code 'ABC123' already exists")

            request_data = {
                "tenant_id": "tenant-123",
                "code_type": "ADMIN_INVITE",
                "invitation_code": "ABC123",
                "capacity": 10
            }

            response = client.post("/invitations", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.CONFLICT
            data = response.json()
            assert "Invitation code 'ABC123' already exists" in data["detail"]


class TestInvitationUpdate:
    """Test invitation update endpoint"""

    def test_update_invitation_success(self):
        """Test successful invitation update"""
        mock_invitation_info = {
            "invitation_id": 1,
            "invitation_code": "ABC123"
        }

        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation, \
             patch('apps.invitation_app.update_invitation_code') as mock_update_invitation:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_get_invitation.return_value = mock_invitation_info
            mock_update_invitation.return_value = True

            request_data = {
                "capacity": 20,
                "expiry_date": "2024-12-31T23:59:59Z"
            }

            response = client.put("/invitations/ABC123", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Invitation code updated successfully"
            mock_update_invitation.assert_called_once_with(
                invitation_id=1,
                updates={"capacity": 20, "expiry_date": "2024-12-31T23:59:59Z"},
                user_id="user-123"
            )

    def test_update_invitation_no_updates(self):
        """Test invitation update with no valid fields"""
        mock_invitation_info = {
            "invitation_id": 1,
            "invitation_code": "ABC123"
        }

        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_get_invitation.return_value = mock_invitation_info

            request_data = {}

            response = client.put("/invitations/ABC123", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.BAD_REQUEST
            data = response.json()
            assert "No valid fields provided for update" in data["detail"]

    def test_update_invitation_not_found(self):
        """Test invitation update when invitation doesn't exist"""
        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_get_invitation.return_value = None

            request_data = {"capacity": 20}

            response = client.put("/invitations/NOTFOUND", json=request_data, headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Invitation code NOTFOUND not found" in data["detail"]

    def test_update_invitation_unauthorized(self):
        """Test invitation update with unauthorized access"""
        with patch('apps.invitation_app.get_current_user_id') as mock_get_user:
            mock_get_user.side_effect = UnauthorizedError("Invalid token")

            request_data = {"capacity": 20}

            response = client.put("/invitations/ABC123", json=request_data, headers={"Authorization": "Bearer invalid"})

            assert response.status_code == HTTPStatus.UNAUTHORIZED
            data = response.json()
            assert "Invalid token" in data["detail"]


class TestInvitationRetrieval:
    """Test invitation retrieval endpoints"""

    def test_get_invitation_success(self):
        """Test successful invitation retrieval"""
        mock_invitation_info = {
            "invitation_id": 1,
            "invitation_code": "ABC123",
            "code_type": "single_use",
            "tenant_id": "tenant-123",
            "capacity": 10,
            "used_count": 2
        }

        with patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation:
            mock_get_invitation.return_value = mock_invitation_info

            response = client.get("/invitations/ABC123")

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Invitation code retrieved successfully"
            assert data["data"] == mock_invitation_info
            mock_get_invitation.assert_called_once_with("ABC123")

    def test_get_invitation_not_found(self):
        """Test invitation retrieval when invitation doesn't exist"""
        with patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation:
            mock_get_invitation.return_value = None

            response = client.get("/invitations/NOTFOUND")

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Invitation code NOTFOUND not found" in data["detail"]

    def test_get_invitation_unexpected_error(self):
        """Test invitation retrieval with unexpected error"""
        with patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation:
            mock_get_invitation.side_effect = Exception("Database error")

            response = client.get("/invitations/ABC123")

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to retrieve invitation code"


class TestInvitationCodeCheck:
    """Test invitation code check endpoint"""

    def test_check_invitation_code_exists(self):
        """Test checking invitation code that exists"""
        with patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation:
            mock_get_invitation.return_value = {
                "invitation_id": 1,
                "invitation_code": "ABC123",
                "code_type": "ADMIN_INVITE",
                "status": "IN_USE"
            }

            response = client.get("/invitations/ABC123/check")

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Invitation code check completed"
            assert data["data"]["invitation_code"] == "ABC123"
            assert data["data"]["exists"] is True
            mock_get_invitation.assert_called_once_with("ABC123")

    def test_check_invitation_code_not_exists(self):
        """Test checking invitation code that doesn't exist"""
        with patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation:
            mock_get_invitation.return_value = None

            response = client.get("/invitations/NOTFOUND/check")

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["data"]["invitation_code"] == "NOTFOUND"
            assert data["data"]["exists"] is False
            mock_get_invitation.assert_called_once_with("NOTFOUND")

    def test_check_invitation_code_unexpected_error(self):
        """Test checking invitation code with unexpected error"""
        with patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation:
            mock_get_invitation.side_effect = Exception("Database error")

            response = client.get("/invitations/ABC123/check")

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to check invitation code"


class TestInvitationAvailability:
    """Test invitation availability check endpoint"""

    def test_check_invitation_available_true(self):
        """Test invitation availability check when available"""
        with patch('apps.invitation_app.check_invitation_available') as mock_check_available:
            mock_check_available.return_value = True

            response = client.get("/invitations/ABC123/available")

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Invitation availability checked successfully"
            assert data["data"]["invitation_code"] == "ABC123"
            assert data["data"]["available"] is True
            mock_check_available.assert_called_once_with("ABC123")

    def test_check_invitation_available_false(self):
        """Test invitation availability check when not available"""
        with patch('apps.invitation_app.check_invitation_available') as mock_check_available:
            mock_check_available.return_value = False

            response = client.get("/invitations/ABC123/available")

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["data"]["available"] is False

    def test_check_invitation_available_unexpected_error(self):
        """Test invitation availability check with unexpected error"""
        with patch('apps.invitation_app.check_invitation_available') as mock_check_available:
            mock_check_available.side_effect = Exception("Database error")

            response = client.get("/invitations/ABC123/available")

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to check invitation availability"


class TestInvitationUsage:
    """Test invitation usage endpoint"""

    def test_use_invitation_success(self):
        """Test successful invitation usage"""
        mock_usage_result = {
            "invitation_code": "ABC123",
            "user_id": "user-456",
            "tenant_id": "tenant-123",
            "group_ids": [1, 2],
            "success": True
        }

        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.use_invitation_code') as mock_use_invitation:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_use_invitation.return_value = mock_usage_result

            response = client.post("/invitations/ABC123/use", headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Invitation code used successfully"
            assert data["data"] == mock_usage_result
            mock_use_invitation.assert_called_once_with(
                invitation_code="ABC123",
                user_id="user-456"
            )

    def test_use_invitation_not_found(self):
        """Test invitation usage when invitation doesn't exist"""
        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.use_invitation_code') as mock_use_invitation:

            mock_get_user.return_value = ("user-456", "tenant-123")
            mock_use_invitation.side_effect = NotFoundException("Invitation code not available")

            response = client.post("/invitations/INVALID/use", headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Invitation code not available" in data["detail"]

    def test_use_invitation_unauthorized(self):
        """Test invitation usage with unauthorized access"""
        with patch('apps.invitation_app.get_current_user_id') as mock_get_user:
            mock_get_user.side_effect = UnauthorizedError("Invalid token")

            response = client.post("/invitations/ABC123/use", headers={"Authorization": "Bearer invalid"})

            assert response.status_code == HTTPStatus.UNAUTHORIZED
            data = response.json()
            assert "Invalid token" in data["detail"]


class TestInvitationStatusUpdate:
    """Test invitation status update endpoint"""

    def test_update_invitation_status_success_updated(self):
        """Test successful invitation status update when status changed"""
        mock_invitation_info = {
            "invitation_id": 1,
            "invitation_code": "ABC123"
        }

        with patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation, \
             patch('apps.invitation_app.update_invitation_code_status') as mock_update_status:

            mock_get_invitation.return_value = mock_invitation_info
            mock_update_status.return_value = True

            response = client.post("/invitations/ABC123/update-status")

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Invitation status updated"
            assert data["data"]["invitation_code"] == "ABC123"
            assert data["data"]["status_updated"] is True
            mock_update_status.assert_called_once_with(1)

    def test_update_invitation_status_success_unchanged(self):
        """Test successful invitation status update when status unchanged"""
        mock_invitation_info = {
            "invitation_id": 1,
            "invitation_code": "ABC123"
        }

        with patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation, \
             patch('apps.invitation_app.update_invitation_code_status') as mock_update_status:

            mock_get_invitation.return_value = mock_invitation_info
            mock_update_status.return_value = False

            response = client.post("/invitations/ABC123/update-status")

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Invitation status unchanged"
            assert data["data"]["status_updated"] is False

    def test_update_invitation_status_not_found(self):
        """Test invitation status update when invitation doesn't exist"""
        with patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation:
            mock_get_invitation.return_value = None

            response = client.post("/invitations/NOTFOUND/update-status")

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Invitation code NOTFOUND not found" in data["detail"]

    def test_update_invitation_status_unexpected_error(self):
        """Test invitation status update with unexpected error"""
        mock_invitation_info = {
            "invitation_id": 1,
            "invitation_code": "ABC123"
        }

        with patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation, \
             patch('apps.invitation_app.update_invitation_code_status') as mock_update_status:

            mock_get_invitation.return_value = mock_invitation_info
            mock_update_status.side_effect = Exception("Database error")

            response = client.post("/invitations/ABC123/update-status")

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["detail"] == "Failed to update invitation status"


class TestInvitationDeletion:
    """Test invitation deletion endpoint"""

    def test_delete_invitation_success(self):
        """Test successful invitation deletion"""
        mock_invitation_info = {
            "invitation_id": 1,
            "invitation_code": "ABC123"
        }

        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation, \
             patch('apps.invitation_app.delete_invitation_code') as mock_delete_invitation:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_get_invitation.return_value = mock_invitation_info
            mock_delete_invitation.return_value = True

            response = client.delete("/invitations/ABC123", headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.OK
            data = response.json()
            assert data["message"] == "Invitation code deleted successfully"
            mock_delete_invitation.assert_called_once_with(
                invitation_id=1,
                user_id="user-123"
            )

    def test_delete_invitation_not_found(self):
        """Test invitation deletion when invitation doesn't exist"""
        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_get_invitation.return_value = None

            response = client.delete("/invitations/NOTFOUND", headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.NOT_FOUND
            data = response.json()
            assert "Invitation code NOTFOUND not found" in data["detail"]

    def test_delete_invitation_unauthorized(self):
        """Test invitation deletion with unauthorized access"""
        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.delete_invitation_code') as mock_delete_invitation:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_delete_invitation.side_effect = UnauthorizedError("User role USER not authorized to delete invitation codes")

            # Need a valid invitation code for the request
            mock_invitation_info = {"invitation_id": 1, "invitation_code": "ABC123"}

            with patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation:
                mock_get_invitation.return_value = mock_invitation_info

                response = client.delete("/invitations/ABC123", headers={"Authorization": "Bearer token"})

                assert response.status_code == HTTPStatus.UNAUTHORIZED
                data = response.json()
                assert "not authorized to delete invitation codes" in data["detail"]

    def test_delete_invitation_validation_error(self):
        """Test invitation deletion with validation error"""
        mock_invitation_info = {
            "invitation_id": 1,
            "invitation_code": "ABC123"
        }

        with patch('apps.invitation_app.get_current_user_id') as mock_get_user, \
             patch('apps.invitation_app.get_invitation_by_code') as mock_get_invitation, \
             patch('apps.invitation_app.delete_invitation_code') as mock_delete_invitation:

            mock_get_user.return_value = ("user-123", "tenant-123")
            mock_get_invitation.return_value = mock_invitation_info
            mock_delete_invitation.side_effect = ValidationError("Failed to delete invitation code")

            response = client.delete("/invitations/ABC123", headers={"Authorization": "Bearer token"})

            assert response.status_code == HTTPStatus.BAD_REQUEST
            data = response.json()
            assert "Failed to delete invitation code" in data["detail"]
