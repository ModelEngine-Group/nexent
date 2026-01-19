import os
import sys
from unittest.mock import patch, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)

# Patch boto3 and other dependencies before importing anything from backend
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.minio_client', minio_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Now we can safely import the function to test
from backend.apps.config_sync_app import load_config, save_config, save_datamate_url


# Fixtures to replace setUp and tearDown
@pytest.fixture
def config_mocks():
    # Create fresh mocks for each test
    with patch('backend.apps.config_sync_app.get_current_user_info') as mock_get_user_info, \
            patch('backend.apps.config_sync_app.get_current_user_id') as mock_get_current_user_id, \
            patch('backend.apps.config_sync_app.save_config_impl') as mock_save_config_impl, \
            patch('backend.apps.config_sync_app.load_config_impl') as mock_load_config_impl, \
            patch('backend.apps.config_sync_app.logger') as mock_logger, \
            patch('backend.apps.config_sync_app.tenant_config_manager.set_single_config') as mock_set_single_config, \
            patch('backend.apps.config_sync_app.tenant_config_manager.delete_single_config') as mock_delete_single_config:

        yield {
            'get_user_info': mock_get_user_info,
            'get_current_user_id': mock_get_current_user_id,
            'save_config_impl': mock_save_config_impl,
            'load_config_impl': mock_load_config_impl,
            'logger': mock_logger,
            'set_single_config': mock_set_single_config,
            'delete_single_config': mock_delete_single_config
        }


@pytest.mark.asyncio
async def test_load_config_success(config_mocks):
    """Test successful configuration loading"""
    # Setup
    mock_request = MagicMock()
    mock_auth_header = "Bearer test-token"

    # Mock user info
    config_mocks['get_user_info'].return_value = (
        "test_user", "test_tenant", "en")

    # Mock service response - use JSON-serializable data instead of MagicMock
    mock_config = {"app": {"name": "Test App"},
                   "models": {"model1": {"enabled": True}}}
    config_mocks['load_config_impl'].return_value = mock_config

    # Execute
    result = await load_config(mock_auth_header, mock_request)

    # Assert
    assert isinstance(result, JSONResponse)
    assert result.status_code == 200

    # Parse the JSON response body to verify content
    import json
    response_body = json.loads(result.body.decode())
    assert response_body["config"] == mock_config

    config_mocks['get_user_info'].assert_called_once_with(
        mock_auth_header, mock_request)
    config_mocks['load_config_impl'].assert_called_once_with(
        "en", "test_tenant")


@pytest.mark.asyncio
async def test_load_config_chinese_language(config_mocks):
    """Test configuration loading with Chinese language"""
    # Setup
    mock_request = MagicMock()
    mock_auth_header = "Bearer test-token"

    # Mock user info with Chinese language
    config_mocks['get_user_info'].return_value = (
        "test_user", "test_tenant", "zh")

    # Mock service response - use JSON-serializable data
    mock_config = {"app": {"language": "zh"}, "settings": {"theme": "dark"}}
    config_mocks['load_config_impl'].return_value = mock_config

    # Execute
    result = await load_config(mock_auth_header, mock_request)

    # Assert
    assert isinstance(result, JSONResponse)
    assert result.status_code == 200

    # Parse the JSON response body to verify content
    import json
    response_body = json.loads(result.body.decode())
    assert response_body["config"] == mock_config

    config_mocks['get_user_info'].assert_called_once_with(
        mock_auth_header, mock_request)
    config_mocks['load_config_impl'].assert_called_once_with(
        "zh", "test_tenant")


@pytest.mark.asyncio
async def test_load_config_with_error(config_mocks):
    """Test configuration loading with error"""
    # Setup
    mock_request = MagicMock()
    mock_auth_header = "Bearer test-token"

    # Mock user info to raise an exception
    config_mocks['get_user_info'].side_effect = Exception("Auth error")

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await load_config(mock_auth_header, mock_request)

    assert exc_info.value.status_code == 400
    assert "Failed to load configuration" in str(exc_info.value.detail)
    config_mocks['logger'].error.assert_called_once()


