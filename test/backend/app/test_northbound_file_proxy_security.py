# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""File-proxy HTTP boundary regression with real HTTPX request construction."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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
    from contracts.constants import environment

    monkeypatch.setattr(environment, "MINIO_ENDPOINT", "http://minio:9000")
    monkeypatch.setattr(environment, "MINIO_DEFAULT_BUCKET", "owned")
    app = FastAPI()
    app.include_router(northbound.router)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:9000/owned/file",
    "http://minio:9000@evil.example/owned/file", "http://minio.evil.example:9000/owned/file",
    "http://minio:9001/owned/file", "https://minio:9000/owned/file",
    "http://minio:9000/other/attachments/owner/test.txt",
])
def test_legacy_references_require_configured_origin_and_bucket(proxy, monkeypatch, url):
    identify = AsyncMock()
    monkeypatch.setattr(northbound, "_get_northbound_context", identify)
    result = proxy.get("/nb/v1/file/fetch", params={"presigned_url": url})
    assert result.status_code == 400
    identify.assert_not_awaited()


@pytest.mark.parametrize(("actor", "status"), [(None, 401), ("other", 403), ("owner", 200)])
def test_legacy_signature_never_confers_access(proxy, monkeypatch, actor, status):
    from fastapi import HTTPException, Response
    from management.api.file import ticket as file_ticket
    from management.services.file.access import check_file_access

    if actor is None:
        identify = AsyncMock(side_effect=HTTPException(401, "Missing API key"))
    else:
        identify = AsyncMock(return_value=SimpleNamespace(user_id=actor, tenant_id="tenant"))
    monkeypatch.setattr(northbound, "_get_northbound_context", identify)
    monkeypatch.setattr(northbound, "check_file_access", check_file_access)
    storage = AsyncMock(return_value=Response("owned"))
    monkeypatch.setattr(file_ticket, "download_authorized_object_response", storage)
    url = "http://minio:9000/owned/attachments/owner/a%20b.txt?X-Amz-Signature=untrusted"
    result = proxy.get("/nb/v1/file/fetch", params={"presigned_url": url})
    assert result.status_code == status
    identify.assert_awaited_once()
    if status == 200:
        assert storage.await_args.args[0] == "attachments/owner/a b.txt"
        assert result.content == b"owned"
    else:
        storage.assert_not_awaited()


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
    identify = AsyncMock(side_effect=AssertionError("A ticket already carries its authorization"))
    monkeypatch.setattr(northbound, "_get_northbound_context", identify)
    return key, version, stat, opening, owner, identify


@pytest.mark.parametrize("mode", ["full", "partial", "invalid"])
def test_ticket_reads_si_with_pinned_version_and_existing_filename(proxy, ticket_reads, mode):
    key, version, stat, opening, owner, identify = ticket_reads
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
    identify.assert_not_awaited()


@pytest.mark.parametrize("invalid", ["tampered", "expired"])
def test_bad_ticket_never_reaches_transport(proxy, ticket_reads, invalid):
    key, _, stat, opening, _, identify = ticket_reads
    token = issue_object_ticket(key, 60, secret="synthetic", now=0 if invalid == "expired" else None)
    if invalid == "tampered":
        token += "X"
    result = proxy.get("/nb/v1/file/fetch", params={"presigned_url": token})
    assert result.status_code == 403
    stat.assert_not_awaited()
    opening.assert_not_awaited()
    identify.assert_not_awaited()
