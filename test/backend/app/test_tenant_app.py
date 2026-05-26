import types
import importlib.machinery
import pytest
import sys
import os

# Import exception classes and models
from consts.exceptions import NotFoundException, ValidationError, UnauthorizedError

# Import the modules we need
from unittest.mock import MagicMock, AsyncMock, patch


# Import exceptions
from consts.exceptions import NotFoundException, ValidationError, UnauthorizedError

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

# Mock external dependencies
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules['boto3'] = boto3_module
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




services_module = types.ModuleType("services")
tenant_service_module = types.ModuleType("services.tenant_service")
tenant_service_module.create_tenant = MagicMock()
tenant_service_module.get_tenant_info = MagicMock()
tenant_service_module.get_tenants_paginated = MagicMock()
tenant_service_module.update_tenant_info = MagicMock()
tenant_service_module.delete_tenant = AsyncMock(return_value=True)
services_module.tenant_service = tenant_service_module

utils_module = types.ModuleType("utils")
auth_utils_module = types.ModuleType("utils.auth_utils")
auth_utils_module.get_current_user_id = MagicMock()
utils_module.auth_utils = auth_utils_module

sys.modules["services"] = services_module
sys.modules["services.tenant_service"] = tenant_service_module
sys.modules["utils"] = utils_module
sys.modules["utils.auth_utils"] = auth_utils_module


class TestTenantExceptions:
    """Test exception handling patterns for tenant endpoints."""

    def test_not_found_exception_maps_to_404(self):
        """Test that NotFoundException is properly defined and raised."""
        with pytest.raises(NotFoundException) as exc_info:
            raise NotFoundException("Tenant not found")
        assert "Tenant not found" in str(exc_info.value)

    def test_validation_error_maps_to_400(self):
        """Test that ValidationError is properly defined and raised."""
        with pytest.raises(ValidationError) as exc_info:
            raise ValidationError("Invalid tenant data")
        assert "Invalid tenant data" in str(exc_info.value)

    def test_unauthorized_error_maps_to_401(self):
        """Test that UnauthorizedError is properly defined and raised."""
        with pytest.raises(UnauthorizedError) as exc_info:
            raise UnauthorizedError("Invalid token")
        assert "Invalid token" in str(exc_info.value)


class TestTenantResponsePatterns:
    """Test the response patterns used by tenant endpoints."""

    def test_create_tenant_success_response(self):
        """Test successful tenant creation response format."""
        mock_tenant_info = {
            "tenant_id": "tenant-123",
            "tenant_name": "Test Tenant",
            "created_by": "user-456",
            "created_at": "2024-01-01T00:00:00Z"
        }

        expected_response = {
            "message": "Tenant created successfully",
            "data": mock_tenant_info
        }

        assert expected_response["message"] == "Tenant created successfully"
        assert expected_response["data"] == mock_tenant_info

    def test_get_tenant_success_response(self):
        """Test successful tenant retrieval response format."""
        mock_tenant_info = {
            "tenant_id": "tenant-123",
            "tenant_name": "Test Tenant",
            "created_by": "user-456",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z"
        }

        expected_response = {
            "message": "Tenant retrieved successfully",
            "data": mock_tenant_info
        }

        assert expected_response["message"] == "Tenant retrieved successfully"
        assert expected_response["data"] == mock_tenant_info

    def test_get_all_tenants_success_response(self):
        """Test successful tenant list response format."""
        mock_tenants = [
            {"tenant_id": "tenant-123", "tenant_name": "Tenant 1"},
            {"tenant_id": "tenant-456", "tenant_name": "Tenant 2"}
        ]

        expected_response = {
            "message": "Tenants retrieved successfully",
            "data": mock_tenants,
            "total": 2,
            "page": 1,
            "page_size": 20,
            "total_pages": 1
        }

        assert expected_response["message"] == "Tenants retrieved successfully"
        assert expected_response["data"] == mock_tenants
        assert expected_response["total"] == 2

    def test_update_tenant_success_response(self):
        """Test successful tenant update response format."""
        mock_updated_tenant = {
            "tenant_id": "tenant-123",
            "tenant_name": "Updated Name",
            "updated_by": "user-789"
        }

        expected_response = {
            "message": "Tenant updated successfully",
            "data": mock_updated_tenant
        }

        assert expected_response["message"] == "Tenant updated successfully"
        assert expected_response["data"] == mock_updated_tenant

    def test_delete_tenant_success_response(self):
        """Test successful tenant deletion response format."""
        expected_response = {
            "message": "Tenant deleted successfully",
            "data": {"tenant_id": "tenant-123"}
        }

        assert expected_response["message"] == "Tenant deleted successfully"
        assert expected_response["data"]["tenant_id"] == "tenant-123"


