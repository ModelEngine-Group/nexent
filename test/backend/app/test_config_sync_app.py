import pytest
from unittest.mock import patch, MagicMock
import sys
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


# Fixtures to replace setUp and tearDown
@pytest.fixture
def config_mocks():
    # Create fresh mocks for each test
    with patch('backend.apps.config_sync_app.get_current_user_info') as mock_get_user_info, \
            patch('backend.apps.config_sync_app.tenant_config_manager') as mock_tenant_config_manager, \
            patch('backend.apps.config_sync_app.get_model_name_from_config') as mock_get_model_name, \
            patch('backend.apps.config_sync_app.get_current_user_id') as mock_get_current_user_id, \
            patch('backend.apps.config_sync_app.get_env_key') as mock_get_env_key, \
            patch('backend.apps.config_sync_app.get_model_id_by_display_name') as mock_get_model_id_by_display_name, \
            patch('backend.apps.config_sync_app.handle_model_config') as mock_handle_model_config, \
            patch('backend.apps.config_sync_app.safe_value') as mock_safe_value, \
            patch('backend.apps.config_sync_app.logger') as mock_logger:

        yield {
            'get_user_info': mock_get_user_info,
            'tenant_config_manager': mock_tenant_config_manager,
            'get_model_name': mock_get_model_name,
            'get_current_user_id': mock_get_current_user_id,
            'get_env_key': mock_get_env_key,
            'get_model_id_by_display_name': mock_get_model_id_by_display_name,
            'handle_model_config': mock_handle_model_config,
            'safe_value': mock_safe_value,
            'logger': mock_logger
        }


