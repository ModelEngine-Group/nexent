import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import pytest
from unittest.mock import patch, MagicMock

# Mock external dependencies before importing
sys.modules['psycopg2'] = MagicMock()
sys.modules['boto3'] = MagicMock()
sys.modules['supabase'] = MagicMock()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
      return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate',
      lambda self: None).start()
patch('backend.database.client.MinioClient',
      return_value=minio_client_mock).start()

from consts.exceptions import NotFoundException, ValidationError
from backend.services.tenant_service import (
    get_tenant_info,
    get_all_tenants,
    create_tenant,
    update_tenant_info,
    delete_tenant,
    _create_default_group_for_tenant,
    check_tenant_name_exists
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
        """Test get_tenant_info when tenant name is not found - should auto-create config"""
        # Setup
        tenant_id = "test_tenant_id"

        # Mock config functions
        service_mocks['get_single_config_info'].side_effect = [
            {},                    # TENANT_NAME first check (not found)
            {},                    # TENANT_NAME check in _ensure_tenant_name_config (double-check)
            {"config_value": "Unnamed Tenant", "tenant_config_id": 1},  # TENANT_NAME after auto-create
            {"config_value": "group-123"}  # DEFAULT_GROUP_ID
        ]
        service_mocks['insert_config'].return_value = True

        # Execute
        result = get_tenant_info(tenant_id)

        # Assert - should return tenant info with auto-created default name
        assert result["tenant_id"] == tenant_id
        assert result["tenant_name"] == "Unnamed Tenant"
        assert result["default_group_id"] == "group-123"

        # Verify insert_config was called to create the missing config
        service_mocks['insert_config'].assert_called_once()

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

    def test_get_tenant_info_get_single_config_exception(self, service_mocks):
        """Test get_tenant_info when get_single_config_info raises exception"""
        # Setup
        tenant_id = "test_tenant_id"

        # Mock get_single_config_info to raise exception
        service_mocks['get_single_config_info'].side_effect = Exception(
            "Database connection error")

        # Execute & Assert
        with pytest.raises(Exception, match="Database connection error"):
            get_tenant_info(tenant_id)

    def test_get_tenant_info_both_configs_none(self, service_mocks):
        """Test get_tenant_info when both configs return None - should auto-create name config"""
        # Setup
        tenant_id = "test_tenant_id"

        # Mock config functions:
        # 1st call: TENANT_NAME not found (None)
        # 2nd call: TENANT_NAME check in _ensure_tenant_name_config (None - double-check)
        # 3rd call: after insert, re-fetch returns the created config
        # 4th call: DEFAULT_GROUP_ID returns None
        service_mocks['get_single_config_info'].side_effect = [
            None,                    # TENANT_NAME first check (None)
            None,                    # TENANT_NAME check in _ensure_tenant_name_config
            {"config_value": "Unnamed Tenant", "tenant_config_id": 1},  # TENANT_NAME after auto-create
            None                     # DEFAULT_GROUP_ID (None)
        ]
        service_mocks['insert_config'].return_value = True

        # Execute
        result = get_tenant_info(tenant_id)

        # Assert - should return tenant info with auto-created default name and empty group_id
        assert result["tenant_id"] == tenant_id
        assert result["tenant_name"] == "Unnamed Tenant"
        assert result["default_group_id"] == ""

        # Verify insert_config was called to create the missing config
        service_mocks['insert_config'].assert_called_once()


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

    def test_get_all_tenants_with_missing_configs(self, service_mocks):
        """Test get_all_tenants when some tenants have missing configs"""
        # Setup
        tenant_ids = ["tenant1", "tenant2", "tenant3"]

        # Mock get_tenant_info to return tenant info for all, but with missing configs for tenant3
        def mock_get_tenant_info(tenant_id):
            if tenant_id == "tenant3":
                # Simulate missing name config - returns empty name
                return {
                    "tenant_id": tenant_id,
                    "tenant_name": "",  # Missing name config
                    "default_group_id": "group3"
                }
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

            # Assert - should return all tenants, with failed tenant having empty fields
            assert len(result) == 3
            assert result[0]["tenant_id"] == "tenant1"
            assert result[0]["tenant_name"] == "Tenant 1"
            assert result[0]["default_group_id"] == "group1"
            assert result[1]["tenant_id"] == "tenant2"
            assert result[1]["tenant_name"] == "Tenant 2"
            assert result[1]["default_group_id"] == "group2"
            # Failed tenant should have empty name and default_group_id
            assert result[2]["tenant_id"] == "tenant3"
            assert result[2]["tenant_name"] == ""
            assert result[2]["default_group_id"] == 'group3'

    def test_get_all_tenants_empty_list(self, service_mocks):
        """Test get_all_tenants when no tenants exist"""
        # Mock dependencies
        with patch('backend.services.tenant_service.get_all_tenant_ids', return_value=[]) as mock_get_tenant_ids:

            # Execute
            result = get_all_tenants()

            # Assert
            assert result == []
            mock_get_tenant_ids.assert_called_once()

    def test_get_all_tenants_get_all_tenant_ids_exception(self, service_mocks):
        """Test get_all_tenants when get_all_tenant_ids raises exception"""
        # Mock dependencies
        with patch('backend.services.tenant_service.get_all_tenant_ids', side_effect=Exception("Database error")) as mock_get_tenant_ids:

            # Execute & Assert
            with pytest.raises(Exception, match="Database error"):
                get_all_tenants()


class TestCreateTenant:
    """Test cases for create_tenant function"""

    def test_create_tenant_success(self, service_mocks):
        """Test successfully creating a tenant"""
        # Setup
        tenant_name = "New Tenant"
        user_id = "creator_user"
        group_id = 123

        # Mock check_tenant_name_exists to return False (name not taken)
        with patch('backend.services.tenant_service.check_tenant_name_exists', return_value=False), \
             patch('backend.services.tenant_service._create_default_group_for_tenant', return_value=group_id):

            # Configure insert_config to succeed
            service_mocks['insert_config'].return_value = True

            # Execute
            result = create_tenant(tenant_name, user_id)

            # Assert
            assert result["tenant_name"] == tenant_name
            assert result["default_group_id"] == str(group_id)
            assert "tenant_id" in result  # tenant_id is auto-generated UUID

            # Verify config insertions were called (3 configs: ID, name, group)
            assert service_mocks['insert_config'].call_count == 3

    def test_create_tenant_name_already_exists(self, service_mocks):
        """Test creating tenant with a name that already exists"""
        # Setup
        tenant_name = "Existing Tenant"
        user_id = "creator_user"

        # Mock check_tenant_name_exists to return True (name already taken)
        with patch('backend.services.tenant_service.check_tenant_name_exists', return_value=True):

            # Execute & Assert
            with pytest.raises(ValidationError, match="already exists"):
                create_tenant(tenant_name, user_id)

    def test_create_tenant_empty_name(self, service_mocks):
        """Test creating tenant with empty name"""
        # Setup
        tenant_name = ""
        user_id = "creator_user"

        # Mock check_tenant_name_exists (won't be called due to empty name validation)
        with patch('backend.services.tenant_service.check_tenant_name_exists', return_value=False):

            # Execute & Assert
            with pytest.raises(ValidationError, match="Tenant name cannot be empty"):
                create_tenant(tenant_name, user_id)

    def test_create_tenant_config_insertion_failure(self, service_mocks):
        """Test create_tenant when config insertion fails"""
        # Setup
        tenant_name = "New Tenant"
        user_id = "creator_user"

        # Mock dependencies
        with patch('backend.services.tenant_service.check_tenant_name_exists', return_value=False), \
             patch('backend.services.tenant_service._create_default_group_for_tenant', return_value=123):

            service_mocks['insert_config'].return_value = False

            # Execute & Assert
            with pytest.raises(ValidationError, match="Failed to create tenant ID configuration"):
                create_tenant(tenant_name, user_id)

    def test_create_tenant_whitespace_name(self, service_mocks):
        """Test creating tenant with whitespace-only name"""
        # Setup
        tenant_name = "   \t\n   "  # Only whitespace
        user_id = "creator_user"

        # Mock check_tenant_name_exists (won't be called due to whitespace validation)
        with patch('backend.services.tenant_service.check_tenant_name_exists', return_value=False):

            # Execute & Assert
            with pytest.raises(ValidationError, match="Tenant name cannot be empty"):
                create_tenant(tenant_name, user_id)

    def test_create_tenant_tenant_id_config_failure(self, service_mocks):
        """Test create_tenant when tenant ID config insertion fails"""
        # Setup
        tenant_name = "New Tenant"
        user_id = "creator_user"

        # Mock dependencies
        with patch('backend.services.tenant_service.check_tenant_name_exists', return_value=False), \
                patch('backend.services.tenant_service._create_default_group_for_tenant', return_value=123):

            # Configure insert_config to fail on first call (tenant ID config)
            service_mocks['insert_config'].side_effect = [False, True, True]

            # Execute & Assert
            with pytest.raises(ValidationError, match="Failed to create tenant ID configuration"):
                create_tenant(tenant_name, user_id)

    def test_create_tenant_group_config_failure(self, service_mocks):
        """Test create_tenant when group config insertion fails"""
        # Setup
        tenant_name = "New Tenant"
        user_id = "creator_user"

        # Mock dependencies
        with patch('backend.services.tenant_service.check_tenant_name_exists', return_value=False), \
                patch('backend.services.tenant_service._create_default_group_for_tenant', return_value=123):

            # Configure insert_config to succeed for first two, fail for third (group config)
            service_mocks['insert_config'].side_effect = [True, True, False]

            # Execute & Assert
            with pytest.raises(ValidationError, match="Failed to create tenant default group configuration"):
                create_tenant(tenant_name, user_id)

    def test_create_tenant_default_group_creation_failure(self, service_mocks):
        """Test create_tenant when default group creation fails"""
        # Setup
        tenant_name = "New Tenant"
        user_id = "creator_user"

        # Mock dependencies
        with patch('backend.services.tenant_service.check_tenant_name_exists', return_value=False), \
                patch('backend.services.tenant_service._create_default_group_for_tenant', side_effect=ValidationError("Group creation failed")):

            # Execute & Assert
            with pytest.raises(ValidationError, match="Failed to create tenant: Group creation failed"):
                create_tenant(tenant_name, user_id)

    def test_create_tenant_unexpected_exception_in_try_block(self, service_mocks):
        """Test create_tenant when unexpected exception occurs in try block"""
        # Setup
        tenant_name = "New Tenant"
        user_id = "creator_user"

        # Mock dependencies
        with patch('backend.services.tenant_service.check_tenant_name_exists', return_value=False), \
                patch('backend.services.tenant_service._create_default_group_for_tenant', side_effect=Exception("Unexpected error")):

            # Execute & Assert
            with pytest.raises(ValidationError, match="Failed to create tenant: Unexpected error"):
                create_tenant(tenant_name, user_id)

    def test_create_tenant_uuid_collision(self, service_mocks):
        """Test create_tenant when UUID collision occurs (unlikely but possible)"""
        # Note: This test is now obsolete since we removed UUID collision check.
        # UUIDs are random and collision probability is astronomically low.
        # Keeping for reference - this scenario should never happen in practice.
        pass


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
        """Test update_tenant_info when tenant doesn't exist - should auto-create config"""
        # Setup
        tenant_id = "nonexistent_tenant"
        new_tenant_name = "Updated Name"
        user_id = "updater_user"

        # Mock get_single_config_info to return empty dict on first call (TENANT_NAME not found),
        # then return the newly created config after auto-creation
        service_mocks['get_single_config_info'].side_effect = [
            {},  # First check - not found
            {"config_value": new_tenant_name, "tenant_config_id": 1}  # After auto-create
        ]
        service_mocks['insert_config'].return_value = True

        # Mock get_tenant_info to return updated info
        with patch('backend.services.tenant_service.get_tenant_info') as mock_get_tenant_info:
            mock_get_tenant_info.return_value = {
                "tenant_id": tenant_id,
                "tenant_name": new_tenant_name,
                "default_group_id": "group-123"
            }

            # Execute - should NOT raise NotFoundException, instead auto-create config
            result = update_tenant_info(tenant_id, new_tenant_name, user_id)

            # Assert - update should succeed by auto-creating the config
            assert result["tenant_id"] == tenant_id
            assert result["tenant_name"] == new_tenant_name

            # Verify insert_config was called to create the missing config
            service_mocks['insert_config'].assert_called_once()

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

    def test_update_tenant_info_whitespace_name(self, service_mocks):
        """Test update_tenant_info with whitespace-only name"""
        # Setup
        tenant_id = "test_tenant"
        new_tenant_name = "   \t\n   "  # Only whitespace
        user_id = "updater_user"

        # Mock config info
        config_info = {"tenant_config_id": 123, "config_value": "Old Name"}

        # Mock dependencies
        service_mocks['get_single_config_info'].return_value = config_info

        # Execute & Assert
        with pytest.raises(ValidationError, match="Tenant name cannot be empty"):
            update_tenant_info(tenant_id, new_tenant_name, user_id)

    def test_update_tenant_info_name_already_exists(self, service_mocks):
        """Test update_tenant_info raises error when name already exists on another tenant"""
        # Setup
        tenant_id = "test_tenant"
        new_tenant_name = "Duplicate Name"
        user_id = "updater_user"

        # Mock check_tenant_name_exists to return True (name already taken by another tenant)
        with patch('backend.services.tenant_service.check_tenant_name_exists', return_value=True) as mock_check:
            # Execute & Assert
            with pytest.raises(ValidationError, match="already exists"):
                update_tenant_info(tenant_id, new_tenant_name, user_id)

            # Verify check_tenant_name_exists was called with the right parameters
            mock_check.assert_called_once_with(new_tenant_name.strip(), exclude_tenant_id=tenant_id)


class TestDeleteTenant:
    """Test cases for delete_tenant function"""

    def test_delete_tenant_always_fails(self):
        """Test that delete_tenant always raises NotImplementedError"""
        # Execute & Assert
        with pytest.raises(NotImplementedError, match="Tenant deletion is not yet implemented"):
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

    def test_create_default_group_for_tenant_with_none_user(self, service_mocks):
        """Test _create_default_group_for_tenant with None user"""
        # Setup
        tenant_id = "test_tenant"
        user_id = None
        expected_group_id = 123

        # Mock add_group to return expected group ID
        with patch('backend.services.tenant_service.add_group', return_value=expected_group_id) as mock_add_group:
            # Execute
            result = _create_default_group_for_tenant(tenant_id, user_id)

            # Assert
            assert result == expected_group_id

            # Verify add_group was called with None as created_by
            mock_add_group.assert_called_once_with(
                tenant_id=tenant_id,
                group_name="Default Group",
                group_description="Default group created automatically for new tenant",
                created_by=None
            )

    def test_create_default_group_for_tenant_validation_error_from_add_group(self, service_mocks):
        """Test _create_default_group_for_tenant when add_group raises ValidationError"""
        # Setup
        tenant_id = "test_tenant"
        user_id = "creator_user"

        # Mock add_group to raise ValidationError
        from consts.exceptions import ValidationError as VE
        with patch('backend.services.tenant_service.add_group', side_effect=VE("Invalid group data")):
            # Execute & Assert
            with pytest.raises(ValidationError, match="Failed to create default group: Invalid group data"):
                _create_default_group_for_tenant(tenant_id, user_id)


class TestCheckTenantNameExists:
    """Test cases for check_tenant_name_exists function"""

    def test_check_tenant_name_exists_returns_false_when_no_match(self):
        """Test check_tenant_name_exists returns False when no tenant has the name"""
        # Setup
        tenant_name = "Unique Tenant Name"
        tenant_ids = ["tenant1", "tenant2", "tenant3"]

        # Mock with fresh mocks to avoid fixture conflicts
        with patch('backend.services.tenant_service.get_all_tenant_ids', return_value=tenant_ids), \
             patch('backend.services.tenant_service.get_single_config_info') as mock_get_config:
            # Each tenant has a different name
            mock_get_config.side_effect = [
                {"config_value": "Tenant 1"},  # tenant1
                {"config_value": "Tenant 2"},  # tenant2
                {"config_value": "Tenant 3"}   # tenant3
            ]

            # Execute
            result = check_tenant_name_exists(tenant_name)

            # Assert
            assert result is False

    def test_check_tenant_name_exists_returns_true_when_match_found(self):
        """Test check_tenant_name_exists returns True when a tenant has the name"""
        # Setup
        tenant_name = "Existing Tenant"
        tenant_ids = ["tenant1", "tenant2", "tenant3"]

        # Mock with fresh mocks
        with patch('backend.services.tenant_service.get_all_tenant_ids', return_value=tenant_ids), \
             patch('backend.services.tenant_service.get_single_config_info') as mock_get_config:
            # tenant2 has the name we're looking for
            mock_get_config.side_effect = [
                {"config_value": "Tenant 1"},  # tenant1
                {"config_value": "Existing Tenant"},  # tenant2 - match!
                {"config_value": "Tenant 3"}   # tenant3
            ]

            # Execute
            result = check_tenant_name_exists(tenant_name)

            # Assert
            assert result is True

    def test_check_tenant_name_exists_excludes_specified_tenant(self):
        """Test check_tenant_name_exists excludes the specified tenant ID when checking"""
        # Setup
        tenant_name = "My Tenant"
        exclude_tenant_id = "tenant2"
        tenant_ids = ["tenant1", "tenant2", "tenant3"]

        # Mock with fresh mocks
        with patch('backend.services.tenant_service.get_all_tenant_ids', return_value=tenant_ids), \
             patch('backend.services.tenant_service.get_single_config_info') as mock_get_config:
            # tenant2 has the name, but should be excluded
            mock_get_config.side_effect = [
                {"config_value": "My Tenant"},  # tenant1 - match (not excluded)
                {"config_value": "My Tenant"},  # tenant2 - would match but excluded
                {"config_value": "Tenant 3"}   # tenant3
            ]

            # Execute
            result = check_tenant_name_exists(tenant_name, exclude_tenant_id=exclude_tenant_id)

            # Assert - should return True because tenant1 has the name
            assert result is True

    def test_check_tenant_name_exists_empty_tenant_list(self):
        """Test check_tenant_name_exists returns False when no tenants exist"""
        # Setup
        tenant_name = "Any Tenant"

        # Mock dependencies - no tenants
        with patch('backend.services.tenant_service.get_all_tenant_ids', return_value=[]):

            # Execute
            result = check_tenant_name_exists(tenant_name)

            # Assert
            assert result is False

    def test_check_tenant_name_exists_case_sensitive(self):
        """Test check_tenant_name_exists is case-sensitive"""
        # Setup
        tenant_name = "my tenant"  # lowercase
        tenant_ids = ["tenant1"]

        # Mock with fresh mock
        with patch('backend.services.tenant_service.get_all_tenant_ids', return_value=tenant_ids), \
             patch('backend.services.tenant_service.get_single_config_info') as mock_get_config:
            mock_get_config.return_value = {"config_value": "My Tenant"}  # different case

            # Execute
            result = check_tenant_name_exists(tenant_name)

            # Assert - should return False because comparison is case-sensitive
            assert result is False

    def test_check_tenant_name_exists_with_empty_name_config(self):
        """Test check_tenant_name_exists handles tenants with empty name config"""
        # Setup
        tenant_name = "Test Tenant"
        tenant_ids = ["tenant1", "tenant2"]

        # Mock with fresh mocks
        with patch('backend.services.tenant_service.get_all_tenant_ids', return_value=tenant_ids), \
             patch('backend.services.tenant_service.get_single_config_info') as mock_get_config:
            # tenant1 has empty name config (empty dict is falsy), tenant2 has different name
            mock_get_config.side_effect = [
                None,  # tenant1 - empty/falsy config
                {"config_value": "Other Tenant"}  # tenant2
            ]

            # Execute
            result = check_tenant_name_exists(tenant_name)

            # Assert - should return False because no tenant has "Test Tenant"
            assert result is False

            # Assert
            assert result is False

