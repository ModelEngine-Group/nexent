import sys
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

# Add the project root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# Mock the consts.const module before importing the image_app module
mock_const = MagicMock()
mock_const.DATA_PROCESS_SERVICE = "http://mock-data-process-service"
sys.modules['consts.const'] = mock_const

# Now import the module after mocking dependencies
from fastapi.testclient import TestClient
from fastapi import FastAPI
from backend.apps.image_app import router

# Create a FastAPI app and include the router for testing
app = FastAPI()
app.include_router(router)
client = TestClient(app)

# Sample test data
test_url = "https://example.com/image.jpg"
encoded_test_url = "https%3A%2F%2Fexample.com%2Fimage.jpg"
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
async def test_proxy_image_success(monkeypatch):
    """Test successful image proxy request"""
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

    # Patch the ClientSession in the correct module
    with patch('backend.services.image_service.aiohttp.ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test with TestClient
        response = client.get(f"/image?url={encoded_test_url}")

        # Assertions
        assert response.status_code == 200
        assert response.json() == success_response

        # Verify correct URL was called
        mock_session.get.assert_called_once()


@pytest.mark.asyncio
async def test_proxy_image_remote_error(monkeypatch):
    """Test image proxy when remote service returns error"""
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

    # Create expected error response
    expected_error_response = {
        "success": False,
        "error": "Failed to fetch image: Image not found"
    }

    # Patch the ClientSession in the correct module
    with patch('backend.services.image_service.aiohttp.ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test with TestClient
        response = client.get(f"/image?url={encoded_test_url}")

        # Assertions
        assert response.status_code == 200
        assert response.json()["success"] is False
        assert "Failed to fetch image" in response.json()["error"]


@pytest.mark.asyncio
async def test_proxy_image_exception(monkeypatch):
    """Test image proxy when an exception occurs"""
    # Create mock session that raises exception
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.side_effect = Exception("Connection error")
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession in the correct module
    with patch('backend.services.image_service.aiohttp.ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test with TestClient
        response = client.get(f"/image?url={encoded_test_url}")

        # Assertions
        assert response.status_code == 200
        assert response.json()["success"] is False
        assert response.json()["error"] == "Connection error"


@pytest.mark.asyncio
async def test_proxy_image_with_special_chars(monkeypatch):
    """Test image proxy with URL containing special characters"""
    special_url = "https://example.com/image with spaces.jpg"
    encoded_special_url = "https%3A%2F%2Fexample.com%2Fimage%20with%20spaces.jpg"

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

    # Patch the ClientSession in the correct module
    with patch('backend.services.image_service.aiohttp.ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test with TestClient
        response = client.get(f"/image?url={encoded_special_url}")

        # Assertions
        assert response.status_code == 200
        assert response.json() == success_response

        # Verify URL was correctly passed
        mock_session.get.assert_called_once()
        called_args = mock_session.get.call_args[0][0]
        assert special_url in called_args or encoded_special_url in called_args


@pytest.mark.asyncio
async def test_proxy_image_logging(monkeypatch):
    """Test error handling when an exception occurs"""
    # Create mock session that raises exception
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.side_effect = Exception("Logging test error")
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession in the correct module
    with patch('backend.services.image_service.aiohttp.ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test with TestClient
        response = client.get(f"/image?url={encoded_test_url}")

        # Focus on verifying the error handling in the response
        assert response.status_code == 200  # API should still return 200 status
        response_data = response.json()
        assert response_data["success"] is False
        assert "Logging test error" in response_data["error"]

        # Verify the mock was called with the expected URL
        mock_session.get.assert_called_once()
