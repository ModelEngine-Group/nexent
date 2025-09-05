import sys
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

# Add the project root directory to sys.path
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '../../..')))

# Mock the consts.const module before importing the image_service module
mock_const = MagicMock()
mock_const.DATA_PROCESS_SERVICE = "http://mock-data-process-service"
sys.modules['consts.const'] = mock_const

# Now import the module after mocking dependencies
from services.image_service import proxy_image_impl

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
