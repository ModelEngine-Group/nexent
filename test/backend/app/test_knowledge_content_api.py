# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public KB content requests retain identity, bounded error and response semantics."""

import httpx
import pytest
from contracts.agentos_knowledge import KnowledgeSearchHit
from fastapi import FastAPI
from management.api.file import knowledge_content as module
from management.services.knowledge_base.hybrid import project_retrieved_image
from management.services.knowledge_base.image_ticket import (
    IMAGE_TICKET_PREFIX,
    open_image_ticket,
)
from nexent.storage.errors import ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal


@pytest.mark.asyncio
async def test_source_download_uses_trusted_identity_and_safe_attachment_header(mocker):
    app = FastAPI()
    app.include_router(module.router)
    mocker.patch.object(module, "get_current_user_id", return_value=("user", "tenant"))
    fetch = mocker.patch.object(
        module, "fetch_knowledge_content", return_value=(b"content", "report.txt")
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://management"
    ) as client:
        response = await client.post(
            "/file/knowledge/content",
            json={"knowledge_id": 1, "file_id": "a" * 32, "file_version": 0},
        )
    assert response.status_code == 200 and response.content == b"content"
    assert response.headers["content-disposition"].startswith("attachment")
    assert (
        response.headers["cache-control"] == "no-store"
        and response.headers["x-content-type-options"] == "nosniff"
    )
    assert fetch.await_args.kwargs == {"user_id": "user", "tenant_id": "tenant"}


@pytest.mark.parametrize("error,status", [(ScopeDenied(), 403), (TimeoutError(), 504)])
@pytest.mark.asyncio
async def test_content_errors_are_redacted(mocker, error, status):
    app = FastAPI()
    app.include_router(module.router)
    mocker.patch.object(module, "get_current_user_id", return_value=("user", "tenant"))
    mocker.patch.object(module, "fetch_knowledge_content", side_effect=error)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://management"
    ) as client:
        response = await client.post(
            "/file/knowledge/content",
            json={"knowledge_id": 1, "file_id": "a" * 32, "file_version": 0},
        )
    assert response.status_code == status and set(response.json()) == {"code"}