@pytest.mark.asyncio
async def test_save_config_success(config_mocks):
    """Test successful configuration saving"""
    # Setup
    mock_auth_header = "Bearer test-token"
    global_config = MagicMock()

    # Mock user and tenant ID
    config_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

    # Mock service response (save_config_impl doesn't need to return anything specific)
    config_mocks['save_config_impl'].return_value = None

    # Execute
    result = await save_config(global_config, mock_auth_header)

    # Assert
    assert isinstance(result, JSONResponse)
    assert result.status_code == 200

    # Parse the JSON response body to verify content
    import json
    response_body = json.loads(result.body.decode())
    assert response_body["status"] == "saved"
    assert "Configuration saved successfully" in response_body["message"]

    config_mocks['get_current_user_id'].assert_called_once_with(
        mock_auth_header)
    config_mocks['save_config_impl'].assert_called_once_with(
        global_config, "test_tenant_id", "test_user_id")
    config_mocks['logger'].info.assert_called_once()


@pytest.mark.asyncio
async def test_save_config_with_error(config_mocks):
    """Test configuration saving with error"""
    # Setup
    mock_auth_header = "Bearer test-token"
    global_config = MagicMock()

    # Mock an exception when getting user ID
    config_mocks['get_current_user_id'].side_effect = Exception(
        "Authentication failed")

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await save_config(global_config, mock_auth_header)

    assert exc_info.value.status_code == 400
    assert "Failed to save configuration" in str(exc_info.value.detail)
    config_mocks['logger'].error.assert_called_once()


@pytest.mark.asyncio
async def test_save_datamate_url_success_with_value(config_mocks):
    """Test successful DataMate URL saving with a value"""
    # Setup
    mock_auth_header = "Bearer test-token"
    test_data = {"datamate_url": "https://test.datamate.com"}

    # Mock user and tenant ID
    config_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

    # Execute
    result = await save_datamate_url(test_data, mock_auth_header)

    # Assert
    assert isinstance(result, JSONResponse)
    assert result.status_code == 200

    # Parse the JSON response body to verify content
    import json
    response_body = json.loads(result.body.decode())
    assert response_body["status"] == "saved"
    assert "DataMate URL saved successfully" in response_body["message"]

    config_mocks['get_current_user_id'].assert_called_once_with(mock_auth_header)
    config_mocks['set_single_config'].assert_called_once_with(
        "test_user_id", "test_tenant_id", "DATAMATE_URL", "https://test.datamate.com")


@pytest.mark.asyncio
async def test_save_datamate_url_success_empty_value(config_mocks):
    """Test successful DataMate URL saving with empty value (deletion)"""
    # Setup
    mock_auth_header = "Bearer test-token"
    test_data = {"datamate_url": "   "}  # Whitespace-only, should be treated as empty

    # Mock user and tenant ID
    config_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

    # Execute
    result = await save_datamate_url(test_data, mock_auth_header)

    # Assert
    assert isinstance(result, JSONResponse)
    assert result.status_code == 200

    # Parse the JSON response body to verify content
    import json
    response_body = json.loads(result.body.decode())
    assert response_body["status"] == "saved"
    assert "DataMate URL saved successfully" in response_body["message"]

    config_mocks['get_current_user_id'].assert_called_once_with(mock_auth_header)
    config_mocks['delete_single_config'].assert_called_once_with("test_tenant_id", "DATAMATE_URL")


@pytest.mark.asyncio
async def test_save_datamate_url_success_no_url_key(config_mocks):
    """Test successful DataMate URL saving with no datamate_url key (deletion)"""
    # Setup
    mock_auth_header = "Bearer test-token"
    test_data = {}  # No datamate_url key

    # Mock user and tenant ID
    config_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

    # Execute
    result = await save_datamate_url(test_data, mock_auth_header)

    # Assert
    assert isinstance(result, JSONResponse)
    assert result.status_code == 200

    config_mocks['get_current_user_id'].assert_called_once_with(mock_auth_header)
    config_mocks['delete_single_config'].assert_called_once_with("test_tenant_id", "DATAMATE_URL")


