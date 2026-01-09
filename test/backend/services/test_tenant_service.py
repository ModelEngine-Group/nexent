import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import pytest
from unittest.mock import patch, MagicMock

# Mock external dependencies before importing
sys.modules['psycopg2'] = MagicMock()
sys.modules['boto3'] = MagicMock()
sys.modules['supabase'] = MagicMock()

from consts.exceptions import NotFoundException, ValidationError
from backend.services.tenant_service import (
    get_tenant_info,
    get_all_tenants,
    create_tenant,
    update_tenant_info,
    delete_tenant,
    _create_default_group_for_tenant
)


@pytest.fixture
def service_mocks():
    """Create mocks for service layer dependencies"""
    with patch('backend.services.tenant_service.get_single_config_info') as mock_get_single_config, \
            patch('backend.services.tenant_service.insert_config') as mock_insert_config, \
            patch('backend.services.tenant_service.update_config_by_tenant_config_id') as mock_update_config, \
            patch('backend.services.tenant_service.get_all_tenant_ids') as mock_get_all_tenant_ids, \
            patch('backend.services.tenant_service.add_group') as mock_add_group:

        yield {
            'get_single_config_info': mock_get_single_config,
            'insert_config': mock_insert_config,
            'update_config_by_tenant_config_id': mock_update_config,
            'get_all_tenant_ids': mock_get_all_tenant_ids,
            'add_group': mock_add_group
        }


class TestGetTenantInfo:
    """Test cases for get_tenant_info function"""

    def test_get_tenant_info_success(self, service_mocks):
        """Test successfully retrieving tenant information"""
        # Setup
        tenant_id = "test_tenant_id"
        expected_name = "Test Tenant"
        expected_group_id = "group-123"

        # Mock config functions
        service_mocks['get_single_config_info'].side_effect = [
            {"config_value": expected_name},  # TENANT_NAME
            {"config_value": expected_group_id}  # DEFAULT_GROUP_ID
        ]

        # Execute
        result = get_tenant_info(tenant_id)

        # Assert
        assert result["tenant_id"] == tenant_id
        assert result["tenant_name"] == expected_name
        assert result["default_group_id"] == expected_group_id

        # Verify calls
        service_mocks['get_single_config_info'].assert_any_call(
            tenant_id, "TENANT_NAME")
        service_mocks['get_single_config_info'].assert_any_call(
            tenant_id, "DEFAULT_GROUP_ID")

    def test_get_tenant_info_name_not_found(self, service_mocks):
        """Test get_tenant_info when tenant name is not found"""
        # Setup
        tenant_id = "test_tenant_id"

        # Mock config functions to return empty dict for name
        service_mocks['get_single_config_info'].side_effect = [
            {},  # TENANT_NAME not found
            {"config_value": "group-123"}  # DEFAULT_GROUP_ID
        ]

        # Execute & Assert
        with pytest.raises(NotFoundException, match="The name of tenant not found"):
            get_tenant_info(tenant_id)

    def test_get_tenant_info_with_empty_group_id(self, service_mocks):
        """Test get_tenant_info when default group ID is empty"""
        # Setup
        tenant_id = "test_tenant_id"
        expected_name = "Test Tenant"

        # Mock config functions
        service_mocks['get_single_config_info'].side_effect = [
            {"config_value": expected_name},  # TENANT_NAME
            {}  # DEFAULT_GROUP_ID not found
        ]

        # Execute
        result = get_tenant_info(tenant_id)

        # Assert
        assert result["tenant_id"] == tenant_id
        assert result["tenant_name"] == expected_name
        assert result["default_group_id"] == ""