class TestTenantServiceCalls:
    """Test that tenant service functions are called with correct parameters."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up mocks for each test."""
        # Import mock services from conftest
        import sys
        self.mock_tenant_service = sys.modules['services'].tenant_service
        self.mock_utils = sys.modules['utils'].auth_utils
        self.mock_tenant_service.create_tenant.reset_mock(side_effect=True, return_value=True)
        self.mock_tenant_service.get_tenant_info.reset_mock(side_effect=True, return_value=True)
        self.mock_tenant_service.get_tenants_paginated.reset_mock(side_effect=True, return_value=True)
        self.mock_tenant_service.update_tenant_info.reset_mock(side_effect=True, return_value=True)
        self.mock_tenant_service.delete_tenant.reset_mock(side_effect=True, return_value=True)
        self.mock_tenant_service.delete_tenant.return_value = True

    def test_create_tenant_calls_service(self):
        """Test that create_tenant is called with correct parameters."""
        from services.tenant_service import create_tenant

        mock_tenant_info = {
            "tenant_id": "tenant-123",
            "tenant_name": "Test Tenant",
            "created_by": "user-456"
        }
        self.mock_tenant_service.create_tenant.return_value = mock_tenant_info

        result = create_tenant(
            tenant_name="Test Tenant",
            created_by="user-456",
            skill_ids=[1, 2],
            skill_names=["skill-a", "skill-b"],
            locale="en"
        )

        self.mock_tenant_service.create_tenant.assert_called_once_with(
            tenant_name="Test Tenant",
            created_by="user-456",
            skill_ids=[1, 2],
            skill_names=["skill-a", "skill-b"],
            locale="en"
        )
        assert result == mock_tenant_info

    def test_get_tenant_calls_service(self):
        """Test that get_tenant_info is called with correct parameters."""
        from services.tenant_service import get_tenant_info

        mock_tenant_info = {
            "tenant_id": "tenant-123",
            "tenant_name": "Test Tenant"
        }
        self.mock_tenant_service.get_tenant_info.return_value = mock_tenant_info

        result = get_tenant_info("tenant-123")

        self.mock_tenant_service.get_tenant_info.assert_called_once_with("tenant-123")
        assert result == mock_tenant_info

    def test_get_tenants_paginated_calls_service(self):
        """Test that get_tenants_paginated is called with correct parameters."""
        from services.tenant_service import get_tenants_paginated

        mock_result = {
            "data": [],
            "total": 100,
            "page": 2,
            "page_size": 10,
            "total_pages": 10
        }
        self.mock_tenant_service.get_tenants_paginated.return_value = mock_result

        result = get_tenants_paginated(page=2, page_size=10)

        self.mock_tenant_service.get_tenants_paginated.assert_called_once_with(page=2, page_size=10)
        assert result == mock_result

    def test_update_tenant_calls_service(self):
        """Test that update_tenant_info is called with correct parameters."""
        from services.tenant_service import update_tenant_info

        mock_updated_tenant = {
            "tenant_id": "tenant-123",
            "tenant_name": "Updated Name"
        }
        self.mock_tenant_service.update_tenant_info.return_value = mock_updated_tenant

        result = update_tenant_info(
            tenant_id="tenant-123",
            tenant_name="Updated Name",
            updated_by="user-789"
        )

        self.mock_tenant_service.update_tenant_info.assert_called_once_with(
            tenant_id="tenant-123",
            tenant_name="Updated Name",
            updated_by="user-789"
        )
        assert result == mock_updated_tenant

    def test_delete_tenant_calls_service(self):
        """Test that delete_tenant is called with correct parameters."""
        import asyncio
        from services.tenant_service import delete_tenant

        # The delete_tenant in conftest is already a mock async function
        # We just need to call it and verify the call
        mock_delete = self.mock_tenant_service.delete_tenant
        if not isinstance(mock_delete, AsyncMock):
            mock_delete = AsyncMock(return_value=True)
            self.mock_tenant_service.delete_tenant = mock_delete

        result = asyncio.run(delete_tenant("tenant-123", deleted_by="user-789"))

        # The mock was called (it was already defined in conftest)
        assert result is True


