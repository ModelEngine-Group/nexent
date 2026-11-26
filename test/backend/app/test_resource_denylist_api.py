# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""HTTP policy editing authorization, scope and conflict contracts."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from management.api.configuration import resource_denylist as tenant_api
from management.services.configuration.resource_denylist import DenylistConflict
from ops.api import system_configurations as global_api
from permissions.models import CurrentUser


@pytest.fixture(params=["tenant", "global"])
def editor(request, mocker):
    global_scope = request.param == "global"
    api = global_api if global_scope else tenant_api
    user = CurrentUser("admin", "tenant-a", "SU" if global_scope else "ADMIN")
    app = FastAPI()
    app.state.thread_manager = object()
    app.include_router(api.router)
    app.dependency_overrides[api.authenticate] = lambda: user
    if global_scope:
        mocker.patch.object(api, "authorize_operations", return_value=user.user_id)
        mocker.patch.object(api, "authorize_configuration_write", return_value=user.user_id)

        async def io(_manager, operation, *args):
            return operation(*args)

        mocker.patch.object(api, "run_system_configuration_io", new=AsyncMock(side_effect=io))
    read = mocker.patch.object(api, "read_denylist", return_value={"revision": "r1", "selected": []})
    write = mocker.patch.object(api, "update_denylist", return_value={"revision": "r2", "selected": []})
    path = "/system_configurations/resource_denylist" if global_scope else "/resource_denylist"
    return api, TestClient(app), path, user, read, write, global_scope


def test_editors_read_and_save_only_their_authorized_scope(editor):
    api, client, path, user, read, write, global_scope = editor
    response = client.get(path)
    assert response.status_code == 200 and response.json()["revision"] == "r1"
    read.assert_called_once_with(*(() if global_scope else (user.tenant_id,)))
    response = client.put(path, json={"revision": "r1", "resource_refs": []})
    assert response.status_code == 200 and response.json()["revision"] == "r2"
    args = write.call_args.args
    assert args[0].revision == "r1" and args[1] == user.user_id
    assert args[2:] == (() if global_scope else (user.tenant_id,))
    if global_scope:
        api.authorize_operations.assert_called_once_with(user)
        api.authorize_configuration_write.assert_called_once_with(user)
        assert all(call.args[0] is client.app.state.thread_manager
                   for call in api.run_system_configuration_io.call_args_list)


@pytest.mark.parametrize("error,status", [(DenylistConflict("new revision"), 409), (ValueError("unavailable"), 400)])
def test_editors_preserve_conflict_and_validation_error_status(editor, error, status):
    _, client, path, _, _, write, _ = editor
    write.side_effect = error
    response = client.put(path, json={"revision": "old", "resource_refs": []})
    assert response.status_code == status and response.json()["detail"] == str(error)


@pytest.mark.parametrize("role,tenant", [("USER", "tenant-a"), ("ADMIN", ""), ("OPS", "tenant-a")])
@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_tenant_editor_denies_non_admin_or_missing_tenant_before_io(mocker, role, tenant, method):
    app = FastAPI()
    app.include_router(tenant_api.router)
    app.dependency_overrides[tenant_api.authenticate] = lambda: CurrentUser("user", tenant, role)
    read = mocker.patch.object(tenant_api, "read_denylist")
    write = mocker.patch.object(tenant_api, "update_denylist")
    response = TestClient(app).request(method, "/resource_denylist",
                                       json={"revision": "r", "resource_refs": []})
    assert response.status_code == 403
    read.assert_not_called()
    write.assert_not_called()


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_global_editor_denies_permission_before_io(mocker, method):
    app = FastAPI()
    app.include_router(global_api.router)
    app.dependency_overrides[global_api.authenticate] = lambda: CurrentUser("user", "tenant-a", "USER")
    mocker.patch.object(global_api, "authorize_operations", side_effect=HTTPException(403, "Denied"))
    mocker.patch.object(global_api, "authorize_configuration_write", side_effect=HTTPException(403, "Denied"))
    io = mocker.patch.object(global_api, "run_system_configuration_io", new=AsyncMock())
    response = TestClient(app).request(method, "/system_configurations/resource_denylist",
                                       json={"revision": "r", "resource_refs": []})
    assert response.status_code == 403
    io.assert_not_awaited()