class TestGetAllTenants:
    """Test cases for get_all_tenants function"""

    def test_get_all_tenants_success(self, service_mocks):
        """Test successfully retrieving all tenants"""
        # Setup
        tenant_ids = ["tenant1", "tenant2", "tenant3"]
        tenant_infos = [
            {"tenant_id": "tenant1", "tenant_name": "Tenant 1", "default_group_id": "group1"},
            {"tenant_id": "tenant2", "tenant_name": "Tenant 2", "default_group_id": "group2"},
            {"tenant_id": "tenant3", "tenant_name": "Tenant 3", "default_group_id": "group3"}
        ]

        # Mock dependencies
        with patch('backend.services.tenant_service.get_all_tenant_ids', return_value=tenant_ids), \
             patch('backend.services.tenant_service.get_tenant_info', side_effect=tenant_infos) as mock_get_tenant_info:

            # Execute
            result = get_all_tenants()

            # Assert
            assert len(result) == 3
            assert result == tenant_infos

    def test_get_all_tenants_with_failed_tenant(self, service_mocks):
        """Test get_all_tenants when one tenant fails to load"""
        # Setup
        tenant_ids = ["tenant1", "tenant2", "tenant3"]

        # Mock get_tenant_info to succeed for first two, fail for third
        def mock_get_tenant_info(tenant_id):
            if tenant_id == "tenant3":
                raise NotFoundException("Tenant not found")
            return {
                "tenant_id": tenant_id,
                "tenant_name": f"Tenant {tenant_id[-1]}",
                "default_group_id": f"group{tenant_id[-1]}"
            }

        # Mock dependencies
        with patch('backend.services.tenant_service.get_all_tenant_ids', return_value=tenant_ids), \
             patch('backend.services.tenant_service.get_tenant_info', side_effect=mock_get_tenant_info):

            # Execute
            result = get_all_tenants()

            # Assert - should skip the failed tenant
            assert len(result) == 2
            assert result[0]["tenant_id"] == "tenant1"
            assert result[1]["tenant_id"] == "tenant2"


class TestCreateTenant:
    """Test cases for create_tenant function"""

    def test_create_tenant_success(self, service_mocks):
        """Test successfully creating a tenant"""
        # Setup
        tenant_id = "new_tenant"
        tenant_name = "New Tenant"
        user_id = "creator_user"
        group_id = 123

        # Mock dependencies
        with patch('backend.services.tenant_service.get_tenant_info', side_effect=NotFoundException()), \
             patch('backend.services.tenant_service._create_default_group_for_tenant', return_value=group_id):

            # Configure insert_config to succeed
            service_mocks['insert_config'].return_value = True

            # Execute
            result = create_tenant(tenant_id, tenant_name, user_id)

            # Assert
            assert result["tenant_id"] == tenant_id
            assert result["tenant_name"] == tenant_name
            assert result["default_group_id"] == str(group_id)

            # Verify config insertions were called
            assert service_mocks['insert_config'].call_count == 2

    def test_create_tenant_already_exists(self, service_mocks):
        """Test creating tenant that already exists"""
        # Setup
        tenant_id = "existing_tenant"
        tenant_name = "Existing Tenant"
        user_id = "creator_user"

        # Mock get_tenant_info to return existing tenant
        with patch('backend.services.tenant_service.get_tenant_info', return_value={"tenant_id": tenant_id}) as mock_get_tenant_info:

            # Execute & Assert
            with pytest.raises(ValidationError, match="already exists"):
                create_tenant(tenant_id, tenant_name, user_id)

    def test_create_tenant_empty_name(self, service_mocks):
        """Test creating tenant with empty name"""
        # Setup
        tenant_id = "new_tenant"
        tenant_name = ""
        user_id = "creator_user"

        # Mock get_tenant_info to raise NotFoundException (tenant doesn't exist)
        with patch('backend.services.tenant_service.get_tenant_info', side_effect=NotFoundException()) as mock_get_tenant_info:

            # Execute & Assert
            with pytest.raises(ValidationError, match="Tenant name cannot be empty"):
                create_tenant(tenant_id, tenant_name, user_id)

    def test_create_tenant_config_insertion_failure(self, service_mocks):
        """Test create_tenant when config insertion fails"""
        # Setup
        tenant_id = "new_tenant"
        tenant_name = "New Tenant"
        user_id = "creator_user"

        # Mock dependencies
        with patch('backend.services.tenant_service.get_tenant_info', side_effect=NotFoundException()), \
             patch('backend.services.tenant_service._create_default_group_for_tenant', return_value=123):

            service_mocks['insert_config'].return_value = False

            # Execute & Assert
            with pytest.raises(ValidationError, match="Failed to create tenant name configuration"):
                create_tenant(tenant_id, tenant_name, user_id)