@pytest.mark.asyncio
async def test_image_preview_uses_raster_content_type_without_exposing_storage_url(mocker):
    app = FastAPI()
    app.include_router(module.router)
    mocker.patch.object(module, "get_current_user_id", return_value=("user", "tenant"))
    mocker.patch.object(module, "fetch_knowledge_content", return_value=(b"image", "source.docx"))
    payload = {"knowledge_id": 1, "file_id": "a" * 32, "file_version": 0,
               "image_ref": {"space": "files", "key": f"images/{'b' * 64}/{'c' * 64}.png",
                             "version": "v1", "sha256": "c" * 64}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://management") as client:
        response = await client.post("/file/knowledge/content", json=payload)
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"] == "inline" and "location" not in response.headers


@pytest.mark.asyncio
async def test_request_cannot_supply_tenant_or_unpinned_object_key(mocker):
    app = FastAPI()
    app.include_router(module.router)
    identity = mocker.patch.object(module, "get_current_user_id")
    fetch = mocker.patch.object(module, "fetch_knowledge_content")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://management") as client:
        response = await client.post("/file/knowledge/content", json={
            "knowledge_id": 1, "file_id": "a" * 32, "file_version": 0, "tenant_id": "foreign", "object_key": "arbitrary"})
    assert response.status_code == 422
    identity.assert_not_called()
    fetch.assert_not_called()


@pytest.fixture
def image_hit(monkeypatch):
    from contracts.constants import environment

    monkeypatch.setattr(environment, "JWT_SECRET", "owned-test-image-secret")
    return KnowledgeSearchHit(
        knowledge_id=3, file_id="a" * 32, file_version=7, chunk_id="owned", filename="source.pptx",
        content="internal body", score=1, score_kind="dense",
        location={"page_number": 2, "coordinates": {"x1": 15}, "internal": "private"},
        image_ref={"space": "files", "key": "images/pinned.png", "version": "private-revision", "sha256": "c" * 64},
    )


@pytest.mark.parametrize("fault", [None, "user", "tenant", "tampered", "expired", "revoked"])
@pytest.mark.asyncio
async def test_image_url_has_bound_identity_and_live_content_check(image_hit, mocker, fault):
    import json

    app = FastAPI()
    app.include_router(module.router)
    clock = mocker.patch("cryptography.fernet.time.time", return_value=20_000)
    actor = ServicePrincipal("user", "tenant")
    document = project_retrieved_image(image_hit, actor)
    content = json.loads(document["content"])
    address = content["image_url"]
    assert content["position"] == {"page_number": 2, "coordinates": {"x1": 15}}
    assert document["metadata"]["image_url"] == address
    assert all(value not in str(document) for value in ("images/pinned.png", "private-revision", "private"))
    if fault == "tampered":
        start = address.index(IMAGE_TICKET_PREFIX) + len(IMAGE_TICKET_PREFIX) + 20
        address = address[:start] + ("A" if address[start] != "A" else "B") + address[start + 1:]
    if fault == "expired":
        clock.return_value += 601
    mocker.patch.object(module, "get_current_user_id", return_value=(
        "other" if fault == "user" else "user", "other" if fault == "tenant" else "tenant"))
    fetch = mocker.patch.object(module, "fetch_knowledge_content", return_value=(b"image", "source.pptx"))
    if fault == "revoked":
        fetch.side_effect = ScopeDenied()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://management") as client:
        response = await client.get(address.removeprefix("/api"))
    if fault:
        assert response.status_code == 403 and set(response.json()) == {"code"}
    else:
        assert response.status_code == 200 and response.content == b"image"
        assert response.headers["content-disposition"] == "inline"
        assert response.headers["cache-control"] == "no-store"
    if fault in {None, "revoked"}:
        request, = fetch.await_args.args
        assert request.image_ref == image_hit.image_ref and request.file_version == 7
    else:
        fetch.assert_not_called()


def test_northbound_url_requires_the_northbound_audience(image_hit):
    from urllib.parse import parse_qs, urlsplit

    actor = ServicePrincipal("user", "tenant")
    result = project_retrieved_image(image_hit, actor, northbound=True)
    url = urlsplit(result["metadata"]["image_url"])
    token, = parse_qs(url.query)["presigned_url"]
    assert url.path.endswith("/nb/v1/file/fetch")
    assert open_image_ticket(token, actor, northbound=True).image_ref == image_hit.image_ref
    with pytest.raises(ScopeDenied):
        open_image_ticket(token, actor)


@pytest.mark.asyncio
async def test_northbound_fetch_uses_current_api_key_identity_for_image_ticket(image_hit, mocker):
    from types import SimpleNamespace
    from urllib.parse import urlsplit

    from management.api import northbound

    app = FastAPI()
    app.include_router(northbound.router)
    actor = ServicePrincipal("user", "tenant")
    document = project_retrieved_image(image_hit, actor, northbound=True)
    url = urlsplit(document["metadata"]["image_url"])
    identity = mocker.patch.object(northbound, "_get_northbound_context",
                                   return_value=SimpleNamespace(user_id=actor.user_id, tenant_id=actor.tenant_id))
    fetch = mocker.patch.object(module, "fetch_knowledge_content", return_value=(b"owned image", "file.pptx"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://management") as client:
        response = await client.get("/nb/v1/file/fetch?" + url.query, headers={"Authorization": "Bearer fixture-api-key"})
        assert response.status_code == 200 and response.content == b"owned image"
        identity.return_value = SimpleNamespace(user_id="other", tenant_id=actor.tenant_id)
        denied = await client.get("/nb/v1/file/fetch?" + url.query, headers={"Authorization": "Bearer other-api-key"})
    assert denied.status_code == 403
    fetch.assert_awaited_once()
    assert fetch.await_args.kwargs == {"user_id": actor.user_id, "tenant_id": actor.tenant_id}


@pytest.mark.asyncio
async def test_legacy_image_ticket_uses_existing_get_endpoint_and_current_actor(image_hit, mocker):
    from contracts.agentos_knowledge import KnowledgeLegacyImageRequest
    from management.services.knowledge_base.image_ticket import issue_image_url

    request = KnowledgeLegacyImageRequest(knowledge_id=3, chunk_key="old-physical-key", index_uuid="origin",
        sequence=5, primary_term=1, image_ref=image_hit.image_ref)
    actor = ServicePrincipal("user", "tenant")
    address = issue_image_url(request, actor)
    app = FastAPI()
    app.include_router(module.router)
    current = mocker.patch.object(module, "get_current_user_id", return_value=(actor.user_id, actor.tenant_id))
    fetch = mocker.patch.object(module, "fetch_knowledge_content", return_value=(b"legacy image", "source.pdf"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://management") as client:
        success = await client.get(address.removeprefix("/api"))
        current.return_value = (actor.user_id, "other")
        rejected = await client.get(address.removeprefix("/api"))
    assert success.status_code == 200 and success.content == b"legacy image"
    assert success.headers["content-type"] == "image/png"
    assert rejected.status_code == 403
    fetch.assert_awaited_once_with(request, user_id=actor.user_id, tenant_id=actor.tenant_id)
