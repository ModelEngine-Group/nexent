# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public KB content requests retain identity, bounded error and response semantics."""

import httpx
import pytest
from fastapi import FastAPI
from management.api.file import knowledge_content as module
from nexent.storage.errors import ScopeDenied


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
