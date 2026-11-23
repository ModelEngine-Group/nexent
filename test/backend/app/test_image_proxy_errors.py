# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Image proxy failures expose a stable response without internal details."""

import base64
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps import image_app


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(image_app.router)
    with TestClient(app) as value:
        yield value


@pytest.mark.parametrize("failure,response_format,status", [
    ("exception", "json", 200), ("exception", "stream", 502),
    ("upstream_error", "json", 200), ("upstream_error", "stream", 502),
    ("malformed_base64", "stream", 502),
])
def test_internal_failure_details_never_reach_client(client, mocker, response_format, status, failure):
    secret = "Traceback /private/config.py credential=secret-value"
    fetch = mocker.patch.object(image_app, "proxy_image_impl", new_callable=AsyncMock)
    if failure == "exception":
        fetch.side_effect = RuntimeError(secret)
    elif failure == "upstream_error":
        fetch.return_value = {"success": False, "error": secret}
    else:
        fetch.return_value = {"success": True, "base64": "a", "content_type": "image/png"}

    response = client.get("/image", params={"url": "https://images.example.test/image.png", "format": response_format})

    assert response.status_code == status
    assert response.json() == ({"detail": "Failed to fetch image"} if response_format == "stream" else
                               {"success": False, "error": "Failed to fetch image"})
    assert secret not in response.text


@pytest.mark.parametrize("response_format", ["json", "stream"])
def test_successful_image_response_remains_unchanged(client, mocker, response_format):
    content = b"image content"
    payload = {"success": True, "base64": base64.b64encode(content).decode(), "content_type": "image/png"}
    mocker.patch.object(image_app, "proxy_image_impl", new_callable=AsyncMock, return_value=payload)

    response = client.get("/image", params={"url": "https://images.example.test/image.png", "format": response_format})

    assert response.status_code == 200
    if response_format == "json":
        assert response.json() == payload
    else:
        assert response.content == content
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "public, max-age=3600"
