import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import Request
from fastapi.responses import JSONResponse
import sys
import logging
import os

# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)

# Patch boto3 and other dependencies before importing anything from backend
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Mock MinioClient before importing backend modules
with patch('backend.database.client.MinioClient') as minio_mock:
    minio_mock.return_value = MagicMock()
    
    # Now we can safely import the function to test
    from backend.apps.config_sync_app import load_config, save_config, handle_model_config


class TestConfigApp(unittest.TestCase):

    def setUp(self):
        # Create fresh mocks for each test
        self.mock_get_user_info = patch('backend.apps.config_sync_app.get_current_user_info').start()
        self.mock_tenant_config_manager = patch('backend.apps.config_sync_app.tenant_config_manager').start()
        self.mock_config_manager = patch('backend.apps.config_sync_app.config_manager').start()
        self.mock_get_model_name = patch('backend.apps.config_sync_app.get_model_name_from_config').start()
        self.mock_get_current_user_id = patch('backend.apps.config_sync_app.get_current_user_id').start()
        self.mock_get_env_key = patch('backend.apps.config_sync_app.get_env_key').start()
        self.mock_get_model_id_by_display_name = patch('backend.apps.config_sync_app.get_model_id_by_display_name').start()
        self.mock_handle_model_config = patch('backend.apps.config_sync_app.handle_model_config').start()
        self.mock_safe_value = patch('backend.apps.config_sync_app.safe_value').start()
        self.mock_safe_list = patch('backend.apps.config_sync_app.safe_list').start()
        self.mock_logger = patch('backend.apps.config_sync_app.logger').start()
        
    def tearDown(self):
        # Stop all patches after each test
        patch.stopall()

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_load_config_success(self, mock_json_response):
        # Setup
        mock_request = MagicMock()
        mock_auth_header = "Bearer test-token"
        
        # Mock user info
        self.mock_get_user_info.return_value = ("test_user", "test_tenant", "en")
        
        # Mock model configurations
        llm_config = {
            "display_name": "Test LLM",
            "api_key": "test-api-key",
            "base_url": "https://test-url.com"
        }
        self.mock_tenant_config_manager.get_model_config.side_effect = [
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
        self.mock_tenant_config_manager.get_app_config.side_effect = [
            "Custom App Name",  # APP_NAME
            "Custom description",  # APP_DESCRIPTION
            "preset",  # ICON_TYPE
            "avatar-uri",  # AVATAR_URI
            "https://custom-icon.com"  # CUSTOM_ICON_URL
        ]
        
        # Mock config dimension values
        self.mock_config_manager.get_config.side_effect = ["1024", "768"]
        
        # Mock model name conversion
        self.mock_get_model_name.return_value = "gpt-4"
        
        # Mock JSONResponse
        mock_response = MagicMock()
        mock_json_response.return_value = mock_response
        
        # Execute
        result = await load_config(mock_auth_header, mock_request)
        
        # Assert
        self.assertEqual(result, mock_response)
        self.mock_get_user_info.assert_called_once_with(mock_auth_header, mock_request)
        self.assertEqual(self.mock_tenant_config_manager.get_model_config.call_count, 8)
        self.assertEqual(self.mock_tenant_config_manager.get_app_config.call_count, 5)
        mock_json_response.assert_called_once()
        
        # Verify the content of the response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)
        self.assertTrue("config" in call_args["content"])
        config = call_args["content"]["config"]
        self.assertEqual(config["app"]["name"], "Custom App Name")
        self.assertEqual(config["models"]["llm"]["displayName"], "Test LLM")

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_load_config_chinese_language(self, mock_json_response):
        # Setup
        mock_request = MagicMock()
        mock_auth_header = "Bearer test-token"
        
        # Mock user info with Chinese language
        self.mock_get_user_info.return_value = ("test_user", "test_tenant", "zh")
        
        # Mock empty model configurations
        self.mock_tenant_config_manager.get_model_config.return_value = {}
        
        # Mock empty app configurations (to use defaults)
        self.mock_tenant_config_manager.get_app_config.return_value = None
        
        # Execute
        result = await load_config(mock_auth_header, mock_request)
        
        # Assert
        mock_json_response.assert_called_once()
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)
        config = call_args["content"]["config"]
        
        # Check Chinese default values
        self.assertEqual(config["app"]["name"], "Nexent 智能体")
        self.assertTrue("Nexent 是一个开源智能体SDK和平台" in config["app"]["description"])

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_load_config_with_error(self, mock_json_response):
        # Setup
        mock_request = MagicMock()
        mock_auth_header = "Bearer test-token"
        
        # Mock user info to raise an exception
        self.mock_get_user_info.side_effect = Exception("Auth error")
        
        # Mock response
        mock_response = MagicMock()
        mock_json_response.return_value = mock_response
        
        # Execute
        result = await load_config(mock_auth_header, mock_request)
        
        # Assert
        self.assertEqual(result, mock_response)
        mock_json_response.assert_called_once()
        
        # Verify error response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 400)
        self.assertEqual(call_args["content"]["status"], "error")
        self.assertTrue("Failed to load configuration" in call_args["content"]["message"])

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_load_config_with_dimension_conversion(self, mock_json_response):
        # Setup
        mock_request = MagicMock()
        mock_auth_header = "Bearer test-token"
        
        # Mock user info
        self.mock_get_user_info.return_value = ("test_user", "test_tenant", "en")
        
        # Mock model configurations
        self.mock_tenant_config_manager.get_model_config.return_value = {}
        
        # Mock config dimension values with invalid values to test conversion
        self.mock_config_manager.get_config.side_effect = ["invalid", "1536"]
        
        # Execute
        result = await load_config(mock_auth_header, mock_request)
        
        # Assert
        mock_json_response.assert_called_once()
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)
        config = call_args["content"]["config"]
        
        # Check dimension conversion
        self.assertIsNone(config["models"]["embedding"]["dimension"])
        self.assertEqual(config["models"]["multiEmbedding"]["dimension"], 1536)
        
    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_success(self, mock_json_response):
        # Setup
        mock_auth_header = "Bearer test-token"
        
        # Mock user and tenant ID
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig
        global_config = MagicMock()
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
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        self.mock_tenant_config_manager.load_config.return_value = {
            "APP_NAME": "Old App Name"
        }
        
        # Mock get_env_key
        self.mock_get_env_key.side_effect = lambda key: key.upper()
        
        # Mock safe_value
        self.mock_safe_value.side_effect = lambda value: str(value) if value is not None else ""
        
        # Mock get_model_id_by_display_name
        self.mock_get_model_id_by_display_name.side_effect = ["llm-model-id", "embedding-model-id"]
        
        # Mock JSONResponse
        mock_response = MagicMock()
        mock_json_response.return_value = mock_response
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        self.assertEqual(result, mock_response)
        self.mock_get_current_user_id.assert_called_once_with(mock_auth_header)
        
        # Verify tenant_config_manager calls
        self.mock_tenant_config_manager.load_config.assert_called_once_with("test_tenant_id")
        
        # Verify config_manager calls
        self.assertTrue(self.mock_config_manager.set_config.called)
        
        # Verify handle_model_config calls
        self.mock_handle_model_config.assert_called()
        
        # Verify response
        mock_json_response.assert_called_once()
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)
        self.assertEqual(call_args["content"]["status"], "saved")
        self.assertEqual(call_args["content"]["message"], "Configuration saved successfully")

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_with_error(self, mock_json_response):
        # Setup
        mock_auth_header = "Bearer test-token"
        global_config = MagicMock()
        
        # Mock an exception when getting user ID
        self.mock_get_current_user_id.side_effect = Exception("Authentication failed")
        
        # Mock JSONResponse
        mock_response = MagicMock()
        mock_json_response.return_value = mock_response
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        self.assertEqual(result, mock_response)
        
        # Verify error response
        mock_json_response.assert_called_once()
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 400)
        self.assertEqual(call_args["content"]["status"], "unsaved")
        self.assertTrue("Failed to save configuration" in call_args["content"]["message"])

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_empty_model_config(self, mock_json_response):
        # Setup
        mock_auth_header = "Bearer test-token"
        
        # Mock user and tenant ID
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig with empty model config
        global_config = MagicMock()
        config_dict = {
            "app": {
                "name": "Test App"
            },
            "models": {
                "llm": None,
                "embedding": {}
            }
        }
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        self.mock_tenant_config_manager.load_config.return_value = {}
        
        # Mock get_env_key
        self.mock_get_env_key.side_effect = lambda key: key.upper()
        
        # Mock safe_value
        self.mock_safe_value.side_effect = lambda value: str(value) if value is not None else ""
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        mock_json_response.assert_called_once()
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)
        
        # Verify that no model config handling was done for None model
        for call in self.mock_get_model_id_by_display_name.call_args_list:
            args, _ = call
            self.assertNotEqual(args[0], None)

    # Additional test cases to improve coverage

    def test_handle_model_config_delete(self):
        """Test handle_model_config when model_id is None and config exists"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = None
        tenant_config_dict = {"LLM_ID": "123"}
        
        # Execute
        handle_model_config(tenant_id, user_id, config_key, model_id, tenant_config_dict)
        
        # Assert
        self.mock_tenant_config_manager.delete_single_config.assert_called_once_with(tenant_id, config_key)
        self.mock_tenant_config_manager.set_single_config.assert_not_called()

    def test_handle_model_config_update_same_value(self):
        """Test handle_model_config when model_id is same as existing"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = 123
        tenant_config_dict = {"LLM_ID": "123"}
        
        # Execute
        handle_model_config(tenant_id, user_id, config_key, model_id, tenant_config_dict)
        
        # Assert
        self.mock_tenant_config_manager.update_single_config.assert_called_once_with(tenant_id, config_key)
        self.mock_tenant_config_manager.delete_single_config.assert_not_called()
        self.mock_tenant_config_manager.set_single_config.assert_not_called()

    def test_handle_model_config_update_different_value(self):
        """Test handle_model_config when model_id is different from existing"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = 456
        tenant_config_dict = {"LLM_ID": "123"}
        
        # Execute
        handle_model_config(tenant_id, user_id, config_key, model_id, tenant_config_dict)
        
        # Assert
        self.mock_tenant_config_manager.delete_single_config.assert_called_once_with(tenant_id, config_key)
        self.mock_tenant_config_manager.set_single_config.assert_called_once_with(
            user_id, tenant_id, config_key, model_id
        )

    def test_handle_model_config_non_int_value(self):
        """Test handle_model_config when existing value is not an int"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = 456
        tenant_config_dict = {"LLM_ID": "not-an-int"}
        
        # Execute
        handle_model_config(tenant_id, user_id, config_key, model_id, tenant_config_dict)
        
        # Assert
        self.mock_tenant_config_manager.delete_single_config.assert_called_once_with(tenant_id, config_key)
        self.mock_tenant_config_manager.set_single_config.assert_called_once_with(
            user_id, tenant_id, config_key, model_id
        )

    def test_handle_model_config_key_not_exists(self):
        """Test handle_model_config when config key doesn't exist"""
        # Setup
        tenant_id = "test_tenant_id"
        user_id = "test_user_id"
        config_key = "LLM_ID"
        model_id = 456
        tenant_config_dict = {}
        
        # Execute
        handle_model_config(tenant_id, user_id, config_key, model_id, tenant_config_dict)
        
        # Assert
        self.mock_tenant_config_manager.delete_single_config.assert_not_called()
        self.mock_tenant_config_manager.set_single_config.assert_called_once_with(
            user_id, tenant_id, config_key, model_id
        )

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_app_values(self, mock_json_response):
        """Test save_config handling different app configuration values"""
        # Setup
        mock_auth_header = "Bearer test-token"
        
        # Mock user and tenant ID
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig with various app config scenarios
        global_config = MagicMock()
        config_dict = {
            "app": {
                "name": "Test App",
                "description": "",  # Empty value to test deletion
                "icon": {
                    "type": "custom"
                }
            },
            "models": {}
        }
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config with existing values
        self.mock_tenant_config_manager.load_config.return_value = {
            "APP_NAME": "Old App Name",
            "APP_DESCRIPTION": "Old description"
        }
        
        # Mock get_env_key
        self.mock_get_env_key.side_effect = lambda key: key.upper()
        
        # Mock safe_value
        self.mock_safe_value.side_effect = lambda value: str(value) if value is not None else ""
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        # Verify APP_NAME was updated (different value)
        self.mock_tenant_config_manager.delete_single_config.assert_any_call("test_tenant_id", "APP_NAME")
        self.mock_tenant_config_manager.set_single_config.assert_any_call(
            "test_user_id", "test_tenant_id", "APP_NAME", "Test App"
        )
        
        # Verify APP_DESCRIPTION was deleted (empty value)
        self.mock_tenant_config_manager.delete_single_config.assert_any_call("test_tenant_id", "APP_DESCRIPTION")
        
        # Verify successful response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_api_config(self, mock_json_response):
        """Test save_config handling API configuration"""
        # Setup
        mock_auth_header = "Bearer test-token"
        
        # Mock user and tenant ID
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig with API config
        global_config = MagicMock()
        config_dict = {
            "app": {},
            "models": {
                "llm": {
                    "modelName": "gpt-4",
                    "displayName": "GPT-4",
                    "apiConfig": {
                        "apiKey": "test-api-key",
                        "baseUrl": "https://api.openai.com"
                    }
                }
            }
        }
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        self.mock_tenant_config_manager.load_config.return_value = {}
        
        # Mock get_env_key - Convert to uppercase and preserve underscores
        self.mock_get_env_key.side_effect = lambda key: key.upper()
        
        # Mock safe_value
        self.mock_safe_value.side_effect = lambda value: str(value) if value is not None else ""
        
        # Mock get_model_id_by_display_name
        self.mock_get_model_id_by_display_name.return_value = 123
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        # Verify config values were set correctly
        self.mock_config_manager.set_config.assert_any_call("LLM_API_KEY", "test-api-key")
        self.mock_config_manager.set_config.assert_any_call("LLM_BASEURL", "https://api.openai.com")
        
        # Verify successful response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_with_empty_api_config(self, mock_json_response):
        """Test save_config with empty API config"""
        # Setup
        mock_auth_header = "Bearer test-token"
        
        # Mock user and tenant ID
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig with empty API config
        global_config = MagicMock()
        config_dict = {
            "app": {},
            "models": {
                "llm": {
                    "modelName": "gpt-4",
                    "displayName": "GPT-4",
                    "apiConfig": None
                }
            }
        }
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        self.mock_tenant_config_manager.load_config.return_value = {}
        
        # Mock get_env_key
        self.mock_get_env_key.side_effect = lambda key: key.upper()
        
        # Mock safe_value
        self.mock_safe_value.side_effect = lambda value: str(value) if value is not None else ""
        
        # Mock get_model_id_by_display_name
        self.mock_get_model_id_by_display_name.return_value = 123
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        # Verify empty values were set
        self.mock_config_manager.set_config.assert_any_call("LLM_API_KEY", "")
        self.mock_config_manager.set_config.assert_any_call("LLM_MODEL_URL", "")
        
        # Verify successful response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_load_config_all_model_types(self, mock_json_response):
        """Test load_config with all model types populated"""
        # Setup
        mock_request = MagicMock()
        mock_auth_header = "Bearer test-token"
        
        # Mock user info
        self.mock_get_user_info.return_value = ("test_user", "test_tenant", "en")
        
        # Create model configs for all types
        def create_model_config(name):
            return {
                "display_name": f"Test {name}",
                "api_key": f"api-key-{name}",
                "base_url": f"https://{name.lower()}-api.com"
            }
        
        # Mock model configurations for all types
        self.mock_tenant_config_manager.get_model_config.side_effect = [
            create_model_config("LLM"),               # LLM_ID
            create_model_config("LLM Secondary"),     # LLM_SECONDARY_ID
            create_model_config("Embedding"),         # EMBEDDING_ID
            create_model_config("Multi-Embedding"),   # MULTI_EMBEDDING_ID
            create_model_config("Rerank"),            # RERANK_ID
            create_model_config("VLM"),               # VLM_ID
            create_model_config("STT"),               # STT_ID
            create_model_config("TTS")                # TTS_ID
        ]
        
        # Mock app configurations
        self.mock_tenant_config_manager.get_app_config.return_value = "Custom Value"
        
        # Mock model name conversion
        self.mock_get_model_name.side_effect = [
            "gpt-4", "gpt-3.5", "ada-002", "multi-ada", "rerank-v1", "clip-vision", "whisper", "elevenlabs"
        ]
        
        # Mock dimension values as valid integers
        self.mock_config_manager.get_config.side_effect = ["1536", "3072"]
        
        # Execute
        result = await load_config(mock_auth_header, mock_request)
        
        # Assert
        mock_json_response.assert_called_once()
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)
        config = call_args["content"]["config"]
        
        # Verify all model types are in the config
        self.assertEqual(config["models"]["llm"]["name"], "gpt-4")
        self.assertEqual(config["models"]["llmSecondary"]["name"], "gpt-3.5")
        self.assertEqual(config["models"]["embedding"]["name"], "ada-002")
        self.assertEqual(config["models"]["multiEmbedding"]["name"], "multi-ada")
        self.assertEqual(config["models"]["rerank"]["name"], "rerank-v1")
        self.assertEqual(config["models"]["vlm"]["name"], "clip-vision")
        self.assertEqual(config["models"]["stt"]["name"], "whisper")
        self.assertEqual(config["models"]["tts"]["name"], "elevenlabs")
        
        # Verify dimensions are set correctly
        self.assertEqual(config["models"]["embedding"]["dimension"], 1536)
        self.assertEqual(config["models"]["multiEmbedding"]["dimension"], 3072)

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_model_without_name(self, mock_json_response):
        """Test save_config with model config that has no modelName"""
        # Setup
        mock_auth_header = "Bearer test-token"
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig with model without modelName
        global_config = MagicMock()
        config_dict = {
            "app": {},
            "models": {
                "llm": {
                    "displayName": "Test Model",
                    "apiConfig": {
                        "apiKey": "test-key"
                    }
                }
            }
        }
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        self.mock_tenant_config_manager.load_config.return_value = {}
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        # Verify that model config was not processed (due to missing modelName)
        self.mock_handle_model_config.assert_not_called()
        
        # Verify successful response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_nested_app_config(self, mock_json_response):
        """Test save_config with nested app configuration"""
        # Setup
        mock_auth_header = "Bearer test-token"
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig with nested app config
        global_config = MagicMock()
        config_dict = {
            "app": {
                "icon": {
                    "type": "custom",
                    "avatarUri": "test-uri",
                    "customUrl": "https://test.com/icon"
                }
            },
            "models": {}
        }
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        self.mock_tenant_config_manager.load_config.return_value = {}
        
        # Mock get_env_key to handle nested keys
        self.mock_get_env_key.side_effect = lambda key: key.upper()
        
        # Mock safe_value
        self.mock_safe_value.side_effect = lambda value: str(value)
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        # Verify that nested config values were processed
        self.mock_config_manager.set_config.assert_any_call("ICON_TYPE", "custom")
        self.mock_config_manager.set_config.assert_any_call("AVATAR_URI", "test-uri")
        self.mock_config_manager.set_config.assert_any_call("CUSTOM_URL", "https://test.com/icon")
        
        # Verify successful response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_model_dimension_handling(self, mock_json_response):
        """Test save_config handling of model dimensions"""
        # Setup
        mock_auth_header = "Bearer test-token"
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig with embedding models having dimensions
        global_config = MagicMock()
        config_dict = {
            "app": {},
            "models": {
                "embedding": {
                    "modelName": "text-embedding-ada-002",
                    "displayName": "Ada",
                    "dimension": 1536
                },
                "multiEmbedding": {
                    "modelName": "multi-embedding",
                    "displayName": "Multi",
                    "dimension": 3072
                },
                "llm": {  # This dimension should be ignored
                    "modelName": "gpt-4",
                    "displayName": "GPT-4",
                    "dimension": 1024
                }
            }
        }
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        self.mock_tenant_config_manager.load_config.return_value = {}
        
        # Mock get_env_key
        self.mock_get_env_key.side_effect = lambda key: key.upper()
        
        # Mock safe_value
        self.mock_safe_value.side_effect = lambda value: str(value)
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        # Verify dimension settings for embedding models
        self.mock_config_manager.set_config.assert_any_call("EMBEDDING_DIMENSION", "1536")
        self.mock_config_manager.set_config.assert_any_call("MULTI_EMBEDDING_DIMENSION", "3072")
        
        # Verify LLM dimension was not set
        for call in self.mock_config_manager.set_config.call_args_list:
            args = call[0]
            self.assertNotIn("LLM_DIMENSION", args)
        
        # Verify successful response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_empty_models_dict(self, mock_json_response):
        """Test save_config with empty models dictionary"""
        # Setup
        mock_auth_header = "Bearer test-token"
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig with empty models dict
        global_config = MagicMock()
        config_dict = {
            "app": {
                "name": "Test App"
            },
            "models": {}
        }
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        self.mock_tenant_config_manager.load_config.return_value = {}
        
        # Mock get_env_key
        self.mock_get_env_key.side_effect = lambda key: key.upper()
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        # Verify that no model config handling was done
        self.mock_get_model_id_by_display_name.assert_not_called()
        self.mock_handle_model_config.assert_not_called()
        
        # Verify app config was still processed
        self.mock_config_manager.set_config.assert_any_call("NAME", "Test App")
        
        # Verify successful response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_invalid_model_config(self, mock_json_response):
        """Test save_config with invalid model configuration"""
        # Setup
        mock_auth_header = "Bearer test-token"
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig with invalid model config
        global_config = MagicMock()
        config_dict = {
            "app": {},
            "models": {
                "llm": None,  # Invalid model config
                "embedding": "",  # Invalid model config
                "multiEmbedding": {},  # Empty model config
                "rerank": {
                    "modelName": "test-model",  # Valid model config
                    "displayName": "Test Model"
                }
            }
        }
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        self.mock_tenant_config_manager.load_config.return_value = {}
        
        # Mock get_env_key
        self.mock_get_env_key.side_effect = lambda key: key.upper()
        
        # Mock get_model_id_by_display_name
        self.mock_get_model_id_by_display_name.return_value = "123"
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        # Verify that only valid model config was processed
        self.mock_get_model_id_by_display_name.assert_called_once_with("Test Model", "test_tenant_id")
        
        # Verify successful response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_model_with_empty_api_config(self, mock_json_response):
        """Test save_config with model having empty API config"""
        # Setup
        mock_auth_header = "Bearer test-token"
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig with empty API config
        global_config = MagicMock()
        config_dict = {
            "app": {},
            "models": {
                "llm": {
                    "modelName": "gpt-4",
                    "displayName": "GPT-4",
                    "apiConfig": {}  # Empty API config
                }
            }
        }
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        self.mock_tenant_config_manager.load_config.return_value = {}
        
        # Mock get_env_key
        self.mock_get_env_key.side_effect = lambda key: key.upper()
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        # Verify that default empty values were set for API config
        self.mock_config_manager.set_config.assert_any_call("LLM_API_KEY", "")
        self.mock_config_manager.set_config.assert_any_call("LLM_MODEL_URL", "")
        
        # Verify successful response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_no_app_config(self, mock_json_response):
        """Test save_config without app configuration"""
        # Setup
        mock_auth_header = "Bearer test-token"
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig without app config
        global_config = MagicMock()
        config_dict = {
            "models": {
                "llm": {
                    "modelName": "gpt-4",
                    "displayName": "GPT-4"
                }
            }
        }
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        self.mock_tenant_config_manager.load_config.return_value = {}
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        # Verify that app config processing was skipped
        self.mock_tenant_config_manager.update_single_config.assert_not_called()
        self.mock_tenant_config_manager.delete_single_config.assert_not_called()
        
        # Verify successful response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_with_print_statements(self, mock_json_response):
        """Test save_config with print statements for debugging"""
        # Setup
        mock_auth_header = "Bearer test-token"
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig
        global_config = MagicMock()
        config_dict = {
            "app": {"name": "Test App"},
            "models": {"llm": {"modelName": "gpt-4"}}
        }
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        tenant_config = {"APP_NAME": "Old App"}
        self.mock_tenant_config_manager.load_config.return_value = tenant_config
        
        # Execute
        with patch('builtins.print') as mock_print:
            result = await save_config(global_config, mock_auth_header)
        
        # Assert
        # Verify print statements were called
        mock_print.assert_any_call(f"config_dict: {config_dict}")
        mock_print.assert_any_call(f"Tenant test_tenant_id config: {tenant_config}")
        
        # Verify successful response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_with_logger(self, mock_json_response):
        """Test save_config with logger calls"""
        # Setup
        mock_auth_header = "Bearer test-token"
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig
        global_config = MagicMock()
        config_dict = {"app": {"name": "Test App"}}
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        self.mock_tenant_config_manager.load_config.return_value = {}
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        # Verify logger calls
        self.mock_logger.info.assert_called_once_with("Configuration saved successfully")
        
        # Verify successful response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_with_error_logging(self, mock_json_response):
        """Test save_config with error logging"""
        # Setup
        mock_auth_header = "Bearer test-token"
        
        # Mock an exception
        error_message = "Test error"
        self.mock_get_current_user_id.side_effect = Exception(error_message)
        
        # Execute
        result = await save_config(MagicMock(), mock_auth_header)
        
        # Assert
        # Verify error logging
        self.mock_logger.error.assert_called_once_with(f"Failed to save configuration: {error_message}")
        
        # Verify error response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 400)
        self.assertEqual(call_args["content"]["status"], "unsaved")
        self.assertEqual(call_args["content"]["message"], f"Failed to save configuration: {error_message}")

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_model_without_display_name(self, mock_json_response):
        """Test save_config with model config that has modelName but no displayName"""
        # Setup
        mock_auth_header = "Bearer test-token"
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig
        global_config = MagicMock()
        config_dict = {
            "models": {
                "llm": {
                    "modelName": "gpt-4"  # No displayName
                }
            }
        }
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        self.mock_tenant_config_manager.load_config.return_value = {}
        
        # Mock get_model_id_by_display_name to return None for missing displayName
        self.mock_get_model_id_by_display_name.return_value = None
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        # Verify model_id was attempted to be retrieved with None
        self.mock_get_model_id_by_display_name.assert_called_once_with(None, "test_tenant_id")
        
        # Verify handle_model_config was called with None model_id
        self.mock_handle_model_config.assert_called_once()
        
        # Verify successful response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)

    @patch('backend.apps.config_sync_app.JSONResponse')
    async def test_save_config_exclude_none_false(self, mock_json_response):
        """Test save_config with exclude_none=False in model_dump"""
        # Setup
        mock_auth_header = "Bearer test-token"
        self.mock_get_current_user_id.return_value = ("test_user_id", "test_tenant_id")
        
        # Mock GlobalConfig with explicit None values
        global_config = MagicMock()
        config_dict = {
            "app": {
                "name": "Test App",
                "description": None
            },
            "models": {
                "llm": {
                    "modelName": "gpt-4",
                    "apiConfig": None
                }
            }
        }
        global_config.model_dump.return_value = config_dict
        
        # Mock tenant config
        self.mock_tenant_config_manager.load_config.return_value = {}
        
        # Mock safe_value to handle None
        self.mock_safe_value.side_effect = lambda value: str(value) if value is not None else ""
        
        # Execute
        result = await save_config(global_config, mock_auth_header)
        
        # Assert
        # Verify None values were processed
        self.mock_config_manager.set_config.assert_any_call("DESCRIPTION", "")
        
        # Verify successful response
        call_args = mock_json_response.call_args[1]
        self.assertEqual(call_args["status_code"], 200)


if __name__ == '__main__':
    unittest.main()
