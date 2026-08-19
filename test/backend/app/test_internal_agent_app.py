"""Tests for Runtime-only Agent delegation endpoints."""

import sys
from types import ModuleType
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from apps import internal_agent_app
from apps.internal_agent_app import InternalAgentRunRequest, router
from consts.error_code import ErrorCode
from consts.exceptions import AppException, ForbiddenError


app = FastAPI()
app.include_router(router)


def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://runtime.test",
    )


def _run_payload(**overrides):
    payload = {
        "agent_request": {
            "query": "hello",
            "conversation_id": 42,
            "agent_id": 7,
            "history": [],
            "is_debug": False,
        },
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "runtime_scope_id": None,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_internal_agent_lazy_helpers_delegate_to_agent_service(monkeypatch):
    agent_service = ModuleType("services.agent_service")
    agent_service.run_agent_stream = AsyncMock(return_value="stream-response")
    agent_service.stop_agent_tasks = lambda conversation_id, user_id: {
        "conversation_id": conversation_id,
        "user_id": user_id,
    }
    monkeypatch.setitem(sys.modules, "services.agent_service", agent_service)

    run_result = await internal_agent_app._run_agent_stream(marker=True)
    stop_result = internal_agent_app._stop_agent_tasks("a2a:task-1", "user-1")

    assert run_result == "stream-response"
    agent_service.run_agent_stream.assert_awaited_once_with(marker=True)
    assert stop_result == {"conversation_id": "a2a:task-1", "user_id": "user-1"}


@pytest.mark.asyncio
async def test_internal_agent_run_uses_explicit_identity_and_request_id(mocker):
    async def stream():
        yield b'data: {"type":"final_answer","content":"done"}\n\n'

    run_agent = mocker.patch(
        "apps.internal_agent_app._run_agent_stream",
        new_callable=AsyncMock,
        return_value=StreamingResponse(stream(), media_type="text/event-stream"),
    )

    async with _client() as client:
        response = await client.post(
            "/internal/agent/run",
            json=_run_payload(runtime_scope_id="a2a:task-1"),
            headers={"X-Request-Id": "req-1"},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "req-1"
    assert "final_answer" in response.text
    kwargs = run_agent.await_args.kwargs
    assert kwargs["user_id"] == "user-1"
    assert kwargs["tenant_id"] == "tenant-1"
    assert kwargs["runtime_scope_id"] == "a2a:task-1"
    assert kwargs["authorization"] is None
    assert kwargs["http_request"] is None
    assert kwargs["agent_request"].conversation_id == 42


@pytest.mark.asyncio
async def test_internal_agent_run_sanitizes_unexpected_failures(mocker):
    mocker.patch(
        "apps.internal_agent_app._run_agent_stream",
        new_callable=AsyncMock,
        side_effect=RuntimeError("private failure"),
    )

    async with _client() as client:
        response = await client.post("/internal/agent/run", json=_run_payload())

    assert response.status_code == 500
    assert response.json() == {"detail": "Agent run error."}


@pytest.mark.asyncio
async def test_internal_agent_run_maps_forbidden_error(mocker):
    mocker.patch(
        "apps.internal_agent_app._run_agent_stream",
        new_callable=AsyncMock,
        side_effect=ForbiddenError("access denied"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await internal_agent_app.internal_agent_run(
            InternalAgentRunRequest.model_validate(_run_payload())
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "access denied"


@pytest.mark.parametrize(
    "error",
    [
        AppException(ErrorCode.COMMON_VALIDATION_ERROR, "invalid request"),
        HTTPException(status_code=409, detail="conflict"),
    ],
)
@pytest.mark.asyncio
async def test_internal_agent_run_preserves_known_application_errors(mocker, error):
    mocker.patch(
        "apps.internal_agent_app._run_agent_stream",
        new_callable=AsyncMock,
        side_effect=error,
    )

    with pytest.raises(type(error)) as exc_info:
        await internal_agent_app.internal_agent_run(
            InternalAgentRunRequest.model_validate(_run_payload())
        )

    assert exc_info.value is error


@pytest.mark.asyncio
async def test_internal_agent_endpoints_do_not_fabricate_request_id_header(mocker):
    async def stream():
        yield b'data: {"type":"final_answer","content":"done"}\n\n'

    mocker.patch(
        "apps.internal_agent_app._run_agent_stream",
        new_callable=AsyncMock,
        return_value=StreamingResponse(stream(), media_type="text/event-stream"),
    )
    mocker.patch(
        "apps.internal_agent_app._stop_agent_tasks",
        return_value={"status": "success"},
    )

    async with _client() as client:
        run_response = await client.post("/internal/agent/run", json=_run_payload())
        stop_response = await client.post(
            "/internal/agent/stop",
            json={"conversation_id": 42, "user_id": "user-1"},
        )

    assert run_response.status_code == 200
    assert stop_response.status_code == 200
    assert "X-Request-Id" not in run_response.headers
    assert "X-Request-Id" not in stop_response.headers


@pytest.mark.parametrize("conversation_id", [42, "a2a:task-1"])
@pytest.mark.asyncio
async def test_internal_agent_stop_supports_conversation_and_a2a_scopes(mocker, conversation_id):
    stop_agent = mocker.patch(
        "apps.internal_agent_app._stop_agent_tasks",
        return_value={"status": "success", "message": "stopped"},
    )

    async with _client() as client:
        response = await client.post(
            "/internal/agent/stop",
            json={"conversation_id": conversation_id, "user_id": "user-1"},
            headers={"X-Request-Id": "req-stop"},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "req-stop"
    stop_agent.assert_called_once_with(conversation_id, "user-1")


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/internal/agent/run", _run_payload(user_id="   ")),
        ("/internal/agent/run", _run_payload(unexpected=True)),
        ("/internal/agent/run", _run_payload(agent_request={"query": "hello", "unexpected": True})),
        ("/internal/agent/run", _run_payload(runtime_scope_id=" ")),
        ("/internal/agent/run", _run_payload(user_id=123)),
        ("/internal/agent/stop", {"conversation_id": " ", "user_id": "user-1"}),
        ("/internal/agent/stop", {"conversation_id": 1.5, "user_id": "user-1"}),
        ("/internal/agent/stop", {"conversation_id": 1, "user_id": " ", "unexpected": True}),
    ],
)
@pytest.mark.asyncio
async def test_internal_agent_endpoints_reject_invalid_payloads(path, payload):
    async with _client() as client:
        response = await client.post(path, json=payload)

    assert response.status_code == 422


def test_internal_agent_routes_are_hidden_from_openapi():
    assert "/internal/agent/run" not in app.openapi()["paths"]
    assert "/internal/agent/stop" not in app.openapi()["paths"]
