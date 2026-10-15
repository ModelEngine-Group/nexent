# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""The existing ES/AIDP apps own deletion previews and offload synchronous I/O."""

import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    get_default_thread_manager,
    run_blocking,
    set_default_thread_manager,
)
from starlette.requests import Request

import apps.vectordatabase_app as local_app
import ext_components.aidp.apps.aidp_mgmt_app as aidp_app
from consts.exceptions import TokenExpiredError
from middleware.exception_handler import ExceptionHandlerMiddleware


EMPTY = {"agents": [], "hidden_agent_count": 0, "total_agent_count": 0}


@pytest.fixture(params=["local", "aidp"])
def preview(request, monkeypatch):
    local = request.param == "local"
    module = local_app if local else aidp_app
    auth = MagicMock(return_value=("u1", "t1"))
    monkeypatch.setattr(local_app if local else aidp_app.auth_utils_module, "get_current_user_id", auth)
    collect = MagicMock(return_value=EMPTY)
    if local:
        monkeypatch.setattr(local_app.ElasticSearchService, "get_bound_agents", collect)
    else:
        monkeypatch.setattr(aidp_app, "get_bound_agents", collect)

    async def worker(task_name, function, *args, lane, owner, **kwargs):
        assert lane == "control-io"
        return function(*args, **kwargs)

    worker_mock = AsyncMock(side_effect=worker)
    monkeypatch.setattr(module, "run_blocking", worker_mock)
    app = FastAPI()
    app.add_middleware(ExceptionHandlerMiddleware)
    app.include_router(local_app.router if local else aidp_app.aidp_mgmt_router)
    prefix = "/indices" if local else "/aidp-mgmt/knowledge-bases"
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, prefix, collect, auth, worker_mock


def test_preview_uses_existing_business_route_and_returns_contract(preview):
    client, prefix, collect, auth, worker = preview
    response = client.get(f"{prefix}/missing-kb/bound_agents", headers={"Authorization": "Bearer fixture"})
    assert response.status_code == 200
    assert response.json() == EMPTY
    collect.assert_called_once_with(["missing-kb"], user_id="u1", tenant_id="t1")
    auth.assert_called_once_with("Bearer fixture")
    assert worker.await_count == 2  # Both authentication and binding reads are managed.


def test_preview_does_not_expose_retired_shared_endpoint(preview):
    client, *_ = preview
    assert client.post("/knowledge-bases/reference-preview", json={"provider": "local", "resource_id": "idx"}).status_code == 404
    assert client.post("/knowledge-bases/statuses", json={"items": []}).status_code == 404


def test_whitespace_path_is_rejected_before_auth_or_service(preview):
    client, prefix, collect, auth, worker = preview
    response = client.get(f"{prefix}/%20/bound_agents", headers={"Authorization": "Bearer fixture"})
    assert response.status_code == 422
    collect.assert_not_called()
    auth.assert_not_called()
    worker.assert_not_awaited()


def test_unauthenticated_preview_cannot_query_bindings(preview):
    client, prefix, collect, auth, _ = preview
    auth.side_effect = TokenExpiredError("expired")
    response = client.get(f"{prefix}/idx/bound_agents", headers={"Authorization": "Bearer fixture"})
    assert response.status_code == 401
    collect.assert_not_called()


def test_database_failure_is_not_returned_as_an_empty_preview(preview):
    client, prefix, collect, _, _ = preview
    collect.side_effect = RuntimeError("database unavailable")
    response = client.get(f"{prefix}/idx/bound_agents", headers={"Authorization": "Bearer fixture"})
    assert response.status_code == 500


@pytest.mark.asyncio
@pytest.mark.parametrize("local", [True, False])
async def test_sync_auth_and_binding_query_both_run_outside_event_loop(monkeypatch, local):
    event_loop_thread = threading.get_ident()
    events = []

    def auth(_):
        assert threading.get_ident() != event_loop_thread
        events.append("auth")
        return "u1", "t1"

    def query(*args, **kwargs):
        assert threading.get_ident() != event_loop_thread
        events.append("query")
        return EMPTY

    module = local_app if local else aidp_app
    monkeypatch.setattr(local_app if local else aidp_app.auth_utils_module, "get_current_user_id", auth)
    if local:
        monkeypatch.setattr(local_app.ElasticSearchService, "get_bound_agents", query)
    else:
        monkeypatch.setattr(aidp_app, "get_bound_agents", query)
    monkeypatch.setattr(module, "run_blocking", run_blocking)
    previous = get_default_thread_manager()
    manager = ThreadManager(service_name="kb-preview-ut", lane_policies={
        "control-io": LanePolicy(name="control-io", max_workers=2, max_queue_size=2,
                                 queue_timeout_seconds=1, cancel_grace_seconds=1, shutdown_grace_seconds=2),
    })
    manager.start()
    set_default_thread_manager(manager)
    try:
        if local:
            response = await local_app.get_knowledge_base_bound_agents("idx", "Bearer fixture")
        else:
            request = Request({"type": "http", "headers": [(b"authorization", b"Bearer fixture")]})
            response = await aidp_app.get_knowledge_base_bound_agents(request, "kds-1")
        assert response.status_code == 200
        assert events == ["auth", "query"]
    finally:
        clear_default_thread_manager(manager)
        if previous is not None:
            set_default_thread_manager(previous)
        await manager.shutdown(timeout=2)