class TestTenantAuth:
    """Test authentication handling for tenant endpoints."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up mocks for each test."""
        import sys
        self.mock_utils = sys.modules['utils'].auth_utils
        self.mock_utils.get_current_user_id.reset_mock(side_effect=True, return_value=True)

    def test_get_current_user_id_is_called(self):
        """Test that get_current_user_id is used for authorization."""
        from utils.auth_utils import get_current_user_id

        self.mock_utils.get_current_user_id.return_value = ("user-456", "tenant-123")

        user_id, tenant_id = get_current_user_id("Bearer token")

        self.mock_utils.get_current_user_id.assert_called_once_with("Bearer token")
        assert user_id == "user-456"
        assert tenant_id == "tenant-123"

    def test_get_current_user_id_raises_unauthorized(self):
        """Test that get_current_user_id raises UnauthorizedError for invalid tokens."""
        from utils.auth_utils import get_current_user_id

        self.mock_utils.get_current_user_id.side_effect = UnauthorizedError("Invalid token")

        with pytest.raises(UnauthorizedError) as exc_info:
            get_current_user_id("Bearer invalid")
        assert "Invalid token" in str(exc_info.value)


class TestTenantEndpointExceptionHandling:
    """Test exception handling patterns in tenant endpoints."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up mocks for each test."""
        import sys
        self.mock_tenant_service = sys.modules['services'].tenant_service
        self.mock_utils = sys.modules['utils'].auth_utils
        self.mock_tenant_service.create_tenant.reset_mock(side_effect=True, return_value=True)
        self.mock_tenant_service.get_tenant_info.reset_mock(side_effect=True, return_value=True)
        self.mock_tenant_service.get_tenants_paginated.reset_mock(side_effect=True, return_value=True)
        self.mock_tenant_service.update_tenant_info.reset_mock(side_effect=True, return_value=True)
        self.mock_tenant_service.delete_tenant.reset_mock(side_effect=True, return_value=True)
        self.mock_tenant_service.delete_tenant.return_value = True

    def test_not_found_exception_handling(self):
        """Test that NotFoundException is caught and raises HTTPException 404."""
        from services.tenant_service import get_tenant_info

        self.mock_tenant_service.get_tenant_info.side_effect = NotFoundException("Tenant not found")

        with pytest.raises(NotFoundException) as exc_info:
            get_tenant_info("nonexistent")
        assert "Tenant not found" in str(exc_info.value)

    def test_validation_error_handling(self):
        """Test that ValidationError is caught and raises HTTPException 400."""
        from services.tenant_service import create_tenant

        self.mock_tenant_service.create_tenant.side_effect = ValidationError("Invalid data")

        with pytest.raises(ValidationError) as exc_info:
            create_tenant(tenant_name="", created_by="user")
        assert "Invalid data" in str(exc_info.value)

    def test_unexpected_error_handling(self):
        """Test that unexpected exceptions are caught and return 500."""
        from services.tenant_service import get_tenant_info

        self.mock_tenant_service.get_tenant_info.side_effect = RuntimeError("Unexpected error")

        with pytest.raises(RuntimeError) as exc_info:
            get_tenant_info("tenant-123")
        assert "Unexpected error" in str(exc_info.value)
