# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""File-proxy HTTP boundary regression with real HTTPX request construction."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from contracts.object_tickets import issue_object_ticket
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nexent.storage.models import ObjectMetadata, ObjectRef, Revision

from test.common.file_streams import object_stream

with pytest.MonkeyPatch.context() as import_mocks:
    import_mocks.setitem(sys.modules, "management.services.agent.service", MagicMock())
    from management.api import northbound


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


@pytest.fixture
def ticket_reads(monkeypatch):
    from management.api.file import ticket as file_ticket

    key = "attachments/account/report.txt"
    version = Revision('etag:"expected"')
    metadata = ObjectMetadata(ObjectRef('files', key, version), 6, "text/plain")
    owner = object_stream(b"signed")
    monkeypatch.setattr(file_ticket, "environment", SimpleNamespace(JWT_SECRET="synthetic"))
    stat = AsyncMock(return_value=metadata)
    opening = AsyncMock(return_value=owner)
    monkeypatch.setattr(file_ticket, "run_blocking", stat)
    monkeypatch.setattr(file_ticket, "open_preview", opening)
    outbound = MagicMock(side_effect=AssertionError("A ticket is not a provider HTTP URL"))
    monkeypatch.setattr(northbound.httpx, "AsyncClient", outbound)
    return key, version, stat, opening, owner, outbound


@pytest.mark.parametrize("mode", ["full", "partial", "invalid"])
def test_ticket_reads_si_with_pinned_version_and_existing_filename(proxy, ticket_reads, mode):
    key, version, stat, opening, owner, outbound = ticket_reads
    token = issue_object_ticket(key, 60, secret="synthetic")
    headers = {}
    if mode == "partial":
        headers["Range"] = "bytes=0-5"
    if mode == "invalid":
        headers["Range"] = "bytes=8-10"
    result = proxy.get("/nb/v1/file/fetch", params={"presigned_url": token}, headers=headers)
    stat.assert_awaited_once()
    assert stat.await_args.args[2] == key
    if mode == "invalid":
        assert result.status_code == 416
        assert result.headers["content-range"] == "bytes */6"
        opening.assert_not_awaited()
    else:
        assert result.status_code == (206 if mode == "partial" else 200)
        assert result.content == b"signed"
        assert result.headers["content-disposition"] == 'attachment; filename="report.txt"'
        if mode == "partial":
            assert result.headers["content-range"] == "bytes 0-5/6"
        assert opening.await_args.args[2:] == ((0, 5) if mode == "partial" else (None, None))
        assert opening.await_args.kwargs == {"version": version}
        owner.aclose.assert_awaited_once()
    outbound.assert_not_called()


@pytest.mark.parametrize("invalid", ["tampered", "expired"])
def test_bad_ticket_never_reaches_transport(proxy, ticket_reads, invalid):
    key, _, stat, opening, _, outbound = ticket_reads
    token = issue_object_ticket(key, 60, secret="synthetic", now=0 if invalid == "expired" else None)
    if invalid == "tampered":
        token += "X"
    result = proxy.get("/nb/v1/file/fetch", params={"presigned_url": token})
    assert result.status_code == 403
    stat.assert_not_awaited()
    opening.assert_not_awaited()
    outbound.assert_not_called()
