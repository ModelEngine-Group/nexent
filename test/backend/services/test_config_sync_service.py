import sys
from unittest.mock import patch, MagicMock, call

import pytest

# Patch boto3 and other dependencies before importing anything from backend
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
minio_client_mock._ensure_bucket_exists = MagicMock()
minio_client_mock.client = MagicMock()

# Mock the entire MinIOStorageConfig class to avoid validation
minio_config_mock = MagicMock()
minio_config_mock.validate = MagicMock()

patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
      return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig',
      return_value=minio_config_mock).start()
patch('backend.database.client.MinioClient',
      return_value=minio_client_mock).start()
patch('database.client.MinioClient', return_value=minio_client_mock).start()
patch('backend.database.client.minio_client', minio_client_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Import backend modules after all patches are applied
# Use additional context manager to ensure MinioClient is properly mocked during import
with patch('backend.database.client.MinioClient', return_value=minio_client_mock), \
        patch('nexent.storage.minio_config.MinIOStorageConfig', return_value=minio_config_mock):
    from backend.services.config_sync_service import (
        handle_model_config,
        save_config_impl,
        load_config_impl,
        build_models_config,
        build_app_config,
        build_model_config
    )


@pytest.fixture
def service_mocks():
    """Create mocks for service layer dependencies"""
    with patch('backend.services.config_sync_service.tenant_config_manager') as mock_tenant_config_manager, \
            patch('backend.services.config_sync_service.get_env_key') as mock_get_env_key, \
            patch('backend.services.config_sync_service.safe_value') as mock_safe_value, \
            patch('backend.services.config_sync_service.get_model_id_by_display_name') as mock_get_model_id, \
            patch('backend.services.config_sync_service.get_model_name_from_config') as mock_get_model_name, \
            patch('backend.services.config_sync_service.logger') as mock_logger:

        yield {
            'tenant_config_manager': mock_tenant_config_manager,
            'get_env_key': mock_get_env_key,
            'safe_value': mock_safe_value,
            'get_model_id': mock_get_model_id,
            'get_model_name': mock_get_model_name,
            'logger': mock_logger
        }


class TestHandleModelConfig:
    """Test cases for handle_model_config function"""

    def test_handle_model_config_zero_sets(self, service_mocks):
        """Test handle_model_config when model_id is 0 and config exists (delete then set)"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = 0
        tenant_config_dict = {"LLM_ID": "123"}

        # Execute
        handle_model_config(tenant_id, user_id, config_key,
                            model_id, tenant_config_dict)

        # Assert
        service_mocks['tenant_config_manager'].delete_single_config.assert_called_once_with(
            tenant_id, config_key)
        service_mocks['tenant_config_manager'].set_single_config.assert_called_once_with(
            user_id, tenant_id, config_key, model_id
        )

    def test_handle_model_config_update_same_value(self, service_mocks):
        """Test handle_model_config when model_id is same as existing"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = 123
        tenant_config_dict = {"LLM_ID": "123"}

        # Execute
        handle_model_config(tenant_id, user_id, config_key,
                            model_id, tenant_config_dict)

        # Assert
        service_mocks['tenant_config_manager'].update_single_config.assert_called_once_with(
            tenant_id, config_key)
        service_mocks['tenant_config_manager'].delete_single_config.assert_not_called()
        service_mocks['tenant_config_manager'].set_single_config.assert_not_called()

    def test_handle_model_config_update_different_value(self, service_mocks):
        """Test handle_model_config when model_id is different from existing"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = 456
        tenant_config_dict = {"LLM_ID": "123"}

        # Execute
        handle_model_config(tenant_id, user_id, config_key,
                            model_id, tenant_config_dict)

        # Assert
        service_mocks['tenant_config_manager'].delete_single_config.assert_called_once_with(
            tenant_id, config_key)
        service_mocks['tenant_config_manager'].set_single_config.assert_called_once_with(
            user_id, tenant_id, config_key, model_id
        )

    def test_handle_model_config_non_int_value(self, service_mocks):
        """Test handle_model_config when existing value is not an int"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = 456
        tenant_config_dict = {"LLM_ID": "not-an-int"}

        # Execute
        handle_model_config(tenant_id, user_id, config_key,
                            model_id, tenant_config_dict)

        # Assert
        service_mocks['tenant_config_manager'].delete_single_config.assert_called_once_with(
            tenant_id, config_key)
        service_mocks['tenant_config_manager'].set_single_config.assert_called_once_with(
            user_id, tenant_id, config_key, model_id
        )

    def test_handle_model_config_key_not_exists(self, service_mocks):
        """Test handle_model_config when config key doesn't exist"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = 456
        tenant_config_dict = {}

        # Execute
        handle_model_config(tenant_id, user_id, config_key,
                            model_id, tenant_config_dict)

        # Assert
        service_mocks['tenant_config_manager'].delete_single_config.assert_not_called()
        service_mocks['tenant_config_manager'].set_single_config.assert_called_once_with(
            user_id, tenant_id, config_key, model_id
        )

    def test_handle_model_config_none_model_id(self, service_mocks):
        """Test handle_model_config when model_id is None"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = None
        tenant_config_dict = {"LLM_ID": "123"}

        # Execute
        handle_model_config(tenant_id, user_id, config_key,
                            model_id, tenant_config_dict)

        # Assert
        service_mocks['tenant_config_manager'].delete_single_config.assert_called_once_with(
            tenant_id, config_key)
        service_mocks['tenant_config_manager'].set_single_config.assert_not_called()

    def test_handle_model_config_empty_string_model_id(self, service_mocks):
        """Test handle_model_config when model_id is empty string"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = ""
        tenant_config_dict = {"LLM_ID": "123"}

        # Execute
        handle_model_config(tenant_id, user_id, config_key,
                            model_id, tenant_config_dict)

        # Assert - empty string is not falsy, so it should delete existing and set new value
        service_mocks['tenant_config_manager'].delete_single_config.assert_called_once_with(
            tenant_id, config_key)
        service_mocks['tenant_config_manager'].set_single_config.assert_called_once_with(
            user_id, tenant_id, config_key, model_id
        )

    def test_handle_model_config_invalid_string_model_id(self, service_mocks):
        """Test handle_model_config when model_id is non-numeric string"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = "invalid"
        tenant_config_dict = {"LLM_ID": "123"}

        # Execute
        handle_model_config(tenant_id, user_id, config_key,
                            model_id, tenant_config_dict)

        # Assert - should delete existing and set new value
        service_mocks['tenant_config_manager'].delete_single_config.assert_called_once_with(
            tenant_id, config_key)
        service_mocks['tenant_config_manager'].set_single_config.assert_called_once_with(
            user_id, tenant_id, config_key, model_id
        )

    def test_handle_model_config_empty_tenant_config_dict(self, service_mocks):
        """Test handle_model_config when tenant_config_dict is empty"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = 456
        tenant_config_dict = {}

        # Execute
        handle_model_config(tenant_id, user_id, config_key,
                            model_id, tenant_config_dict)

        # Assert - should set new config since key doesn't exist
        service_mocks['tenant_config_manager'].delete_single_config.assert_not_called()
        service_mocks['tenant_config_manager'].set_single_config.assert_called_once_with(
            user_id, tenant_id, config_key, model_id
        )

    def test_handle_model_config_zero_model_id_with_existing_config(self, service_mocks):
        """Test handle_model_config when model_id is 0 and config exists"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = 0
        tenant_config_dict = {"LLM_ID": "123"}

        # Execute
        handle_model_config(tenant_id, user_id, config_key,
                            model_id, tenant_config_dict)

        # Assert - should delete existing and set new value (0 is falsy but should be treated as valid model_id)
        service_mocks['tenant_config_manager'].delete_single_config.assert_called_once_with(
            tenant_id, config_key)
        service_mocks['tenant_config_manager'].set_single_config.assert_called_once_with(
            user_id, tenant_id, config_key, model_id
        )


class TestSaveConfigImpl:
    """Test cases for save_config_impl function"""

    @pytest.mark.asyncio
    async def test_save_config_impl_success(self, service_mocks):
        """Test successful configuration saving"""
        # Setup
        config = MagicMock()
        config_dict = {
            "app": {
                "name": "Test App",
                "description": "Test Description"
            },
            "models": {
                "llm": {
                    "modelName": "gpt-4",
                    "displayName": "GPT-4",
                    "apiConfig": {
                        "apiKey": "test-api-key",
                        "baseUrl": "https://api.openai.com"
                    }
                },
                "embedding": {
                    "modelName": "text-embedding-ada-002",
                    "displayName": "Ada Embeddings",
                    "dimension": 1536
                }
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config
        service_mocks['tenant_config_manager'].load_config.return_value = {
            "APP_NAME": "Old App Name"
        }

        # Mock get_env_key
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()

        # Mock safe_value
        service_mocks['safe_value'].side_effect = lambda value: str(
            value) if value is not None else ""

        # Mock get_model_id_by_display_name
        service_mocks['get_model_id'].side_effect = [
            "llm-model-id", "embedding-model-id"]

        # Execute
        result = await save_config_impl(config, tenant_id, user_id)

        # Assert
        # save_config_impl returns None, JSONResponse is created in the endpoint
        assert result is None

        # Verify tenant_config_manager calls
        service_mocks['tenant_config_manager'].load_config.assert_called_once_with(
            tenant_id)

        # Verify logger
        service_mocks['logger'].info.assert_called_once_with(
            "Configuration saved successfully")

    @pytest.mark.asyncio
    async def test_save_config_impl_success_model(self, service_mocks):
        """Test successful configuration saving"""
        # Setup
        config = MagicMock()
        config_dict = {
            "app": {
                "name": "Test App",
                "description": "Test Description"
            },
            "models": {
                "llm": {
                    "modelName": "gpt-4",
                    "displayName": "GPT-4",
                    "apiConfig": {
                        "apiKey": "test-api-key",
                        "baseUrl": "https://api.openai.com"
                    }
                },
                "embedding": {
                    "modelName": "text-embedding-ada-002",
                    "displayName": "Ada Embeddings",
                    "dimension": 1536
                }
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config
        service_mocks['tenant_config_manager'].load_config.return_value = {
            "APP_NAME": "Old App Name"
        }

        # Mock get_env_key
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()

        # Mock safe_value
        service_mocks['safe_value'].side_effect = lambda value: str(
            value) if value is not None else ""

        # Mock get_model_id_by_display_name
        service_mocks['get_model_id'].side_effect = [
            "llm-model-id", "embedding-model-id"]

        # Execute
        result = await save_config_impl(config, tenant_id, user_id)

        # Assert
        # save_config_impl returns None, JSONResponse is created in the endpoint
        assert result is None

        # Verify tenant_config_manager calls
        service_mocks['tenant_config_manager'].load_config.assert_called_once_with(
            tenant_id)

        # Verify logger
        service_mocks['logger'].info.assert_called_once_with(
            "Configuration saved successfully")

    @pytest.mark.asyncio
    async def test_save_config_impl_success_embedding_model(self, service_mocks):
        """Test successful configuration saving"""
        # Setup
        config = MagicMock()
        config_dict = {
            "app": {
                "name": "Test App",
                "description": "Test Description"
            },
            "models": {
                "llm": {
                    "modelName": "gpt-4",
                    "displayName": "GPT-4",
                    "apiConfig": {
                        "apiKey": "test-api-key",
                        "baseUrl": "https://api.openai.com"
                    }
                },
                "embedding": {
                    "modelName": "text-embedding-ada-002",
                    "displayName": "Ada Embeddings",
                    "dimension": 1536,
                    "apiConfig": {
                        "apiKey": "test-api-key",
                        "baseUrl": "https://api.openai.com"
                    }
                }
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config
        service_mocks['tenant_config_manager'].load_config.return_value = {
            "APP_NAME": "Old App Name"
        }

        # Mock get_env_key
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()

        # Mock safe_value
        service_mocks['safe_value'].side_effect = lambda value: str(
            value) if value is not None else ""

        # Mock get_model_id_by_display_name
        service_mocks['get_model_id'].side_effect = [
            "llm-model-id", "embedding-model-id"]

        # Execute
        result = await save_config_impl(config, tenant_id, user_id)

        # Assert
        # save_config_impl returns None, JSONResponse is created in the endpoint
        assert result is None

        # Verify tenant_config_manager calls
        service_mocks['tenant_config_manager'].load_config.assert_called_once_with(
            tenant_id)

        # Verify logger
        service_mocks['logger'].info.assert_called_once_with(
            "Configuration saved successfully")

    @pytest.mark.asyncio
    async def test_save_config_impl_model_config(self, service_mocks):
        """Test saving configuration with empty model config"""
        # Setup
        config = MagicMock()
        config_dict = {
            "app": {
                "name": "Test App"
            },
            "models": {
                "llm": None,
                "embedding": {}
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config
        service_mocks['tenant_config_manager'].load_config.return_value = {
            "NAME": "Test App"
        }

        # Mock get_env_key
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()

        # Mock safe_value
        service_mocks['safe_value'].side_effect = lambda value: str(
            value) if value is not None else ""

        # Execute
        result = await save_config_impl(config, tenant_id, user_id)

        # Assert
        assert result is None

        # Verify that no model config handling was done for None model
        service_mocks['get_model_id'].assert_not_called()

    @pytest.mark.asyncio
    async def test_save_config_impl_success_no_model(self, service_mocks):
        """Test successful configuration saving"""
        # Setup
        config = MagicMock()
        config_dict = {
            "app": {
                "name": "Test App",
                "description": "Test Description"
            },
            "models": {
                "llm": {
                    "modelName": "",
                    "displayName": "GPT-4",
                    "apiConfig": {
                        "apiKey": "test-api-key",
                        "baseUrl": "https://api.openai.com"
                    }
                },
                "embedding": {
                    "modelName": "text-embedding-ada-002",
                    "displayName": "Ada Embeddings",
                    "dimension": 1536
                }
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config
        service_mocks['tenant_config_manager'].load_config.return_value = {
            "APP_NAME": "Old App Name"
        }

        # Mock get_env_key
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()

        # Mock safe_value
        service_mocks['safe_value'].side_effect = lambda value: str(
            value) if value is not None else ""

        # Mock get_model_id_by_display_name
        service_mocks['get_model_id'].side_effect = [
            "llm-model-id", "embedding-model-id"]

        # Execute
        result = await save_config_impl(config, tenant_id, user_id)

        # Assert
        # save_config_impl returns None, JSONResponse is created in the endpoint
        assert result is None

        # Verify tenant_config_manager calls
        service_mocks['tenant_config_manager'].load_config.assert_called_once_with(
            tenant_id)

        # Verify logger
        service_mocks['logger'].info.assert_called_once_with(
            "Configuration saved successfully")

    @pytest.mark.asyncio
    async def test_save_config_impl_non_model_config(self, service_mocks):
        """Test saving configuration with empty model config"""
        # Setup
        config = MagicMock()
        config_dict = {
            "app": {
                "name": ""
            },
            "models": {
                "llm": None,
                "embedding": {}
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config
        service_mocks['tenant_config_manager'].load_config.return_value = {
            "NAME": "Test APP"
        }

        # Mock get_env_key
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()

        # Mock safe_value
        service_mocks['safe_value'].side_effect = lambda value: str(
            value) if value is not None else ""

        # Execute
        result = await save_config_impl(config, tenant_id, user_id)

        # Assert
        assert result is None

        # Verify that no model config handling was done for None model
        service_mocks['get_model_id'].assert_not_called()

    @pytest.mark.asyncio
    async def test_save_config_impl_in_model_config(self, service_mocks):
        """Test saving configuration with empty model config"""
        # Setup
        config = MagicMock()
        config_dict = {
            "app": {
                "name": "Test app"
            },
            "models": {
                "llm": None,
                "embedding": {}
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config
        service_mocks['tenant_config_manager'].load_config.return_value = {
            "NAME": "Test APP"
        }

        # Mock get_env_key
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()

        # Mock safe_value
        service_mocks['safe_value'].side_effect = lambda value: str(
            value) if value is not None else ""

        # Execute
        result = await save_config_impl(config, tenant_id, user_id)

        # Assert
        assert result is None

        # Verify that no model config handling was done for None model
        service_mocks['get_model_id'].assert_not_called()

    @pytest.mark.asyncio
    async def test_save_config_impl_app_config_updates(self, service_mocks):
        """Test app configuration updates"""
        # Setup
        config = MagicMock()
        config_dict = {
            "app": {
                "name": "New App Name",
                "description": "New Description"
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config with different values
        service_mocks['tenant_config_manager'].load_config.return_value = {
            "APP_NAME": "Old App Name",
            "APP_DESCRIPTION": "Old Description"
        }

        # Mock get_env_key
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()

        # Mock safe_value to return the same value consistently
        def mock_safe_value(value):
            return str(value) if value is not None else ""

        service_mocks['safe_value'].side_effect = mock_safe_value

        # Execute
        result = await save_config_impl(config, tenant_id, user_id)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_save_config_impl_app_config_same_values(self, service_mocks):
        """Test app configuration when values are the same"""
        # Setup
        config = MagicMock()
        config_dict = {
            "app": {
                "name": "Same App Name",
                "description": "Same Description"
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config with same values
        service_mocks['tenant_config_manager'].load_config.return_value = {
            "APP_NAME": "Same App Name",
            "APP_DESCRIPTION": "Same Description"
        }

        # Mock get_env_key
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()

        # Mock safe_value
        service_mocks['safe_value'].side_effect = lambda value: str(
            value) if value is not None else ""

        # Execute
        result = await save_config_impl(config, tenant_id, user_id)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_save_config_impl_app_config_empty_values(self, service_mocks):
        """Test app configuration when values are empty"""
        # Setup
        config = MagicMock()
        config_dict = {
            "app": {
                "name": "",
                "description": ""
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config with non-empty values
        service_mocks['tenant_config_manager'].load_config.return_value = {
            "APP_NAME": "Old App Name",
            "APP_DESCRIPTION": "Old Description"
        }

        # Mock get_env_key
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()

        # Mock safe_value
        service_mocks['safe_value'].side_effect = lambda value: str(
            value) if value is not None else ""

        # Execute
        result = await save_config_impl(config, tenant_id, user_id)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_save_config_impl_app_config_new_keys(self, service_mocks):
        """Test app configuration when keys don't exist in tenant config"""
        # Setup
        config = MagicMock()
        config_dict = {
            "app": {
                "name": "New App Name",
                "description": "New Description"
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config with no existing keys
        service_mocks['tenant_config_manager'].load_config.return_value = {}

        # Mock get_env_key
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()

        # Mock safe_value
        service_mocks['safe_value'].side_effect = lambda value: str(
            value) if value is not None else ""

        # Execute
        result = await save_config_impl(config, tenant_id, user_id)

        # Assert
        assert result is None

        # Verify that set_single_config is called for new keys
        assert service_mocks['tenant_config_manager'].set_single_config.call_count == 2
        service_mocks['tenant_config_manager'].delete_single_config.assert_not_called()
        service_mocks['tenant_config_manager'].update_single_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_config_impl_model_dump_exception(self, service_mocks):
        """Test save_config_impl when config.model_dump() raises exception"""
        # Setup
        config = MagicMock()
        config.model_dump.side_effect = Exception("Serialization failed")

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Execute and assert exception is raised
        with pytest.raises(Exception) as exc_info:
            await save_config_impl(config, tenant_id, user_id)

        assert "Serialization failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_save_config_impl_load_config_exception(self, service_mocks):
        """Test save_config_impl when load_config raises exception"""
        # Setup
        config = MagicMock()
        config_dict = {"app": {"name": "Test App"}}
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock load_config to raise exception
        service_mocks['tenant_config_manager'].load_config.side_effect = Exception(
            "Database connection failed")

        # Execute and assert exception is raised
        with pytest.raises(Exception) as exc_info:
            await save_config_impl(config, tenant_id, user_id)

        assert "Database connection failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_save_config_impl_get_model_id_exception(self, service_mocks):
        """Test save_config_impl when get_model_id_by_display_name raises exception"""
        # Setup
        config = MagicMock()
        config_dict = {
            "app": {"name": "Test App"},
            "models": {
                "llm": {
                    "modelName": "gpt-4",
                    "displayName": "GPT-4"
                }
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config
        service_mocks['tenant_config_manager'].load_config.return_value = {}

        # Mock get_env_key
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()

        # Mock safe_value
        service_mocks['safe_value'].side_effect = lambda value: str(
            value) if value is not None else ""

        # Mock get_model_id_by_display_name to raise exception
        service_mocks['get_model_id'].side_effect = Exception(
            "Model not found")

        # Execute and assert exception is raised
        with pytest.raises(Exception) as exc_info:
            await save_config_impl(config, tenant_id, user_id)

        assert "Model not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_save_config_impl_empty_config_dict(self, service_mocks):
        """Test save_config_impl with empty config_dict"""
        # Setup
        config = MagicMock()
        config_dict = {}
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config
        service_mocks['tenant_config_manager'].load_config.return_value = {}

        # Execute
        result = await save_config_impl(config, tenant_id, user_id)

        # Assert
        assert result is None
        # Should not call any config operations since config_dict is empty
        service_mocks['tenant_config_manager'].set_single_config.assert_not_called()
        service_mocks['tenant_config_manager'].delete_single_config.assert_not_called()
        service_mocks['tenant_config_manager'].update_single_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_config_impl_empty_models_section(self, service_mocks):
        """Test save_config_impl with empty models section"""
        # Setup
        config = MagicMock()
        config_dict = {
            "app": {"name": "Test App"},
            "models": {}
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config
        service_mocks['tenant_config_manager'].load_config.return_value = {}

        # Mock get_env_key
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()

        # Mock safe_value
        service_mocks['safe_value'].side_effect = lambda value: str(
            value) if value is not None else ""

        # Execute
        result = await save_config_impl(config, tenant_id, user_id)

        # Assert
        assert result is None
        # Should only process app config, not model config
        service_mocks['get_model_id'].assert_not_called()

    @pytest.mark.asyncio
    async def test_save_config_impl_embedding_without_api_config(self, service_mocks):
        """Test save_config_impl with embedding model without apiConfig"""
        # Setup
        config = MagicMock()
        config_dict = {
            "app": {"name": "Test App"},
            "models": {
                "embedding": {
                    "modelName": "text-embedding-ada-002",
                    "displayName": "Ada Embeddings",
                    "dimension": 1536
                }
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        # Mock tenant config
        service_mocks['tenant_config_manager'].load_config.return_value = {}

        # Mock get_env_key
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()

        # Mock safe_value
        service_mocks['safe_value'].side_effect = lambda value: str(
            value) if value is not None else ""

        # Mock get_model_id_by_display_name
        service_mocks['get_model_id'].return_value = "embedding-model-id"

        # Execute
        result = await save_config_impl(config, tenant_id, user_id)

        # Assert
        assert result is None
        # Should not try to access apiConfig since it's not present
        service_mocks['logger'].info.assert_called_once_with(
            "Configuration saved successfully")


class TestLoadConfigImpl:
    """Test cases for load_config_impl function"""

    @pytest.mark.asyncio
    async def test_load_config_impl_english(self, service_mocks):
        """Test loading configuration with English language"""
        # Setup
        language = "en"
        tenant_id = "test_tenant_id"

        # Mock model configurations
        llm_config = {
            "display_name": "Test LLM",
            "api_key": "test-api-key",
            "base_url": "https://test-url.com"
        }
        service_mocks['tenant_config_manager'].get_model_config.side_effect = [
            llm_config,  # LLM_ID
            {},          # LLM_SECONDARY_ID
            {},          # EMBEDDING_ID
            {},          # MULTI_EMBEDDING_ID
            {},          # RERANK_ID
            {},          # VLM_ID
            {},          # STT_ID
            {}           # TTS_ID
        ]

        # Mock app configurations
        def mock_get_app_config(key, tenant_id=None):
            config_map = {
                "APP_NAME": "Custom App Name",
                "APP_DESCRIPTION": "Custom description",
                "TENANT_NAME": "Test Tenant",
                "DEFAULT_GROUP_ID": "default-group-123",
                "ICON_TYPE": "preset",
                "AVATAR_URI": "avatar-uri",
                "CUSTOM_ICON_URL": "https://custom-icon.com",
                "DATAMATE_URL": "https://datamate.example.com"
            }
            return config_map.get(key)

        service_mocks['tenant_config_manager'].get_app_config.side_effect = mock_get_app_config

        # Mock model name conversion to return string values
        service_mocks['get_model_name'].side_effect = [
            "gpt-4",     # LLM_ID
            "",          # LLM_SECONDARY_ID
            "",          # EMBEDDING_ID
            "",          # MULTI_EMBEDDING_ID
            "",          # RERANK_ID
            "",          # VLM_ID
            "",          # STT_ID
            ""           # TTS_ID
        ]

        # Execute
        result = await load_config_impl(language, tenant_id)

        assert result["app"]["name"] == "Custom App Name"
        assert result["app"]["description"] == "Custom description"
        assert result["app"]["tenantName"] == "Test Tenant"
        assert result["app"]["defaultGroupId"] == "default-group-123"
        assert result["app"]["icon"]["type"] == "preset"
        assert result["app"]["icon"]["avatarUri"] == "avatar-uri"
        assert result["app"]["icon"]["customUrl"] == "https://custom-icon.com"
        assert result["models"]["llm"]["displayName"] == "Test LLM"

    @pytest.mark.asyncio
    async def test_load_config_impl_chinese(self, service_mocks):
        """Test loading configuration with Chinese language"""
        # Setup
        language = "zh"
        tenant_id = "test_tenant_id"

        # Mock empty model configurations
        service_mocks['tenant_config_manager'].get_model_config.return_value = {}

        # Mock empty app configurations (to use defaults)
        service_mocks['tenant_config_manager'].get_app_config.return_value = None

        # Mock model name conversion to return string values
        service_mocks['get_model_name'].return_value = ""

        # Execute
        result = await load_config_impl(language, tenant_id)

        # Check Chinese default values
        assert result["app"]["name"] == "Nexent 智能体"
        assert result["app"]["description"] == "Nexent 是一个开源智能体平台，基于 MCP 工具生态系统，提供灵活的多模态问答、检索、数据分析、处理等能力。"
        assert result["app"]["tenantName"] == ""
        assert result["app"]["defaultGroupId"] == ""
        assert result["app"]["icon"]["type"] == "preset"
        assert result["app"]["icon"]["avatarUri"] == ""
        assert result["app"]["icon"]["customUrl"] == ""

    @pytest.mark.asyncio
    async def test_load_config_impl_with_embedding_dimension(self, service_mocks):
        """Test loading configuration with embedding dimension"""
        # Setup
        language = "en"
        tenant_id = "test_tenant_id"

        # Mock model configurations with max_tokens and model_type
        embedding_config = {
            "max_tokens": 1536,
            "model_type": "embedding",
            "base_url": "http://test.com",
            "api_key": "test_key",
            "dimension": 1536
        }
        multi_embedding_config = {
            "max_tokens": 768,
            "model_type": "multi_embedding",
            "base_url": "http://test.com",
            "api_key": "test_key",
            "dimension": 768
        }

        service_mocks['tenant_config_manager'].get_model_config.side_effect = [
            {},          # LLM_ID
            embedding_config,  # EMBEDDING_ID
            multi_embedding_config,  # MULTI_EMBEDDING_ID
            {},          # RERANK_ID
            {},          # VLM_ID
            {},          # STT_ID
            {}           # TTS_ID
        ]

        # Mock app configurations
        service_mocks['tenant_config_manager'].get_app_config.return_value = None

        # Mock model name conversion to return string values
        service_mocks['get_model_name'].side_effect = [
            "",          # LLM_ID
            "text-embedding-ada-002",  # EMBEDDING_ID
            "text-embedding-3-small",  # MULTI_EMBEDDING_ID
            "",          # RERANK_ID
            "",          # VLM_ID
            "",          # STT_ID
            ""           # TTS_ID
        ]

        # Execute
        result = await load_config_impl(language, tenant_id)

        # Check app config (should use defaults)
        assert result["app"]["name"] == "Nexent Agent"
        assert result["app"]["description"] == "Nexent is an open-source agent platform built on the MCP tool ecosystem, providing flexible multi-modal Q&A, retrieval, data analysis, and processing capabilities."
        assert result["app"]["tenantName"] == ""
        assert result["app"]["defaultGroupId"] == ""

        # Check dimension values
        assert result["models"]["embedding"]["dimension"] == 1536
        assert result["models"]["multiEmbedding"]["dimension"] == 768

    @pytest.mark.asyncio
    async def test_load_config_impl_empty_models(self, service_mocks):
        """Test loading configuration with empty model configs"""
        # Setup
        language = "en"
        tenant_id = "test_tenant_id"

        # Mock empty model configurations
        service_mocks['tenant_config_manager'].get_model_config.return_value = {}

        # Mock empty app configurations
        service_mocks['tenant_config_manager'].get_app_config.return_value = None

        # Mock model name conversion to return string values
        service_mocks['get_model_name'].return_value = ""

        # Execute
        result = await load_config_impl(language, tenant_id)

        # Check app config (should use defaults)
        assert result["app"]["name"] == "Nexent Agent"
        assert result["app"]["description"] == "Nexent is an open-source agent platform built on the MCP tool ecosystem, providing flexible multi-modal Q&A, retrieval, data analysis, and processing capabilities."
        assert result["app"]["tenantName"] == ""
        assert result["app"]["defaultGroupId"] == ""

        # Check that models have empty values
        assert result["models"]["llm"]["name"] == ""
        assert result["models"]["embedding"]["name"] == ""

    @pytest.mark.asyncio
    async def test_load_config_impl_exception(self, service_mocks):
        """Test loading configuration when build_app_config throws an exception"""
        # Setup
        language = "en"
        tenant_id = "test_tenant_id"

        # Mock build_app_config to raise an exception
        with patch('backend.services.config_sync_service.build_app_config') as mock_build_app_config:
            mock_build_app_config.side_effect = Exception(
                "Database connection failed")

            # Execute and assert that exception is raised
            with pytest.raises(Exception) as exc_info:
                await load_config_impl(language, tenant_id)

            # Verify the exception message
            assert f"Failed to load config for tenant {tenant_id}." in str(
                exc_info.value)

            # Verify that logger.error was called
            service_mocks['logger'].error.assert_called_once_with(
                f"Failed to load config for tenant {tenant_id}: Database connection failed"
            )

    @pytest.mark.asyncio
    async def test_load_config_impl_empty_language(self, service_mocks):
        """Test loading configuration with empty language"""
        # Setup
        language = ""
        tenant_id = "test_tenant_id"

        # Mock empty configurations to avoid default values
        service_mocks['tenant_config_manager'].get_app_config.return_value = None
        service_mocks['tenant_config_manager'].get_model_config.return_value = {}

        # Mock model name conversion to return string values
        service_mocks['get_model_name'].return_value = ""

        # Execute
        result = await load_config_impl(language, tenant_id)

        # Assert - should use English defaults when language is empty
        assert result["app"]["name"] == "Nexent Agent"  # DEFAULT_APP_NAME_EN
        assert result["models"]["llm"]["name"] == ""

    @pytest.mark.asyncio
    async def test_load_config_impl_invalid_language(self, service_mocks):
        """Test loading configuration with invalid language"""
        # Setup
        language = "invalid"
        tenant_id = "test_tenant_id"

        # Mock empty configurations to avoid default values
        service_mocks['tenant_config_manager'].get_app_config.return_value = None
        service_mocks['tenant_config_manager'].get_model_config.return_value = {}

        # Mock model name conversion to return string values
        service_mocks['get_model_name'].return_value = ""

        # Execute
        result = await load_config_impl(language, tenant_id)

        # Assert - should use English defaults when language is invalid
        assert result["app"]["name"] == "Nexent Agent"  # DEFAULT_APP_NAME_EN
        assert result["models"]["llm"]["name"] == ""

    @pytest.mark.asyncio
    async def test_load_config_impl_empty_tenant_id(self, service_mocks):
        """Test loading configuration with empty tenant_id"""
        # Setup
        language = "en"
        tenant_id = ""

        # Mock empty configurations to avoid default values
        service_mocks['tenant_config_manager'].get_app_config.return_value = None
        service_mocks['tenant_config_manager'].get_model_config.return_value = {}

        # Mock model name conversion to return string values
        service_mocks['get_model_name'].return_value = ""

        # Execute
        result = await load_config_impl(language, tenant_id)

        # Assert - should still work with empty tenant_id
        assert result["app"]["name"] == "Nexent Agent"
        assert result["models"]["llm"]["name"] == ""

    @pytest.mark.asyncio
    async def test_load_config_impl_both_build_functions_exception(self, service_mocks):
        """Test loading configuration when both build functions raise exceptions"""
        # Setup
        language = "en"
        tenant_id = "test_tenant_id"

        # Mock build_app_config to raise an exception
        with patch('backend.services.config_sync_service.build_app_config') as mock_build_app_config, \
                patch('backend.services.config_sync_service.build_models_config') as mock_build_models_config:

            mock_build_app_config.side_effect = Exception("App config failed")
            mock_build_models_config.side_effect = Exception(
                "Models config failed")

            # Execute and assert that exception is raised
            with pytest.raises(Exception) as exc_info:
                await load_config_impl(language, tenant_id)

            # Verify the exception message
            assert f"Failed to load config for tenant {tenant_id}." in str(
                exc_info.value)

            # Verify that logger.error was called
            service_mocks['logger'].error.assert_called_once_with(
                f"Failed to load config for tenant {tenant_id}: App config failed"
            )

    def test_build_models_config_partial_success(self, service_mocks):
        """Test build_models_config with some successful and some failed configs"""
        # Setup
        tenant_id = "test_tenant_id"

        # Mock get_model_config to succeed for some configs and fail for others
        def side_effect(config_key, tenant_id=None):
            if config_key == "LLM_ID":
                return {
                    "display_name": "Test LLM",
                    "api_key": "test-api-key",
                    "base_url": "https://test-url.com"
                }
            elif config_key == "EMBEDDING_ID":
                raise Exception("Database timeout")
            else:
                return {}

        service_mocks['tenant_config_manager'].get_model_config.side_effect = side_effect

        # Mock model name conversion
        service_mocks['get_model_name'].side_effect = [
            "gpt-4",  # LLM_ID - successful
            "",  # LLM_SECONDARY_ID
            "",  # EMBEDDING_ID - will be empty due to exception
            "",  # MULTI_EMBEDDING_ID
            "",  # RERANK_ID
            "",  # VLM_ID
            "",  # STT_ID
            ""  # TTS_ID
        ]

        # Execute
        result = build_models_config(tenant_id)

        # Assert
        assert isinstance(result, dict)

        # Verify successful config
        assert result["llm"]["displayName"] == "Test LLM"
        assert result["llm"]["apiConfig"]["apiKey"] == "test-api-key"

        # Verify failed config was handled gracefully
        assert result["embedding"]["name"] == ""
        assert result["embedding"]["displayName"] == ""

        # Verify that logger.warning was called for the failed config
        service_mocks['logger'].warning.assert_called_with(
            "Failed to get config for EMBEDDING_ID: Database timeout"
        )

    def test_build_models_config_all_success(self, service_mocks):
        """Test build_models_config with all configurations successful"""
        # Setup
        tenant_id = "test_tenant_id"

        # Mock successful model configurations for all model types
        def side_effect(config_key, tenant_id=None):
            configs = {
                "LLM_ID": {
                    "display_name": "GPT-4",
                    "api_key": "test-key",
                    "base_url": "https://api.openai.com"
                },
                "LLM_SECONDARY_ID": {},
                "EMBEDDING_ID": {
                    "display_name": "Ada Embeddings",
                    "api_key": "test-key",
                    "base_url": "https://api.openai.com",
                    "max_tokens": 1536,
                    "model_type": "embedding"
                },
                "MULTI_EMBEDDING_ID": {},
                "RERANK_ID": {},
                "VLM_ID": {},
                "STT_ID": {},
                "TTS_ID": {}
            }
            return configs.get(config_key, {})

        service_mocks['tenant_config_manager'].get_model_config.side_effect = side_effect

        # Execute
        result = build_models_config(tenant_id)

        # Assert
        assert isinstance(result, dict)
        assert len(result) == 7  # All model types should be present

        # Verify successful configs
        assert result["llm"]["displayName"] == "GPT-4"
        assert result["llm"]["apiConfig"]["apiKey"] == "test-key"

        # Verify no warnings were logged (all successful)
        service_mocks['logger'].warning.assert_not_called()

    def test_build_models_config_all_failures(self, service_mocks):
        """Test build_models_config when all configurations fail"""
        # Setup
        tenant_id = "test_tenant_id"

        # Mock all get_model_config calls to raise exceptions
        service_mocks['tenant_config_manager'].get_model_config.side_effect = Exception(
            "Database completely down")

        # Execute
        result = build_models_config(tenant_id)

        # Assert
        assert isinstance(result, dict)
        # All model types should still be present with empty configs
        assert len(result) == 7

        # All configs should be empty due to exceptions
        for model_key in ["llm", "embedding", "multiEmbedding", "rerank", "vlm", "stt", "tts"]:
            assert result[model_key]["name"] == ""
            assert result[model_key]["displayName"] == ""
            assert result[model_key]["apiConfig"]["apiKey"] == ""
            assert result[model_key]["apiConfig"]["modelUrl"] == ""

        # Verify that logger.warning was called for each model type
        assert service_mocks['logger'].warning.call_count == 7
        warning_calls = service_mocks['logger'].warning.call_args_list
        expected_configs = ["LLM_ID", "EMBEDDING_ID", "MULTI_EMBEDDING_ID",
                            "RERANK_ID", "VLM_ID", "STT_ID", "TTS_ID"]
        for i, config_key in enumerate(expected_configs):
            assert f"Failed to get config for {config_key}: Database completely down" in warning_calls[
                i][0][0]


class TestBuildAppConfig:
    """Test cases for build_app_config function"""

    def test_build_app_config_english_with_values(self, service_mocks):
        """Test build_app_config with English language and all config values present"""
        # Setup
        language = "en"
        tenant_id = "test_tenant_id"

        # Mock all app config values
        def mock_get_app_config(key, tenant_id=None):
            config_map = {
                "APP_NAME": "Custom App Name",
                "APP_DESCRIPTION": "Custom description",
                "TENANT_NAME": None,  # TENANT_NAME (use default)
                "DEFAULT_GROUP_ID": None,  # DEFAULT_GROUP_ID (use default)
                "ICON_TYPE": "custom",
                "AVATAR_URI": "avatar-uri",
                "CUSTOM_ICON_URL": "https://custom-icon.com",
                "DATAMATE_URL": "https://datamate.example.com"
            }
            return config_map.get(key)

        service_mocks['tenant_config_manager'].get_app_config.side_effect = mock_get_app_config

        # Mock MODEL_ENGINE_ENABLED
        with patch('backend.services.config_sync_service.MODEL_ENGINE_ENABLED', 'false'):
            # Execute
            result = build_app_config(language, tenant_id)

            # Assert
            assert result["name"] == "Custom App Name"
            assert result["description"] == "Custom description"
            assert result["tenantName"] == ""  # None returns default empty string
            assert result["defaultGroupId"] == ""  # None returns default empty string
            assert result["icon"]["type"] == "custom"
            assert result["icon"]["avatarUri"] == "avatar-uri"
            assert result["icon"]["customUrl"] == "https://custom-icon.com"
            assert result["modelEngineEnabled"] == False

        # Verify calls
        expected_calls = [
            ("APP_NAME", tenant_id),
            ("APP_DESCRIPTION", tenant_id),
            ("TENANT_NAME", tenant_id),
            ("DEFAULT_GROUP_ID", tenant_id),
            ("ICON_TYPE", tenant_id),
            ("AVATAR_URI", tenant_id),
            ("CUSTOM_ICON_URL", tenant_id),
            ("DATAMATE_URL", tenant_id)
        ]
        assert service_mocks['tenant_config_manager'].get_app_config.call_count == 8
        service_mocks['tenant_config_manager'].get_app_config.assert_has_calls(
            [call(key, tenant_id=tenant_id)
             for key, _ in expected_calls]
        )

    def test_build_app_config_chinese_defaults(self, service_mocks):
        """Test build_app_config with Chinese language and no config values"""
        # Setup
        language = "zh"
        tenant_id = "test_tenant_id"

        # Mock all app config values to return None (use defaults)
        service_mocks['tenant_config_manager'].get_app_config.return_value = None

        # Mock MODEL_ENGINE_ENABLED
        with patch('backend.services.config_sync_service.MODEL_ENGINE_ENABLED', 'false'):
            # Execute
            result = build_app_config(language, tenant_id)

            # Assert - should use Chinese defaults
            assert result["name"] == "Nexent 智能体"  # DEFAULT_APP_NAME_ZH
            # DEFAULT_APP_DESCRIPTION_ZH
            assert result["description"] == "Nexent 是一个开源智能体平台，基于 MCP 工具生态系统，提供灵活的多模态问答、检索、数据分析、处理等能力。"
            assert result["icon"]["type"] == "preset"
            assert result["icon"]["avatarUri"] == ""
            assert result["icon"]["customUrl"] == ""
            assert result["modelEngineEnabled"] == False

    def test_build_app_config_english_defaults(self, service_mocks):
        """Test build_app_config with English language and no config values"""
        # Setup
        language = "en"
        tenant_id = "test_tenant_id"

        # Mock all app config values to return None (use defaults)
        service_mocks['tenant_config_manager'].get_app_config.return_value = None

        # Mock MODEL_ENGINE_ENABLED
        with patch('backend.services.config_sync_service.MODEL_ENGINE_ENABLED', 'false'):
            # Execute
            result = build_app_config(language, tenant_id)

            # Assert - should use English defaults
            assert result["name"] == "Nexent Agent"  # DEFAULT_APP_NAME_EN
            # DEFAULT_APP_DESCRIPTION_EN
            assert result["description"] == "Nexent is an open-source agent platform built on the MCP tool ecosystem, providing flexible multi-modal Q&A, retrieval, data analysis, and processing capabilities."
            assert result["icon"]["type"] == "preset"
            assert result["icon"]["avatarUri"] == ""
            assert result["icon"]["customUrl"] == ""
            assert result["modelEngineEnabled"] == False

    def test_build_app_config_partial_values(self, service_mocks):
        """Test build_app_config with some config values present and some missing"""
        # Setup
        language = "en"
        tenant_id = "test_tenant_id"

        # Mock partial app config values
        def side_effect(config_key, tenant_id=None):
            config_map = {
                "APP_NAME": "Custom App Name",
                "APP_DESCRIPTION": None,  # Will use default
                "ICON_TYPE": "custom",
                "AVATAR_URI": None,  # Will use empty string
                "CUSTOM_ICON_URL": "https://custom-icon.com"
            }
            return config_map.get(config_key)

        service_mocks['tenant_config_manager'].get_app_config.side_effect = side_effect

        # Mock MODEL_ENGINE_ENABLED
        with patch('backend.services.config_sync_service.MODEL_ENGINE_ENABLED', 'false'):
            # Execute
            result = build_app_config(language, tenant_id)

            # Assert
            assert result["name"] == "Custom App Name"
            # Default
            assert result["description"] == "Nexent is an open-source agent platform built on the MCP tool ecosystem, providing flexible multi-modal Q&A, retrieval, data analysis, and processing capabilities."
            assert result["icon"]["type"] == "custom"
            assert result["icon"]["avatarUri"] == ""  # Default empty
            assert result["icon"]["customUrl"] == "https://custom-icon.com"
            assert result["modelEngineEnabled"] == False

    def test_build_app_config_exception_handling(self, service_mocks):
        """Test build_app_config when get_app_config raises exception"""
        # Setup
        language = "en"
        tenant_id = "test_tenant_id"

        # Mock get_app_config to raise exception
        service_mocks['tenant_config_manager'].get_app_config.side_effect = Exception(
            "Database timeout")

        # Execute and assert exception is raised (since this function doesn't handle exceptions internally)
        with pytest.raises(Exception) as exc_info:
            build_app_config(language, tenant_id)

        assert "Database timeout" in str(exc_info.value)


class TestBuildModelConfig:
    """Test cases for build_model_config function"""

    def test_build_model_config_empty_config(self, service_mocks):
        """Test build_model_config with empty/None config"""
        # Test with None
        result = build_model_config(None)
        assert result == {
            "name": "",
            "displayName": "",
            "apiConfig": {
                "apiKey": "",
                "modelUrl": ""
            }
        }

        # Test with empty dict
        result = build_model_config({})
        assert result == {
            "name": "",
            "displayName": "",
            "apiConfig": {
                "apiKey": "",
                "modelUrl": ""
            }
        }

    def test_build_model_config_non_embedding_model(self, service_mocks):
        """Test build_model_config with non-embedding model config"""
        # Setup
        model_config = {
            "display_name": "GPT-4",
            "api_key": "test-api-key",
            "base_url": "https://api.openai.com",
            "model_type": "llm",
            "max_tokens": 4096
        }

        # Mock get_model_name_from_config
        service_mocks['get_model_name'].return_value = "gpt-4"

        # Execute
        result = build_model_config(model_config)

        # Assert
        assert result["name"] == "gpt-4"
        assert result["displayName"] == "GPT-4"
        assert result["apiConfig"]["apiKey"] == "test-api-key"
        assert result["apiConfig"]["modelUrl"] == "https://api.openai.com"
        # Should not have dimension field for non-embedding models
        assert "dimension" not in result

    def test_build_model_config_embedding_model(self, service_mocks):
        """Test build_model_config with embedding model config"""
        # Setup
        model_config = {
            "display_name": "Ada Embeddings",
            "api_key": "test-api-key",
            "base_url": "https://api.openai.com",
            "model_type": "embedding",
            "max_tokens": 1536
        }

        # Mock get_model_name_from_config
        service_mocks['get_model_name'].return_value = "text-embedding-ada-002"

        # Execute
        result = build_model_config(model_config)

        # Assert
        assert result["name"] == "text-embedding-ada-002"
        assert result["displayName"] == "Ada Embeddings"
        assert result["apiConfig"]["apiKey"] == "test-api-key"
        assert result["apiConfig"]["modelUrl"] == "https://api.openai.com"
        # Should have dimension field for embedding models
        assert result["dimension"] == 1536

    def test_build_model_config_multi_embedding_model(self, service_mocks):
        """Test build_model_config with multi_embedding model config"""
        # Setup
        model_config = {
            "display_name": "Multi Ada Embeddings",
            "api_key": "test-api-key",
            "base_url": "https://api.openai.com",
            "model_type": "multi_embedding",
            "max_tokens": 768
        }

        # Mock get_model_name_from_config
        service_mocks['get_model_name'].return_value = "text-embedding-3-small"

        # Execute
        result = build_model_config(model_config)

        # Assert
        assert result["name"] == "text-embedding-3-small"
        assert result["displayName"] == "Multi Ada Embeddings"
        assert result["apiConfig"]["apiKey"] == "test-api-key"
        assert result["apiConfig"]["modelUrl"] == "https://api.openai.com"
        # Should have dimension field for multi_embedding models
        assert result["dimension"] == 768

    def test_build_model_config_partial_fields(self, service_mocks):
        """Test build_model_config with partial fields missing"""
        # Setup
        model_config = {
            "display_name": "Test Model",
            # api_key and base_url are missing
            "model_type": "llm"
        }

        # Mock get_model_name_from_config
        service_mocks['get_model_name'].return_value = "test-model"

        # Execute
        result = build_model_config(model_config)

        # Assert
        assert result["name"] == "test-model"
        assert result["displayName"] == "Test Model"
        assert result["apiConfig"]["apiKey"] == ""  # Default empty
        assert result["apiConfig"]["modelUrl"] == ""  # Default empty
        assert "dimension" not in result  # No dimension for llm

    def test_build_model_config_embedding_without_max_tokens(self, service_mocks):
        """Test build_model_config with embedding model but no max_tokens"""
        # Setup
        model_config = {
            "display_name": "Test Embedding",
            "api_key": "test-key",
            "base_url": "https://test.com",
            "model_type": "embedding"
            # max_tokens is missing
        }

        # Mock get_model_name_from_config
        service_mocks['get_model_name'].return_value = "test-embedding"

        # Execute
        result = build_model_config(model_config)

        # Assert
        assert result["name"] == "test-embedding"
        assert result["displayName"] == "Test Embedding"
        assert result["apiConfig"]["apiKey"] == "test-key"
        assert result["apiConfig"]["modelUrl"] == "https://test.com"
        # Should have dimension field with default value 0
        assert result["dimension"] == 0

    def test_build_model_config_model_type_partial_match(self, service_mocks):
        """Test build_model_config with model_type that partially contains 'embedding'"""
        # Setup
        model_config = {
            "display_name": "Test Model",
            "api_key": "test-key",
            "model_type": "some_embedding_type",  # Contains 'embedding'
            "max_tokens": 512
        }

        # Mock get_model_name_from_config
        service_mocks['get_model_name'].return_value = "test-model"

        # Execute
        result = build_model_config(model_config)

        # Assert
        assert result["name"] == "test-model"
        assert result["displayName"] == "Test Model"
        assert result["apiConfig"]["apiKey"] == "test-key"
        # Should have dimension since model_type contains 'embedding'
        assert result["dimension"] == 512
