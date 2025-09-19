import sys
from unittest.mock import patch, MagicMock

import pytest

# Patch boto3 and other dependencies before importing anything from backend
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock


# Mock dependencies before importing
minio_client_mock = MagicMock()
with patch('backend.database.client.MinioClient', return_value=minio_client_mock):
    from backend.services.config_sync_service import (
        handle_model_config,
        save_config_impl,
        load_config_impl,
        build_models_config
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

    def test_handle_model_config_delete(self, service_mocks):
        """Test handle_model_config when model_id is 0 and config exists"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = 0  # 0 means delete
        tenant_config_dict = {"LLM_ID": "123"}

        # Execute
        handle_model_config(tenant_id, user_id, config_key,
                            model_id, tenant_config_dict)

        # Assert
        service_mocks['tenant_config_manager'].delete_single_config.assert_called_once_with(
            tenant_id, config_key)
        service_mocks['tenant_config_manager'].set_single_config.assert_not_called()

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
        service_mocks['tenant_config_manager'].get_app_config.side_effect = [
            "Custom App Name",  # APP_NAME
            "Custom description",  # APP_DESCRIPTION
            "preset",  # ICON_TYPE
            "avatar-uri",  # AVATAR_URI
            "https://custom-icon.com"  # CUSTOM_ICON_URL
        ]

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
        assert "Nexent 是一个开源智能体SDK和平台" in result["app"]["description"]

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
            {},          # LLM_SECONDARY_ID
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
            "",          # LLM_SECONDARY_ID
            "text-embedding-ada-002",  # EMBEDDING_ID
            "text-embedding-3-small",  # MULTI_EMBEDDING_ID
            "",          # RERANK_ID
            "",          # VLM_ID
            "",          # STT_ID
            ""           # TTS_ID
        ]

        # Execute
        result = await load_config_impl(language, tenant_id)

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
