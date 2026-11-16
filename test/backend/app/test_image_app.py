# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import sys
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

TEST_ROOT = Path(__file__).resolve().parents[2]
if str(TEST_ROOT) not in sys.path:
    sys.path.append(str(TEST_ROOT))

import management.services.file.image_content  # noqa: F401 - Load the capability before legacy SDK stubs.

from test.common.test_mocks import bootstrap_test_env

helpers_env = bootstrap_test_env()


helpers_env["mock_const"].DATA_PROCESS_SERVICE = "http://mock-data-process-service"
helpers_env["mock_const"].MODEL_CONFIG_MAPPING = {"vlm": "vlm_model_config"}
mock_const = helpers_env["mock_const"]

from fastapi import FastAPI
from fastapi.testclient import TestClient
from management.api.file.image import router

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

    from management.api.file import image as image_app
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

    from management.api.file import image as image_app
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

    from management.api.file import image as image_app
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

    from management.api.file import image as image_app
    from fastapi import HTTPException

    monkeypatch.setattr(image_app, "proxy_image_impl", fake_proxy_image_impl)

    with pytest.raises(HTTPException) as exc_info:
        await image_app.proxy_image(url=encoded_test_url, format="stream")

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Failed to fetch image"


@pytest.mark.asyncio
async def test_proxy_image_json_format_default(monkeypatch):
    """Test proxy_image with format=json (default)"""
    async def fake_proxy_image_impl(decoded_url):
        return success_response

    from management.api.file import image as image_app

    monkeypatch.setattr(image_app, "proxy_image_impl", fake_proxy_image_impl)

    result = await image_app.proxy_image(url=encoded_test_url, format="json")

    assert result == success_response


@pytest.mark.asyncio
async def test_proxy_image_json_format_exception(monkeypatch):
    """Test proxy_image with format=json when exception occurs"""
    async def fake_proxy_image_impl(decoded_url):
        raise RuntimeError("Service unavailable")

    from management.api.file import image as image_app

    monkeypatch.setattr(image_app, "proxy_image_impl", fake_proxy_image_impl)

    result = await image_app.proxy_image(url=encoded_test_url, format="json")

    assert result["success"] is False
    assert result["error"] == "Failed to fetch image"


@pytest.mark.asyncio
async def test_proxy_image_url_decoding(monkeypatch):
    """Test proxy_image correctly decodes URL"""
    special_url = "https://example.com/image with spaces.jpg"
    encoded_special_url = "https%3A%2F%2Fexample.com%2Fimage%20with%20spaces.jpg"

    call_urls = []
    async def fake_proxy_image_impl(decoded_url):
        call_urls.append(decoded_url)
        return success_response

    from management.api.file import image as image_app

    monkeypatch.setattr(image_app, "proxy_image_impl", fake_proxy_image_impl)

    await image_app.proxy_image(url=encoded_special_url, format="json")

    assert len(call_urls) == 1
    assert call_urls[0] == special_url