@pytest.mark.asyncio
async def test_save_datamate_url_with_error(config_mocks):
    """Test DataMate URL saving with error"""
    # Setup
    mock_auth_header = "Bearer test-token"
    test_data = {"datamate_url": "https://test.datamate.com"}

    # Mock an exception when getting user ID
    config_mocks['get_current_user_id'].side_effect = Exception(
        "Authentication failed")

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await save_datamate_url(test_data, mock_auth_header)

    assert exc_info.value.status_code == 400
    assert "Failed to save DataMate URL" in str(exc_info.value.detail)
    config_mocks['logger'].error.assert_called_once()


@pytest.mark.asyncio
async def test_load_config_missing_language(config_mocks):
    """Test configuration loading with missing language parameter"""
    # Setup
    mock_request = MagicMock()
    mock_auth_header = "Bearer test-token"

    # Mock user info with None language
    config_mocks['get_user_info'].return_value = (
        "test_user", "test_tenant", None)

    # Mock service response
    mock_config = {"app": {"name": "Test App"}}
    config_mocks['load_config_impl'].return_value = mock_config

    # Execute
    result = await load_config(mock_auth_header, mock_request)

    # Assert
    assert isinstance(result, JSONResponse)
    assert result.status_code == 200

    # Parse the JSON response body to verify content
    import json
    response_body = json.loads(result.body.decode())
    assert response_body["config"] == mock_config

    config_mocks['get_user_info'].assert_called_once_with(
        mock_auth_header, mock_request)
    config_mocks['load_config_impl'].assert_called_once_with(
        None, "test_tenant")


@pytest.mark.asyncio
async def test_save_config_empty_auth_header(config_mocks):
    """Test configuration saving with empty authorization header"""
    # Setup
    mock_auth_header = ""  # Empty header
    global_config = MagicMock()

    # Mock user and tenant ID for empty auth
    config_mocks['get_current_user_id'].return_value = (
        "anonymous_user", "default_tenant")

    # Execute
    result = await save_config(global_config, mock_auth_header)

    # Assert
    assert isinstance(result, JSONResponse)
    assert result.status_code == 200

    config_mocks['get_current_user_id'].assert_called_once_with("")


@pytest.mark.asyncio
async def test_load_config_empty_auth_header(config_mocks):
    """Test configuration loading with empty authorization header"""
    # Setup
    mock_request = MagicMock()
    mock_auth_header = ""  # Empty header

    # Mock user info for empty auth
    config_mocks['get_user_info'].return_value = (
        "anonymous_user", "default_tenant", "en")

    # Mock service response
    mock_config = {"app": {"name": "Default App"}}
    config_mocks['load_config_impl'].return_value = mock_config

    # Execute
    result = await load_config(mock_auth_header, mock_request)

    # Assert
    assert isinstance(result, JSONResponse)
    assert result.status_code == 200

    config_mocks['get_user_info'].assert_called_once_with(
        "", mock_request)
    config_mocks['load_config_impl'].assert_called_once_with(
        "en", "default_tenant")


@pytest.mark.asyncio
async def test_save_datamate_url_trimmed_value(config_mocks):
    """Test DataMate URL saving with whitespace trimming"""
    # Setup
    mock_auth_header = "Bearer test-token"
    test_data = {"datamate_url": "  https://test.datamate.com  "}  # With whitespace

    # Mock user and tenant ID
    config_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

    # Execute
    result = await save_datamate_url(test_data, mock_auth_header)

    # Assert
    assert isinstance(result, JSONResponse)
    assert result.status_code == 200

    config_mocks['get_current_user_id'].assert_called_once_with(mock_auth_header)
    config_mocks['set_single_config'].assert_called_once_with(
        "test_user_id", "test_tenant_id", "DATAMATE_URL", "https://test.datamate.com")
