"""HTTP regression tests for synchronous AIDP work on managed workers."""

import asyncio
import importlib
import threading

import httpx
import pytest
from fastapi import FastAPI
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    get_default_thread_manager,
    run_blocking,
    set_default_thread_manager,
)

from test.backend.app import test_tool_config_app as legacy_tool
from test.backend.app import test_agent_app as legacy_agent  # noqa: F401


agent_app = importlib.import_module("apps.agent_app")
tool_app = legacy_tool.tool_config_app
tool_service = importlib.import_module(tool_app.validate_tool_impl.__module__)


@pytest.mark.parametrize("boundary", ["capabilities", "search", "update", "validate"])
@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.asyncio
async def test_unrelated_http_request_returns_while_aidp_work_waits(boundary, fails, monkeypatch, mocker):
    previous_manager = get_default_thread_manager()
    lane = "model-tool-io" if boundary == "validate" else "control-io"
    manager = ThreadManager("aidp-http-test", {lane: LanePolicy(lane, 1, 0)})
    manager.start()
    set_default_thread_manager(manager)
    entered = threading.Event()
    release = threading.Event()
    worker_ids = []
    result = {"status": "success", "data": {"available": True}}

    def slow_service(*args, **kwargs):
        worker_ids.append(threading.get_ident())
        entered.set()
        assert release.wait(3), "AIDP work was never released"
        if fails:
            raise RuntimeError("AIDP unavailable")
        return result

    app = FastAPI()
    app.include_router(agent_app.agent_config_router)
    app.include_router(tool_app.router)

    @app.get("/probe")
    async def probe():
        return {"responsive": True}

    for module in (agent_app, tool_app, tool_service):
        monkeypatch.setattr(module, "run_blocking", run_blocking)
    for module in (agent_app, tool_app):
        mocker.patch.object(module, "get_current_user_id", return_value=("user", "tenant"))

    if boundary == "capabilities":
        collaborator = mocker.patch.object(agent_app, "get_agent_knowledge_capabilities", side_effect=slow_service)
        method, path, body = "GET", "/agent/7/knowledge-capabilities", None
    elif boundary == "search":
        collaborator = mocker.patch.object(tool_app, "search_tool_info_impl", side_effect=slow_service)
        method, path, body = "POST", "/tool/search", {"agent_id": 7, "tool_id": 8}
    elif boundary == "update":
        collaborator = mocker.patch.object(tool_app, "update_tool_info_impl", side_effect=slow_service)
        method, path, body = "POST", "/tool/update", {
            "agent_id": 7, "tool_id": 8, "params": {"knowledge_base_ids": ["1"]}, "enabled": True,
        }
    else:
        collaborator = mocker.patch.object(tool_service, "_validate_local_tool", side_effect=slow_service)
        method, path, body = "POST", "/tool/validate", {
            "name": "knowledge_base_search", "source": "local", "inputs": {"query": "hello"}, "params": {},
        }

    pending = None
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            pending = asyncio.create_task(client.request(method, path, json=body))
            for _ in range(100):
                if entered.is_set() or pending.done():
                    break
                await asyncio.sleep(0.005)
            assert entered.is_set(), await pending if pending.done() else "Worker did not start"
            assert not pending.done(), "The event loop was blocked until the worker timed out"
            probe_response = await asyncio.wait_for(client.get("/probe"), timeout=0.5)
            assert probe_response.status_code == 200
            assert probe_response.json() == {"responsive": True}
            assert not pending.done()
            assert worker_ids == [worker_ids[0]] and worker_ids[0] != threading.get_ident()
            snapshot = manager.snapshot()
            assert snapshot.active_count == 1
            assert snapshot.executions[0].lane == lane
            release.set()
            response = await asyncio.wait_for(pending, timeout=2)
            assert response.status_code == (500 if fails else 200)
            if fails:
                expected_detail = {
                    "capabilities": "Failed to resolve agent knowledge capabilities.",
                    "search": "Failed to search tool info",
                    "update": "Failed to update tool",
                    "validate": "AIDP unavailable",
                }
                assert response.json() == {"detail": expected_detail[boundary]}
            elif boundary == "capabilities":
                assert response.json()["data"] == result
            else:
                assert response.json() == result
            collaborator.assert_called_once()
            if boundary == "search":
                assert collaborator.call_args.args == (7, 8, "tenant", "user")
            elif boundary == "update":
                request, tenant_id, user_id = collaborator.call_args.args
                assert (request.agent_id, request.tool_id, tenant_id, user_id) == (7, 8, "tenant", "user")
                assert request.params == body["params"]
            elif boundary == "validate":
                assert collaborator.call_args.args == (body["name"], body["inputs"], {}, "tenant", "user")
            else:
                assert collaborator.call_args.args == ()
                assert collaborator.call_args.kwargs == {
                    "agent_id": 7, "tenant_id": "tenant", "version_no": None, "user_id": "user",
                }
            assert manager.snapshot().active_count == 0
    finally:
        release.set()
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        clear_default_thread_manager(manager)
        if previous_manager is not None:
            set_default_thread_manager(previous_manager)
        await manager.shutdown(timeout=3)
