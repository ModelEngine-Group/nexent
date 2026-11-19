# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual skill route contracts and managed scheduling with controlled services."""

import asyncio
import threading

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from contracts.errors.exceptions import SkillException
from management.api.skill import skill as module
from backend.http.server.exception_handlers import register_exception_handlers
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)


@pytest.fixture
async def runtime():
    manager = ThreadManager(service_name="skill-route-test", lane_policies={
        "control-io": LanePolicy(name="control-io", max_workers=1, max_queue_size=0),
    })
    manager.start()
    set_default_thread_manager(manager)
    app = FastAPI()
    app.include_router(module.router)
    register_exception_handlers(app)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield manager, client
    finally:
        clear_default_thread_manager(manager)
        result = await manager.shutdown(timeout=3)
        assert not result.stuck_execution_ids
        assert manager.snapshot().active_count == 0


@pytest.mark.parametrize("tenant,inventory,effective", [(None, None, "current"), ("explicit", None, "explicit"),
                                                       ("explicit", "inventory", "inventory")])
@pytest.mark.parametrize("include_content", [None, False, True])
@pytest.mark.asyncio
async def test_tenant_auth_inventory_and_payload_remain_compatible(
        runtime, mocker, tenant, inventory, effective, include_content):
    _, client = runtime
    loop_thread = threading.get_ident()

    def auth(token):
        assert threading.get_ident() != loop_thread
        assert token == "Bearer token"
        return "user", "current"

    mocker.patch.object(module, "get_current_user_id", side_effect=auth)
    resource_read = mocker.patch.object(module, "resource_read_tenant", return_value=inventory)
    service_class = mocker.patch.object(module, "SkillService")
    row = {"skill_id": 1, "name": "skill", "description": "description", "source": "official", "tags": [],
           "update_time": None, "content": "full", "config_values": {"nested": [1]},
           "config_schemas": [], "tool_ids": [7, 7], "permission": "READ_ONLY"}
    service_class.return_value.list_skills.return_value = [row]
    expected = row if include_content else {key: value for key, value in row.items() if key != "content"}
    service_class.return_value.list_visible_skills.return_value = [expected]
    params = {} if tenant is None else {"tenant_id": tenant}
    if include_content is not None:
        params["include_content"] = str(include_content).lower()
    response = await client.get("/skills", params=params,
                                headers={"Authorization": "Bearer token"})
    assert response.status_code == 200
    service_class.assert_called_once_with(tenant_id=effective)
    assert resource_read.call_args.kwargs == {"shared": True}
    if inventory:
        fields = ("skill_id", "name", "description", "source", "tags", "update_time")
        assert response.json() == {"skills": [{field: row[field] for field in fields}]}
        service_class.return_value.list_skills.assert_called_once_with(include_content=False)
        service_class.return_value.list_visible_skills.assert_not_called()
    else:
        assert response.json() == {"skills": [expected]}
        service_class.return_value.list_visible_skills.assert_called_once_with(
            tenant_id=effective, user_id="user", include_content=bool(include_content))


@pytest.mark.asyncio
async def test_invalid_content_flag_is_rejected_before_handler(runtime, mocker):
    _, client = runtime
    auth = mocker.patch.object(module, "get_current_user_id")
    service = mocker.patch.object(module, "SkillService")
    response = await client.get("/skills?include_content=invalid")
    assert response.status_code == 422
    auth.assert_not_called()
    service.assert_not_called()


@pytest.mark.asyncio
async def test_blocking_actual_route_keeps_event_loop_available_and_rejects_before_auth(runtime, mocker):
    _, client = runtime
    started, release = threading.Event(), threading.Event()
    auth = mocker.patch.object(module, "get_current_user_id", return_value=("user", "current"))
    mocker.patch.object(module, "resource_read_tenant", return_value=None)

    def list_skills(**kwargs):
        started.set()
        assert release.wait(3)
        return []

    service = mocker.patch.object(module, "SkillService").return_value
    service.list_visible_skills.side_effect = list_skills
    task = asyncio.create_task(client.get("/skills"))
    try:
        async def wait_started():
            while not started.is_set():
                await asyncio.sleep(0.001)
        await asyncio.wait_for(wait_started(), 2)
        assert (await asyncio.wait_for(client.get("/ping"), 1)).json() == {"ok": True}
        assert not task.done()
        response = await client.get("/skills")
        assert response.status_code == 429
        assert response.json()["code"] == "MANAGEMENT_READ_CAPACITY_FULL"
        assert response.headers["Retry-After"] == "1"
        auth.assert_called_once()
    finally:
        release.set()
        assert (await task).json() == {"skills": []}


@pytest.mark.parametrize("error,status,detail", [(HTTPException(status_code=403, detail="denied"), 403, "denied"),
                                                (SkillException("read failed"), 500, "read failed"),
                                                (RuntimeError("private detail"), 500, "Internal server error")])
@pytest.mark.asyncio
async def test_existing_business_error_mapping(runtime, mocker, error, status, detail):
    _, client = runtime
    mocker.patch.object(module, "get_current_user_id", return_value=("user", "current"))
    mocker.patch.object(module, "resource_read_tenant", return_value=None)
    mocker.patch.object(module, "SkillService").return_value.list_visible_skills.side_effect = error
    response = await client.get("/skills")
    assert response.status_code == status
    assert response.json() == {"message": detail}
