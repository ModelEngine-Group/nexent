# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify archive HTTP contracts with isolated identity and storage boundaries."""

import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, call

import httpx
import pytest
from fastapi import FastAPI

from ops.api import trajectory as api
from ops.services.trajectory.access import Actor
from ops.services.trajectory.primitives import QueryError


ACTOR = Actor("operator", "tenant", "OPS")
AUTHORIZATION = {"Authorization": "Bearer session"}


@pytest.fixture
async def archive_api(mocker):
    app = FastAPI()
    app.include_router(api.router)

    async def run(lane, spec, work):
        assert lane == "trajectory-read"
        assert spec.pass_cancel_event is True
        return work(Event())

    app.state.thread_manager = SimpleNamespace(run=run)
    identity = mocker.patch.object(
        api, "get_current_user_context", return_value=("operator", "tenant", ("OPS",))
    )
    source = mocker.patch.object(api, "get_service")
    store = mocker.patch.object(api, "configured_store").return_value
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://ops"
    ) as client:
        yield client, identity, source, store


async def test_export_returns_private_download_and_passes_requested_scope(archive_api, mocker):
    client, identity, source, _ = archive_api
    export = mocker.patch.object(api, "export_conversation", return_value=b"zip body")
    response = await client.post(
        "/trajectory/conversations/42/export",
        params={"tenant_id": "scope", "target_user_id": "owner"},
        headers=AUTHORIZATION,
    )
    assert response.status_code == 200
    assert response.content == b"zip body"
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == (
        'attachment; filename="trajectory-42.zip"'
    )
    assert response.headers["cache-control"] == "private,no-store"
    identity.assert_called_once_with("Bearer session")
    export.assert_called_once_with(
        source.return_value, ACTOR, "42", "scope", "owner", limits=api.configured_limits()
    )


@pytest.mark.parametrize("path", ["/trajectory/import", "/trajectory/imports"])
@pytest.mark.parametrize("roles,status,code", [
    (None, 401, "unauthenticated"),
    (("USER",), 403, "administrator_required"),
])
async def test_upload_rejects_before_reading_body(archive_api, mocker, path, roles, status, code):
    client, identity, source, store = archive_api
    identity.return_value = ("operator" if roles else None, "tenant", roles)
    read_form = mocker.patch.object(api, "read_archive_form")
    response = await client.post(path, content=b"not multipart")
    assert response.status_code == status
    assert response.json() == {"detail": {"code": code}}
    assert response.headers["cache-control"] == "private,no-store"
    read_form.assert_not_called()
    source.assert_not_called()
    store.create.assert_not_called()


@pytest.mark.parametrize("path", ["/trajectory/import", "/trajectory/imports"])
async def test_upload_maps_bad_form_to_private_422(archive_api, path):
    client, identity, source, store = archive_api
    response = await client.post(path, files={"wrong": ("capture.zip", b"zip body")})
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_archive"}}
    assert response.headers["cache-control"] == "private,no-store"
    identity.assert_called_once()
    source.assert_not_called()
    store.create.assert_not_called()


@pytest.mark.parametrize("save", [False, True])
@pytest.mark.parametrize("parse_fails", [False, True])
async def test_upload_rechecks_identity_and_closes_file(archive_api, mocker, save, parse_fails):
    client, identity, source, store = archive_api
    files_seen = []

    def parse(file):
        files_seen.append(file)
        assert not file.closed
        assert file.read() == b"zip body"
        if parse_fails:
            raise QueryError("invalid_archive", 422)
        return {"row": {"conversation_id": "42"}}

    parse_archive = mocker.patch.object(
        api, "import_archive", side_effect=lambda file, limits: parse(file)
    )
    store.create.side_effect = lambda actor, file, filename: parse(file)
    response = await client.post(
        "/trajectory/imports" if save else "/trajectory/import",
        files={"file": ("capture.zip", b"zip body")},
        headers=AUTHORIZATION,
    )
    assert response.headers["cache-control"] == "private,no-store"
    assert identity.call_args_list == [call("Bearer session")] * 2
    (file,) = files_seen
    assert file.closed
    source.assert_not_called()
    if save:
        store.create.assert_called_once_with(ACTOR, file, "capture.zip")
        parse_archive.assert_not_called()
    else:
        parse_archive.assert_called_once_with(file, limits=api.configured_limits())
        store.create.assert_not_called()
    if parse_fails:
        assert response.status_code == 422
        assert response.json() == {"detail": {"code": "invalid_archive"}}
    else:
        assert response.status_code == 200
        assert response.json()["data"] == {"row": {"conversation_id": "42"}}


async def test_list_passes_pagination_and_sort_without_loading_capture(archive_api):
    client, _, source, store = archive_api
    store.list.return_value = {"items": [], "total": 2}
    response = await client.get(
        "/trajectory/imports",
        params={"page": 3, "page_size": 2, "sort_by": "filename", "sort_order": "asc"},
    )
    assert response.status_code == 200
    assert response.json()["data"] == {"items": [], "total": 2}
    store.list.assert_called_once_with(ACTOR, 3, 2, sort_by="filename", sort_order="asc")
    source.assert_not_called()


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 101}, {"sort_order": "bad"}])
async def test_list_rejects_invalid_parameters_without_touching_storage(archive_api, params):
    client, identity, _, store = archive_api
    response = await client.get("/trajectory/imports", params=params)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", next(iter(params))]
    identity.assert_not_called()
    store.list.assert_not_called()


@pytest.mark.parametrize("method,operation", [("GET", "read"), ("DELETE", "delete")])
async def test_saved_import_operation_receives_actor_and_preserves_not_found(archive_api, method, operation):
    client, _, source, store = archive_api
    action = getattr(store, operation)
    action.side_effect = [{"import_id": "stored"}, QueryError("import_not_found", 404)]
    response = await client.request(method, "/trajectory/imports/stored")
    assert response.status_code == 200
    assert response.json()["data"] == {"import_id": "stored"}
    response = await client.request(method, "/trajectory/imports/missing")
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "import_not_found"}}
    assert response.headers["cache-control"] == "private,no-store"
    assert action.call_args_list == [call(ACTOR, "stored"), call(ACTOR, "missing")]
    source.assert_not_called()


async def test_request_owned_dispatch_cancels_the_worker_on_disconnect():
    started, stopped = asyncio.Event(), asyncio.Event()

    async def run(lane, spec, work):
        started.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    async def receive():
        await started.wait()
        return {"type": "http.disconnect"}

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(thread_manager=SimpleNamespace(run=run))),
        receive=receive,
    )
    operation = Mock()
    async with asyncio.timeout(2):
        with pytest.raises(asyncio.CancelledError):
            await api.dispatch(request, None, operation, request_owned=True)
    assert stopped.is_set()
    operation.assert_not_called()
