# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Deletion previews retain direct authentication and offload binding queries."""

import threading
from unittest.mock import AsyncMock, MagicMock

from management.api.knowledge_base import vectordatabase as local_app
import ext_components.aidp.apps.aidp_mgmt_app as aidp_app
import pytest
from management.utils.app_factory import register_exception_handlers
from contracts.exceptions import TokenExpiredError
from ext_components.aidp.consts.aidp_exceptions import (
    AidpKbNotFoundError,
    AidpKbPermissionDeniedError,
)
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from middleware.exception_handler import ExceptionHandlerMiddleware
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    get_default_thread_manager,
    run_blocking,
    set_default_thread_manager,
)
from starlette.requests import Request


EMPTY = {"agents": []}


@pytest.fixture(params=["local", "aidp"])
def preview(request, monkeypatch):
    local = request.param == "local"
    module = local_app if local else aidp_app
    auth = MagicMock(return_value=("u1", "t1", "USER") if local else ("u1", "t1"))
    monkeypatch.setattr(local_app if local else aidp_app.auth_utils_module,
                        "get_current_user_context" if local else "get_current_user_id", auth)
    permission = MagicMock()
    monkeypatch.setattr(local_app if local else aidp_app.perms,
                        "require_knowledge_base_read_permission" if local else "require_permission", permission)
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
    register_exception_handlers(app)
    app.add_middleware(ExceptionHandlerMiddleware)
    app.include_router(local_app.router if local else aidp_app.aidp_mgmt_router)
    prefix = "/indices" if local else "/aidp-mgmt/knowledge-bases"
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, prefix, collect, auth, worker_mock, permission


@pytest.mark.parametrize("agents", [[], [{"agent_id": 7, "display_name": "Private agent"}, {"agent_id": 8, "display_name": "Shared agent"}]])
def test_preview_uses_existing_business_route_and_returns_contract(preview, agents):
    client, prefix, collect, auth, worker, permission = preview
    expected = {"agents": agents}
    collect.return_value = expected
    response = client.get(f"{prefix}/missing-kb/bound_agents", headers={"Authorization": "Bearer fixture"})
    assert response.status_code == 200
    assert response.json() == expected
    collect.assert_called_once_with(["missing-kb"], tenant_id="t1")
    auth.assert_called_once_with("Bearer fixture")
    if prefix == "/indices":
        permission.assert_called_once_with("missing-kb", "u1", "t1")
    else:
        permission.assert_called_once_with("missing-kb", "u1", "t1", required="READ")
    worker.assert_awaited_once()
    assert worker.call_args.args[1] is collect


@pytest.mark.parametrize("preview", ["local"], indirect=True)
@pytest.mark.parametrize("role,tenant,status", [("USER", "t1", 200), ("USER", "selected-tenant", 403),
                                                 ("ADMIN", "selected-tenant", 403), ("SU", "selected-tenant", 200)])
def test_resource_management_preview_uses_selected_tenant(preview, role, tenant, status):
    client, prefix, collect, auth, worker, permission = preview
    auth.return_value = ("u1", "t1", role)
    response = client.get(
        f"{prefix}/idx-b/bound_agents?tenant_id={tenant}",
        headers={"Authorization": "Bearer fixture"},
    )
    assert response.status_code == status
    if status == 200:
        collect.assert_called_once_with(["idx-b"], tenant_id=tenant)
        permission.assert_called_once_with("idx-b", "u1", tenant)
    else:
        permission.assert_not_called()
        collect.assert_not_called()
        worker.assert_not_awaited()


def test_whitespace_path_is_rejected_before_auth_or_service(preview):
    client, prefix, collect, auth, worker, permission = preview
    response = client.get(f"{prefix}/%20/bound_agents", headers={"Authorization": "Bearer fixture"})
    assert response.status_code == 422
    collect.assert_not_called()
    auth.assert_not_called()
    permission.assert_not_called()
    worker.assert_not_awaited()


def test_unauthenticated_preview_cannot_query_bindings(preview):
    client, prefix, collect, auth, _, permission = preview
    auth.side_effect = TokenExpiredError("expired")
    response = client.get(f"{prefix}/idx/bound_agents", headers={"Authorization": "Bearer fixture"})
    assert response.status_code == 401
    permission.assert_not_called()
    collect.assert_not_called()


@pytest.mark.parametrize("failure,status", [("query", 500), ("permission", 500), ("denied", 403), ("missing", 200)])
def test_preview_permission_and_database_errors(preview, failure, status):
    client, prefix, collect, _, worker, permission = preview
    if failure == "query":
        collect.side_effect = RuntimeError("database unavailable")
    elif failure == "permission":
        permission.side_effect = RuntimeError("database unavailable")
    elif prefix == "/indices":
        permission.side_effect = HTTPException(status_code=404 if failure == "missing" else 403)
    else:
        permission.side_effect = (AidpKbNotFoundError("idx", "t1") if failure == "missing"
                                  else AidpKbPermissionDeniedError("idx", "u1", "READ"))
    response = client.get(f"{prefix}/idx/bound_agents", headers={"Authorization": "Bearer fixture"})
    assert response.status_code == status
    if failure != "query":
        collect.assert_not_called()
        worker.assert_not_awaited()
    if failure == "missing":
        assert response.json() == EMPTY


@pytest.mark.asyncio
@pytest.mark.parametrize("local", [True, False])
async def test_auth_runs_directly_and_binding_query_runs_in_managed_worker(monkeypatch, local):
    event_loop_thread = threading.get_ident()
    events = []

    def auth(_):
        assert threading.get_ident() == event_loop_thread
        events.append("auth")
        return ("u1", "t1", "USER") if local else ("u1", "t1")

    def query(*args, **kwargs):
        assert threading.get_ident() != event_loop_thread
        events.append("query")
        return EMPTY

    module = local_app if local else aidp_app
    monkeypatch.setattr(local_app if local else aidp_app.auth_utils_module,
                        "get_current_user_context" if local else "get_current_user_id", auth)
    monkeypatch.setattr(local_app if local else aidp_app.perms,
                        "require_knowledge_base_read_permission" if local else "require_permission", MagicMock())
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
            response = await local_app.get_knowledge_base_bound_agents("idx", "Bearer fixture", tenant_id=None)
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
