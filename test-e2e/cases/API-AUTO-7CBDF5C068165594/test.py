# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""HTTP overload responses at the conversation and Northbound facades."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from contracts.authentication import NorthboundContext
from contracts.errors.exceptions import RuntimeQueueTimeoutError, RuntimeUpstreamError
from management.api import northbound
from management.api.agent import conversation_run


@pytest.mark.stage("D2")
@pytest.mark.case_id("API-AUTO-7CBDF5C068165594")
@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/agent/run", "/nb/v1/chat/run"])
@pytest.mark.parametrize(
    ("code", "message", "retry_after"),
    [
        ("RUNTIME_CAPACITY_FULL", "Agent runtime is at capacity.", "1"),
        (
            "RUNTIME_QUEUE_TIMEOUT",
            "Agent runtime queue wait timed out.",
            str(RuntimeQueueTimeoutError(30).retry_after_seconds),
        ),
    ],
)
async def test_runtime_overload_error_contract(monkeypatch, path, code, message, retry_after):
    app = FastAPI()
    app.include_router(conversation_run.router)
    app.include_router(northbound.router)
    body = {"code": code, "message": message, "retryable": True}
    runtime = AsyncMock(
        side_effect=RuntimeUpstreamError(
            429, json.dumps(body).encode(), {"Content-Type": "application/json", "Retry-After": retry_after},
        ),
    )
    if path == "/agent/run":
        monkeypatch.setattr(conversation_run, "get_current_user_id", lambda _: ("test-user", "test-tenant"))
        monkeypatch.setattr(conversation_run, "forward_conversation_run", runtime)
        request = {"agent_id": 1, "query": "hello"}
    else:
        actor = NorthboundContext("test-request", "test-tenant", "test-user", "")
        monkeypatch.setattr(northbound, "_get_northbound_context", AsyncMock(return_value=actor))
        monkeypatch.setattr(northbound, "start_streaming_chat", runtime)
        request = {"agent_name": "test-agent", "query": "hello"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://testserver") as client:
        response = await client.post(path, json=request)

    runtime.assert_awaited_once()
    assert response.status_code == 429, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["Retry-After"] == retry_after
    assert response.json() == body