class TestUpdateTenantInfo:
    """Test cases for update_tenant_info function"""

    def test_update_tenant_info_success(self, service_mocks):
        """Test successfully updating tenant information"""
        # Setup
        tenant_id = "test_tenant"
        new_tenant_name = "Updated Tenant Name"
        user_id = "updater_user"

        # Mock config info
        config_info = {"tenant_config_id": 123, "config_value": "Old Name"}

        # Mock dependencies
        with patch('backend.services.tenant_service.get_tenant_info') as mock_get_tenant_info:

            service_mocks['get_single_config_info'].return_value = config_info
            service_mocks['update_config_by_tenant_config_id'].return_value = True

            mock_get_tenant_info.return_value = {
                "tenant_id": tenant_id,
                "tenant_name": new_tenant_name,
                "default_group_id": "group-123"
            }

            # Execute
            result = update_tenant_info(tenant_id, new_tenant_name, user_id)

            # Assert
            assert result["tenant_id"] == tenant_id
            assert result["tenant_name"] == new_tenant_name

    def test_update_tenant_info_tenant_not_found(self, service_mocks):
        """Test update_tenant_info when tenant doesn't exist"""
        # Setup
        tenant_id = "nonexistent_tenant"
        new_tenant_name = "Updated Name"
        user_id = "updater_user"

        # Mock get_single_config_info to return empty dict (not found)
        service_mocks['get_single_config_info'].return_value = {}

        # Execute & Assert
        with pytest.raises(NotFoundException, match="not found"):
            update_tenant_info(tenant_id, new_tenant_name, user_id)

    def test_update_tenant_info_empty_name(self, service_mocks):
        """Test update_tenant_info with empty name"""
        # Setup
        tenant_id = "test_tenant"
        new_tenant_name = ""
        user_id = "updater_user"

        # Mock config info
        config_info = {"tenant_config_id": 123, "config_value": "Old Name"}

        # Mock dependencies
        service_mocks['get_single_config_info'].return_value = config_info

        # Execute & Assert
        with pytest.raises(ValidationError, match="Tenant name cannot be empty"):
            update_tenant_info(tenant_id, new_tenant_name, user_id)

    def test_update_tenant_info_update_failure(self, service_mocks):
        """Test update_tenant_info when config update fails"""
        # Setup
        tenant_id = "test_tenant"
        new_tenant_name = "Updated Name"
        user_id = "updater_user"

        # Mock config info
        config_info = {"tenant_config_id": 123, "config_value": "Old Name"}

        # Mock dependencies
        service_mocks['get_single_config_info'].return_value = config_info
        service_mocks['update_config_by_tenant_config_id'].return_value = False

        # Execute & Assert
        with pytest.raises(ValidationError, match="Failed to update tenant name"):
            update_tenant_info(tenant_id, new_tenant_name, user_id)


class TestDeleteTenant:
    """Test cases for delete_tenant function"""

    def test_delete_tenant_always_fails(self):
        """Test that delete_tenant always raises ValidationError"""
        # Execute & Assert
        with pytest.raises(ValidationError, match="Tenant deletion is not yet implemented"):
            delete_tenant("any_tenant", "any_user")


class TestCreateDefaultGroupForTenant:
    """Test cases for _create_default_group_for_tenant function"""

    def test_create_default_group_for_tenant_success(self, service_mocks):
        """Test successfully creating default group for tenant"""
        # Setup
        tenant_id = "test_tenant"
        user_id = "creator_user"
        expected_group_id = 123

        # Mock add_group to return expected group ID
        with patch('backend.services.tenant_service.add_group', return_value=expected_group_id) as mock_add_group:
            # Execute
            result = _create_default_group_for_tenant(tenant_id, user_id)

            # Assert
            assert result == expected_group_id

            # Verify add_group was called with correct parameters
            mock_add_group.assert_called_once_with(
                tenant_id=tenant_id,
                group_name="Default Group",
                group_description="Default group created automatically for new tenant",
                created_by=user_id
            )

    def test_create_default_group_for_tenant_failure(self, service_mocks):
        """Test _create_default_group_for_tenant when group creation fails"""
        # Setup
        tenant_id = "test_tenant"
        user_id = "creator_user"

        # Mock add_group to raise exception
        with patch('backend.services.tenant_service.add_group', side_effect=Exception("Database error")):
            # Execute & Assert
            with pytest.raises(ValidationError, match="Failed to create default group"):
                _create_default_group_for_tenant(tenant_id, user_id)
