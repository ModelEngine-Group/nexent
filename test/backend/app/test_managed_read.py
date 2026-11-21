# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""HTTP signature/error compatibility and event-loop progress during managed reads."""

import asyncio
import threading

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Query

from management.utils.managed_read import managed_read
from nexent.core.concurrency import (
    LanePolicy, ThreadManager, clear_default_thread_manager, set_default_thread_manager,
)


@pytest.mark.asyncio
async def test_managed_handler_keeps_http_contract_and_event_loop_responsive():
    manager = ThreadManager(service_name="read-test", lane_policies={
        "control-io": LanePolicy(name="control-io", max_workers=2, max_queue_size=2),
    })
    manager.start()
    set_default_thread_manager(manager)
    app = FastAPI()
    started, release = threading.Event(), threading.Event()
    loop_thread = threading.get_ident()

    @app.get("/read")
    @managed_read
    def slow_read(value: int = Query(..., ge=1)):
        assert threading.get_ident() != loop_thread
        if value == 2:
            raise HTTPException(status_code=403, detail="forbidden")
        started.set()
        assert release.wait(3)
        return {"data": value}

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/read", params={"value": 0})).status_code == 422
            forbidden = await client.get("/read", params={"value": 2})
            assert forbidden.status_code == 403
            assert forbidden.json() == {"detail": "forbidden"}
            task = asyncio.create_task(client.get("/read", params={"value": 1}))
            async def wait_started():
                while not started.is_set():
                    await asyncio.sleep(0.001)
            await asyncio.wait_for(wait_started(), 2)
            try:
                assert (await asyncio.wait_for(client.get("/ping"), 1)).json() == {"ok": True}
                assert not task.done()
            finally:
                release.set()
            response = await task
            assert response.status_code == 200
            assert response.json() == {"data": 1}
    finally:
        release.set()
        clear_default_thread_manager(manager)
        await manager.shutdown(timeout=3)


@pytest.mark.asyncio
async def test_full_read_lane_returns_retryable_error_without_starting_handler():
    from backend.http.server.exception_handlers import register_exception_handlers

    manager = ThreadManager(service_name="full-read-test", lane_policies={
        "control-io": LanePolicy(name="control-io", max_workers=1, max_queue_size=0),
    })
    manager.start()
    set_default_thread_manager(manager)
    started, release = threading.Event(), threading.Event()
    calls = []
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/read")
    @managed_read
    def read():
        calls.append(1)
        started.set()
        assert release.wait(3)
        return {"ok": True}

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = asyncio.create_task(client.get("/read"))
            async def wait_started():
                while not started.is_set():
                    await asyncio.sleep(0.001)
            await asyncio.wait_for(wait_started(), 2)
            try:
                rejected = await client.get("/read")
                assert rejected.status_code == 429
                assert rejected.json()["code"] == "MANAGEMENT_READ_CAPACITY_FULL"
                assert rejected.json()["retryable"] is True
                assert rejected.headers["Retry-After"] == "1"
                assert calls == [1]
            finally:
                release.set()
            assert (await first).status_code == 200
    finally:
        release.set()
        clear_default_thread_manager(manager)
        await manager.shutdown(timeout=3)


@pytest.mark.asyncio
async def test_queue_timeout_has_a_distinct_domain_code(mocker):
    from contracts.errors.exceptions import ManagementReadBusyError
    from management.utils import managed_read as module
    from nexent.core.concurrency import ThreadQueueTimedOut

    mocker.patch.object(module, "run_blocking", side_effect=ThreadQueueTimedOut("control-io", 2.5))
    with pytest.raises(ManagementReadBusyError) as captured:
        await module.run_management_read("read", lambda: None)
    assert captured.value.code == "MANAGEMENT_READ_QUEUE_TIMEOUT"
    assert captured.value.retry_after_seconds == 3
