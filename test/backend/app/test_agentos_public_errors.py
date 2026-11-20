# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management preserves the public error contract after Runtime ingress retirement."""

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError
from management.api.agent import conversation_run


@pytest.mark.asyncio
@pytest.mark.parametrize("status,headers,content", [
    (429, {"Retry-After": "1", "content-type": "application/json"},
     b'{"code":"RUNTIME_CAPACITY_FULL","message":"Agent runtime is at capacity.","retryable":true}'),
    (429, {"Retry-After": "30", "content-type": "application/json"},
     b'{"code":"RUNTIME_QUEUE_TIMEOUT","message":"Agent runtime queue wait timed out.","retryable":true}'),
    (403, {"content-type": "application/json"}, b'{"code":"FORBIDDEN"}'),
    (404, {"content-type": "application/json"}, b'{"code":"AGENTOS_RUN_NOT_FOUND"}'),
    (409, {"content-type": "application/json"}, b'{"code":"AGENTOS_RUN_ALREADY_ACTIVE"}'),
    (422, {"content-type": "application/json"}, b'{"code":"AGENTOS_INVALID_REQUEST"}'),
])
@pytest.mark.parametrize("operation", ["run", "stop"])
async def test_management_preserves_upstream_errors(monkeypatch, status, headers, content, operation):
    app = FastAPI()
    app.include_router(conversation_run.router)
    monkeypatch.setattr(conversation_run, "get_current_user_id", lambda _: ("owner", "tenant"))
    forward = AsyncMock(side_effect=RuntimeUpstreamError(status, content, headers))
    monkeypatch.setattr(conversation_run, "forward_conversation_run" if operation == "run" else "forward_scoped_stop", forward)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        response = (await client.post("/agent/run", json={"agent_id": 7, "query": "fixture"}) if operation == "run" else
                    await client.get("/agent/stop/" + "a" * 32))
    assert response.status_code == status and response.content == content
    for key, value in headers.items():
        assert response.headers[key] == value
    assert forward.await_args.args[-2:] == ("owner", "tenant")


@pytest.mark.asyncio
@pytest.mark.parametrize("error,status", [(RuntimeServiceTimeoutError("private endpoint"), 504),
                                          (RuntimeServiceUnavailableError("private endpoint"), 503)])
async def test_management_maps_transport_failures_without_private_details(monkeypatch, error, status):
    app = FastAPI()
    app.include_router(conversation_run.router)
    monkeypatch.setattr(conversation_run, "get_current_user_id", lambda _: ("owner", "tenant"))
    monkeypatch.setattr(conversation_run, "forward_conversation_run", AsyncMock(side_effect=error))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        response = await client.post("/agent/run", json={"agent_id": 7, "query": "fixture"})
    assert response.status_code == status
    assert "private endpoint" not in response.text
