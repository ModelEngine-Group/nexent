import sys
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

TEST_ROOT = Path(__file__).resolve().parents[2]
if str(TEST_ROOT) not in sys.path:
    sys.path.append(str(TEST_ROOT))

from test.common.test_mocks import bootstrap_test_env

helpers_env = bootstrap_test_env()


helpers_env["mock_const"].DATA_PROCESS_SERVICE = "http://mock-data-process-service"
helpers_env["mock_const"].MODEL_CONFIG_MAPPING = {"vlm": "vlm_model_config"}
mock_const = helpers_env["mock_const"]

from fastapi import FastAPI
from fastapi.testclient import TestClient
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
    with patch('services.image_service.aiohttp.ClientSession') as mock_session_class:
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
    with patch('services.image_service.aiohttp.ClientSession') as mock_session_class:
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
    with patch('services.image_service.aiohttp.ClientSession') as mock_session_class:
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
    with patch('services.image_service.aiohttp.ClientSession') as mock_session_class:
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
    with patch('services.image_service.aiohttp.ClientSession') as mock_session_class:
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


@pytest.mark.asyncio
async def test_proxy_image_stream_format(monkeypatch):
    """Test proxy_image with format=stream"""
    import base64
    from io import BytesIO
    
    # Create mock response with base64 image data
    test_image_bytes = b"fake image data"
    test_base64 = base64.b64encode(test_image_bytes).decode('utf-8')
    
    success_response_stream = {
        "success": True,
        "base64": test_base64,
        "content_type": "image/png"
    }
    
    async def fake_proxy_image_impl(decoded_url):
        return success_response_stream
    
    from backend.apps import image_app
    monkeypatch.setattr(image_app, "proxy_image_impl", fake_proxy_image_impl)
    
    resp = await image_app.proxy_image(url=encoded_test_url, format="stream")
    
    # Should return StreamingResponse
    assert hasattr(resp, 'media_type')
    assert resp.media_type == "image/png"
    assert "Cache-Control" in resp.headers
    assert resp.headers["Cache-Control"] == "public, max-age=3600"
    
    # Verify content
    content = b""
    async for chunk in resp.body_iterator:
        content += chunk
    assert content == test_image_bytes


@pytest.mark.asyncio
async def test_proxy_image_stream_format_error(monkeypatch):
    """Test proxy_image with format=stream when proxy_image_impl returns error"""
    error_response = {
        "success": False,
        "error": "Failed to fetch image"
    }
    
    async def fake_proxy_image_impl(decoded_url):
        return error_response
    
    from backend.apps import image_app
    from fastapi import HTTPException
    
    monkeypatch.setattr(image_app, "proxy_image_impl", fake_proxy_image_impl)
    
    with pytest.raises(HTTPException) as exc_info:
        await image_app.proxy_image(url=encoded_test_url, format="stream")
    
    assert exc_info.value.status_code == 502
    assert "Failed to fetch image" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_proxy_image_stream_format_base64_decode_error(monkeypatch):
    """Test proxy_image with format=stream when base64 decoding fails"""
    import base64
    
    # Invalid base64 data
    success_response_invalid = {
        "success": True,
        "base64": "invalid base64!!!",
        "content_type": "image/png"
    }
    
    async def fake_proxy_image_impl(decoded_url):
        return success_response_invalid
    
    from backend.apps import image_app
    from fastapi import HTTPException
    
    monkeypatch.setattr(image_app, "proxy_image_impl", fake_proxy_image_impl)
    
    with pytest.raises(HTTPException) as exc_info:
        await image_app.proxy_image(url=encoded_test_url, format="stream")
    
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_proxy_image_stream_format_exception(monkeypatch):
    """Test proxy_image with format=stream when exception occurs"""
    async def fake_proxy_image_impl(decoded_url):
        raise ValueError("Unexpected error")
    
    from backend.apps import image_app
    from fastapi import HTTPException
    
    monkeypatch.setattr(image_app, "proxy_image_impl", fake_proxy_image_impl)
    
    with pytest.raises(HTTPException) as exc_info:
        await image_app.proxy_image(url=encoded_test_url, format="stream")
    
    assert exc_info.value.status_code == 502
    assert "Unexpected error" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_proxy_image_json_format_default(monkeypatch):
    """Test proxy_image with format=json (default)"""
    async def fake_proxy_image_impl(decoded_url):
        return success_response
    
    from backend.apps import image_app
    
    monkeypatch.setattr(image_app, "proxy_image_impl", fake_proxy_image_impl)
    
    result = await image_app.proxy_image(url=encoded_test_url, format="json")
    
    assert result == success_response


@pytest.mark.asyncio
async def test_proxy_image_json_format_exception(monkeypatch):
    """Test proxy_image with format=json when exception occurs"""
    async def fake_proxy_image_impl(decoded_url):
        raise RuntimeError("Service unavailable")
    
    from backend.apps import image_app
    
    monkeypatch.setattr(image_app, "proxy_image_impl", fake_proxy_image_impl)
    
    result = await image_app.proxy_image(url=encoded_test_url, format="json")
    
    assert result["success"] is False
    assert "Service unavailable" in result["error"]


@pytest.mark.asyncio
async def test_proxy_image_url_decoding(monkeypatch):
    """Test proxy_image correctly decodes URL"""
    special_url = "https://example.com/image with spaces.jpg"
    encoded_special_url = "https%3A%2F%2Fexample.com%2Fimage%20with%20spaces.jpg"
    
    call_urls = []
    async def fake_proxy_image_impl(decoded_url):
        call_urls.append(decoded_url)
        return success_response
    
    from backend.apps import image_app
    
    monkeypatch.setattr(image_app, "proxy_image_impl", fake_proxy_image_impl)
    
    await image_app.proxy_image(url=encoded_special_url, format="json")
    
    assert len(call_urls) == 1
    assert call_urls[0] == special_url
