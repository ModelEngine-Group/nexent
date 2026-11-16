# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""File-proxy HTTP boundary regression with real HTTPX request construction."""

import sys
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

with pytest.MonkeyPatch.context() as import_mocks:
    import_mocks.setitem(sys.modules, "management.services.agent.service", MagicMock())
    from gateway.api import northbound


@pytest.fixture
def proxy(monkeypatch):
    monkeypatch.setattr(northbound, "MINIO_ENDPOINT", "http://minio:9000")
    app = FastAPI()
    app.include_router(northbound.router)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:9000/bucket/file",
    "http://minio:9000@evil.example/bucket/file", "http://minio.evil.example:9000/bucket/file",
    "http://minio:9001/bucket/file", "https://minio:9000/bucket/file",
])
def test_denied_origins_never_create_http_client(proxy, monkeypatch, url):
    outbound = MagicMock(side_effect=AssertionError("Untrusted URL reached HTTP client"))
    monkeypatch.setattr(northbound.httpx, "AsyncClient", outbound)
    result = proxy.get("/nb/v1/file/fetch", params={"presigned_url": url})
    assert result.status_code == 400
    outbound.assert_not_called()


@pytest.mark.parametrize("redirect", [False, True])
def test_signed_download_pins_authority_and_does_not_follow_redirect(proxy, monkeypatch, redirect):
    seen = []
    options = {}
    real_client = httpx.AsyncClient

    def storage(request):
        seen.append(request)
        if redirect:
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
        return httpx.Response(200, content=b"signed file", headers={
            "Content-Type": "text/plain", "Content-Disposition": 'attachment; filename="report.txt"',
        })

    def client_factory(**kwargs):
        options.update(kwargs)
        return real_client(transport=httpx.MockTransport(storage), **kwargs)

    monkeypatch.setattr(northbound.httpx, "AsyncClient", client_factory)
    url = "http://minio:9000/bucket/a%20b.txt?X-Amz-Signature=abc%2Fdef&x=1&x=2"
    result = proxy.get("/nb/v1/file/fetch", params={"presigned_url": url})
    assert result.status_code == (502 if redirect else 200)
    assert len(seen) == 1
    assert str(seen[0].url) == url
    assert options["follow_redirects"] is False
    assert options["trust_env"] is False
    if not redirect:
        assert result.content == b"signed file"
        assert "report.txt" in result.headers["content-disposition"]


def test_transport_error_does_not_expose_signed_url(proxy, monkeypatch):
    real_client = httpx.AsyncClient
    url = "http://minio:9000/bucket/file?X-Amz-Signature=private-signature"

    def storage(request):
        raise httpx.ConnectError(f"Could not connect to {request.url}", request=request)

    monkeypatch.setattr(
        northbound.httpx, "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(storage), **kwargs),
    )
    result = proxy.get("/nb/v1/file/fetch", params={"presigned_url": url})
    assert result.status_code == 502
    assert result.json() == {"detail": "Failed to fetch file from storage"}
    assert "private-signature" not in result.text
