# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Image proxy failures expose a stable response without internal details."""

import base64
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from management.api.file import image as image_app


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


def test_s3_route_propagates_verified_identity(client, mocker):
    mocker.patch.object(image_app, "get_current_user_id", return_value=("owner", "tenant"))
    fetch = mocker.patch.object(image_app, "proxy_image_impl", new_callable=AsyncMock,
                              return_value={"success": True, "base64": "AQ==", "content_type": "image/png"})
    response = client.get("/image", params={"url": "s3://files/attachments/owner/a.png"},
                          headers={"Authorization": "Bearer synthetic"})
    assert response.status_code == 200
    fetch.assert_awaited_once_with("s3://files/attachments/owner/a.png", user_id="owner", tenant_id="tenant")


@pytest.mark.parametrize("response_format,status", [("json", 200), ("stream", 502)])
def test_timeout_is_redacted_warning_once(client, mocker, caplog, response_format, status):
    fetch = mocker.patch.object(image_app, "proxy_image_impl", new_callable=AsyncMock,
                              side_effect=TimeoutError("secret-value"))
    response = client.get("/image", params={"url": "https://example.test/a?token=secret-value", "format": response_format})
    assert response.status_code == status
    assert "secret-value" not in response.text
    assert "secret-value" not in caplog.text
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "WARNING"
    assert "image_proxy_timeout phase=content threshold_seconds=5" in caplog.text
    fetch.assert_awaited_once()