@pytest.mark.asyncio
async def test_load_config_success(config_mocks):
    # Setup
    mock_request = MagicMock()
    mock_auth_header = "Bearer test-token"

    # Mock user info
    config_mocks['get_user_info'].return_value = (
        "test_user", "test_tenant", "en")

    # Mock model configurations
    llm_config = {
        "display_name": "Test LLM",
        "api_key": "test-api-key",
        "base_url": "https://test-url.com"
    }
    config_mocks['tenant_config_manager'].get_model_config.side_effect = [
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
    config_mocks['tenant_config_manager'].get_app_config.side_effect = [
        "Custom App Name",  # APP_NAME
        "Custom description",  # APP_DESCRIPTION
        "preset",  # ICON_TYPE
        "avatar-uri",  # AVATAR_URI
        "https://custom-icon.com"  # CUSTOM_ICON_URL
    ]

    # Mock model name conversion
    config_mocks['get_model_name'].return_value = "gpt-4"

    # Mock JSONResponse
    with patch('backend.apps.config_sync_app.JSONResponse') as mock_json_response:
        mock_response = MagicMock()
        mock_json_response.return_value = mock_response

        # Execute
        result = await load_config(mock_auth_header, mock_request)

        # Assert
        assert result == mock_response
        config_mocks['get_user_info'].assert_called_once_with(
            mock_auth_header, mock_request)
        assert config_mocks['tenant_config_manager'].get_model_config.call_count == 8
        assert config_mocks['tenant_config_manager'].get_app_config.call_count == 5
        mock_json_response.assert_called_once()

        # Verify the content of the response
        call_args = mock_json_response.call_args[1]
        assert call_args["status_code"] == 200
        assert "config" in call_args["content"]
        config = call_args["content"]["config"]
        assert config["app"]["name"] == "Custom App Name"
        assert config["models"]["llm"]["displayName"] == "Test LLM"


@pytest.mark.asyncio
async def test_load_config_chinese_language(config_mocks):
    # Setup
    mock_request = MagicMock()
    mock_auth_header = "Bearer test-token"

    # Mock user info with Chinese language
    config_mocks['get_user_info'].return_value = (
        "test_user", "test_tenant", "zh")

    # Mock empty model configurations
    config_mocks['tenant_config_manager'].get_model_config.return_value = {}

    # Mock empty app configurations (to use defaults)
    config_mocks['tenant_config_manager'].get_app_config.return_value = None

    with patch('backend.apps.config_sync_app.JSONResponse') as mock_json_response:
        # Execute
        result = await load_config(mock_auth_header, mock_request)

        # Assert
        mock_json_response.assert_called_once()
        call_args = mock_json_response.call_args[1]
        assert call_args["status_code"] == 200
        config = call_args["content"]["config"]

        # Check Chinese default values
        assert config["app"]["name"] == "Nexent 智能体"
        assert "Nexent 是一个开源智能体SDK和平台" in config["app"]["description"]


@pytest.mark.asyncio
async def test_load_config_with_error(config_mocks):
    # Setup
    mock_request = MagicMock()
    mock_auth_header = "Bearer test-token"

    # Mock user info to raise an exception
    config_mocks['get_user_info'].side_effect = Exception("Auth error")

    with patch('backend.apps.config_sync_app.JSONResponse') as mock_json_response:
        # Mock response
        mock_response = MagicMock()
        mock_json_response.return_value = mock_response

        # Execute
        result = await load_config(mock_auth_header, mock_request)

        # Assert
        assert result == mock_response
        mock_json_response.assert_called_once()

        # Verify error response
        call_args = mock_json_response.call_args[1]
        assert call_args["status_code"] == 400
        assert call_args["content"]["status"] == "error"
        assert "Failed to load configuration" in call_args["content"]["message"]


@pytest.mark.asyncio
async def test_load_config_with_dimension_conversion(config_mocks):
    # Setup
    mock_request = MagicMock()
    mock_auth_header = "Bearer test-token"

    # Mock user info
    config_mocks['get_user_info'].return_value = (
        "test_user", "test_tenant", "en")

    # Mock model configurations - provide max_tokens property
    # Invalid conversion will default to 0
    embedding_config = {"max_tokens": 0}
    multi_embedding_config = {"max_tokens": 1536}  # Valid dimension

    config_mocks['tenant_config_manager'].get_model_config.side_effect = [
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
    config_mocks['tenant_config_manager'].get_app_config.return_value = None

    with patch('backend.apps.config_sync_app.JSONResponse') as mock_json_response:
        # Execute
        result = await load_config(mock_auth_header, mock_request)

        # Assert
        mock_json_response.assert_called_once()
        call_args = mock_json_response.call_args[1]
        assert call_args["status_code"] == 200
        config = call_args["content"]["config"]

        # Check dimension conversion
        assert config["models"]["embedding"]["dimension"] == 0
        assert config["models"]["multiEmbedding"]["dimension"] == 1536


@pytest.mark.asyncio
async def test_save_config_success(config_mocks):
    # Setup
    mock_auth_header = "Bearer test-token"

    # Mock user and tenant ID
    config_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

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
    config_mocks['tenant_config_manager'].load_config.return_value = {
        "APP_NAME": "Old App Name"
    }

    # Mock get_env_key
    config_mocks['get_env_key'].side_effect = lambda key: key.upper()

    # Mock safe_value
    config_mocks['safe_value'].side_effect = lambda value: str(
        value) if value is not None else ""

    # Mock get_model_id_by_display_name
    config_mocks['get_model_id_by_display_name'].side_effect = [
        "llm-model-id", "embedding-model-id"]

    with patch('backend.apps.config_sync_app.JSONResponse') as mock_json_response:
        # Mock JSONResponse
        mock_response = MagicMock()
        mock_json_response.return_value = mock_response

        # Execute
        result = await save_config(global_config, mock_auth_header)

        # Assert
        assert result == mock_response
        config_mocks['get_current_user_id'].assert_called_once_with(
            mock_auth_header)

        # Verify tenant_config_manager calls
        config_mocks['tenant_config_manager'].load_config.assert_called_once_with(
            "test_tenant_id")

        # Verify handle_model_config calls
        assert config_mocks['handle_model_config'].called

        # Verify response
        mock_json_response.assert_called_once()
        call_args = mock_json_response.call_args[1]
        assert call_args["status_code"] == 200
        assert call_args["content"]["status"] == "saved"
        assert call_args["content"]["message"] == "Configuration saved successfully"


@pytest.mark.asyncio
async def test_save_config_with_error(config_mocks):
    # Setup
    mock_auth_header = "Bearer test-token"
    global_config = MagicMock()

    # Mock an exception when getting user ID
    config_mocks['get_current_user_id'].side_effect = Exception(
        "Authentication failed")

    with patch('backend.apps.config_sync_app.JSONResponse') as mock_json_response:
        # Mock JSONResponse
        mock_response = MagicMock()
        mock_json_response.return_value = mock_response

        # Execute
        result = await save_config(global_config, mock_auth_header)

        # Assert
        assert result == mock_response

        # Verify error response
        mock_json_response.assert_called_once()
        call_args = mock_json_response.call_args[1]
        assert call_args["status_code"] == 400
        assert call_args["content"]["status"] == "unsaved"
        assert "Failed to save configuration" in call_args["content"]["message"]


@pytest.mark.asyncio
async def test_save_config_empty_model_config(config_mocks):
    # Setup
    mock_auth_header = "Bearer test-token"

    # Mock user and tenant ID
    config_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

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
    config_mocks['tenant_config_manager'].load_config.return_value = {}

    # Mock get_env_key
    config_mocks['get_env_key'].side_effect = lambda key: key.upper()

    # Mock safe_value
    config_mocks['safe_value'].side_effect = lambda value: str(
        value) if value is not None else ""

    with patch('backend.apps.config_sync_app.JSONResponse') as mock_json_response:
        # Execute
        result = await save_config(global_config, mock_auth_header)

        # Assert
        mock_json_response.assert_called_once()
        call_args = mock_json_response.call_args[1]
        assert call_args["status_code"] == 200

        # Verify that no model config handling was done for None model
        for call in config_mocks['get_model_id_by_display_name'].call_args_list:
            args, _ = call
            assert args[0] is not None


# Additional test cases to improve coverage

def test_handle_model_config_delete(config_mocks):
    """Test handle_model_config when model_id is None and config exists"""
    # Setup
    tenant_id = "test_tenant_id"
    user_id = "test_user_id"
    config_key = "LLM_ID"
    model_id = 0  # Changed from None to 0 to match implementation
    tenant_config_dict = {"LLM_ID": "123"}

    # Execute
    handle_model_config(tenant_id, user_id, config_key,
                        model_id, tenant_config_dict)

    # Assert
    config_mocks['tenant_config_manager'].delete_single_config.assert_called_once_with(
        tenant_id, config_key)
    config_mocks['tenant_config_manager'].set_single_config.assert_not_called()


def test_handle_model_config_update_same_value(config_mocks):
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
    config_mocks['tenant_config_manager'].update_single_config.assert_called_once_with(
        tenant_id, config_key)
    config_mocks['tenant_config_manager'].delete_single_config.assert_not_called()
    config_mocks['tenant_config_manager'].set_single_config.assert_not_called()


def test_handle_model_config_update_different_value(config_mocks):
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
    config_mocks['tenant_config_manager'].delete_single_config.assert_called_once_with(
        tenant_id, config_key)
    config_mocks['tenant_config_manager'].set_single_config.assert_called_once_with(
        user_id, tenant_id, config_key, model_id
    )


def test_handle_model_config_non_int_value(config_mocks):
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
    config_mocks['tenant_config_manager'].delete_single_config.assert_called_once_with(
        tenant_id, config_key)
    config_mocks['tenant_config_manager'].set_single_config.assert_called_once_with(
        user_id, tenant_id, config_key, model_id
    )


def test_handle_model_config_key_not_exists(config_mocks):
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
    config_mocks['tenant_config_manager'].delete_single_config.assert_not_called()
    config_mocks['tenant_config_manager'].set_single_config.assert_called_once_with(
        user_id, tenant_id, config_key, model_id
    )
