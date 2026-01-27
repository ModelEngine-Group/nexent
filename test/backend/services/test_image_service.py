import sys
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

TEST_ROOT = Path(__file__).resolve().parents[2]
if str(TEST_ROOT) not in sys.path:
    sys.path.append(str(TEST_ROOT))

from test.common.env_test_utils import bootstrap_env

helpers_env = bootstrap_env()

helpers_env["mock_const"].DATA_PROCESS_SERVICE = "http://mock-data-process-service"
helpers_env["mock_const"].MODEL_CONFIG_MAPPING = {"vlm": "vlm_model_config"}
mock_const = helpers_env["mock_const"]

from services.image_service import get_vlm_model, proxy_image_impl

# Sample test data
test_url = "https://example.com/image.jpg"
success_response = {
    "success": True,
    "data": "base64_encoded_image_data",
    "mime_type": "image/jpeg"
}
error_response = {
    "success": False,
    "error": "Failed to fetch image or image format not supported"
}


@pytest.mark.asyncio
async def test_proxy_image_impl_success():
    """Test successful image proxy implementation"""
    # Create mock response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=success_response)

    # Create mock session
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession
    with patch('services.image_service.aiohttp.ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test the function
        result = await proxy_image_impl(test_url)

        # Assertions
        assert result == success_response

        # Verify correct URL was called
        mock_session.get.assert_called_once()
        called_url = mock_session.get.call_args[0][0]
        assert "http://mock-data-process-service/tasks/load_image" in called_url
        assert f"url={test_url}" in called_url


@pytest.mark.asyncio
async def test_proxy_image_impl_remote_error():
    """Test image proxy implementation when remote service returns error"""
    # Create mock response
    mock_response = AsyncMock()
    mock_response.status = 404
    mock_response.text = AsyncMock(return_value="Image not found")

    # Create mock session
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession
    with patch('services.image_service.aiohttp.ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test the function
        result = await proxy_image_impl(test_url)

        # Assertions
        assert result["success"] is False
        assert result["error"] == "Failed to fetch image or image format not supported"

        # Verify correct URL was called
        mock_session.get.assert_called_once()


@pytest.mark.asyncio
async def test_proxy_image_impl_500_error():
    """Test image proxy implementation when remote service returns 500 error"""
    # Create mock response
    mock_response = AsyncMock()
    mock_response.status = 500
    mock_response.text = AsyncMock(return_value="Internal server error")

    # Create mock session
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession
    with patch('services.image_service.aiohttp.ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test the function
        result = await proxy_image_impl(test_url)

        # Assertions
        assert result["success"] is False
        assert result["error"] == "Failed to fetch image or image format not supported"

        # Verify correct URL was called
        mock_session.get.assert_called_once()


@pytest.mark.asyncio
async def test_proxy_image_impl_connection_exception():
    """Test image proxy implementation when connection exception occurs"""
    # Create mock session that raises exception
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.side_effect = Exception("Connection error")
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession
    with patch('services.image_service.aiohttp.ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test the function - should raise the exception
        with pytest.raises(Exception) as exc_info:
            await proxy_image_impl(test_url)

        # Verify the exception message
        assert "Connection error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_proxy_image_impl_with_special_chars():
    """Test image proxy implementation with URL containing special characters"""
    special_url = "https://example.com/image with spaces.jpg"

    # Create mock response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=success_response)

    # Create mock session
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession
    with patch('services.image_service.aiohttp.ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test the function
        result = await proxy_image_impl(special_url)

        # Assertions
        assert result == success_response

        # Verify URL was correctly passed
        mock_session.get.assert_called_once()
        called_url = mock_session.get.call_args[0][0]
        assert "http://mock-data-process-service/tasks/load_image" in called_url
        assert f"url={special_url}" in called_url


@pytest.mark.asyncio
async def test_proxy_image_impl_json_parse_error():
    """Test image proxy implementation when JSON parsing fails"""
    # Create mock response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(side_effect=Exception("Invalid JSON"))

    # Create mock session
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession
    with patch('services.image_service.aiohttp.ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test the function - should raise the exception
        with pytest.raises(Exception) as exc_info:
            await proxy_image_impl(test_url)

        # Verify the exception message
        assert "Invalid JSON" in str(exc_info.value)


@pytest.mark.asyncio
async def test_proxy_image_impl_different_status_codes():
    """Test image proxy implementation with different HTTP status codes"""
    test_cases = [
        (400, "Bad Request"),
        (401, "Unauthorized"),
        (403, "Forbidden"),
        (429, "Too Many Requests"),
        (502, "Bad Gateway"),
        (503, "Service Unavailable")
    ]

    for status_code, status_text in test_cases:
        # Create mock response
        mock_response = AsyncMock()
        mock_response.status = status_code
        mock_response.text = AsyncMock(return_value=status_text)

        # Create mock session
        mock_session = AsyncMock()
        mock_get = AsyncMock()
        mock_get.__aenter__.return_value = mock_response
        mock_session.get = MagicMock(return_value=mock_get)

        # Create mock session factory
        mock_client_session = AsyncMock()
        mock_client_session.__aenter__.return_value = mock_session

        # Patch the ClientSession
        with patch('services.image_service.aiohttp.ClientSession') as mock_session_class:
            mock_session_class.return_value = mock_client_session

            # Test the function
            result = await proxy_image_impl(test_url)

            # Assertions
            assert result["success"] is False
            assert result["error"] == "Failed to fetch image or image format not supported"

            # Verify correct URL was called
            mock_session.get.assert_called_once()


@pytest.mark.asyncio
async def test_proxy_image_impl_url_encoding():
    """Test image proxy implementation with URL encoding"""
    encoded_url = "https%3A%2F%2Fexample.com%2Fimage.jpg"
    decoded_url = "https://example.com/image.jpg"

    # Create mock response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=success_response)

    # Create mock session
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession
    with patch('services.image_service.aiohttp.ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test the function with encoded URL
        result = await proxy_image_impl(encoded_url)

        # Assertions
        assert result == success_response

        # Verify URL was correctly passed (should be URL encoded in the request)
        mock_session.get.assert_called_once()
        called_url = mock_session.get.call_args[0][0]
        assert "http://mock-data-process-service/tasks/load_image" in called_url
        assert f"url={encoded_url}" in called_url


@patch('services.image_service.OpenAIVLModel')
@patch('services.image_service.MessageObserver')
@patch('services.image_service.get_model_name_from_config')
@patch('services.image_service.tenant_config_manager')
def test_get_vlm_model_success(mock_tenant_config_manager, mock_get_model_name, mock_message_observer, mock_openai_vl_model):
    """Ensure get_vlm_model builds OpenAIVLModel with tenant config."""
    mock_config = {
        "base_url": "https://mock-api",
        "api_key": "secret",
        "model_name": "gpt-4v"
    }
    mock_tenant_config_manager.get_model_config.return_value = mock_config
    mock_get_model_name.return_value = "gpt-4v"
    mock_model_instance = MagicMock()
    mock_openai_vl_model.return_value = mock_model_instance

    result = get_vlm_model("tenant-1")

    mock_tenant_config_manager.get_model_config.assert_called_once_with(
        key=mock_const.MODEL_CONFIG_MAPPING["vlm"],
        tenant_id="tenant-1"
    )
    mock_message_observer.assert_called_once_with()
    mock_openai_vl_model.assert_called_once_with(
        observer=mock_message_observer.return_value,
        model_id="gpt-4v",
        api_base="https://mock-api",
        api_key="secret",
        temperature=0.7,
        top_p=0.7,
        frequency_penalty=0.5,
        max_tokens=512,
        ssl_verify=True
    )
    assert result == mock_model_instance


@patch('services.image_service.OpenAIVLModel')
@patch('services.image_service.MessageObserver')
@patch('services.image_service.get_model_name_from_config')
@patch('services.image_service.tenant_config_manager')
def test_get_vlm_model_with_empty_config(mock_tenant_config_manager, mock_get_model_name, mock_message_observer, mock_openai_vl_model):
    """Fallback to empty values when tenant config is empty."""
    mock_tenant_config_manager.get_model_config.return_value = {}
    mock_model_instance = MagicMock()
    mock_openai_vl_model.return_value = mock_model_instance

    result = get_vlm_model("tenant-2")

    # get_model_name_from_config should not be called because config is falsy
    mock_get_model_name.assert_not_called()
    mock_openai_vl_model.assert_called_once_with(
        observer=mock_message_observer.return_value,
        model_id="",
        api_base="",
        api_key="",
        temperature=0.7,
        top_p=0.7,
        frequency_penalty=0.5,
        max_tokens=512,
        ssl_verify=True
    )
    assert result == mock_model_instance
