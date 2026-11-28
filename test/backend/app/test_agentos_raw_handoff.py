# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserve input and error contracts at the public Management run boundary."""

import httpx
import pytest
from starlette.responses import StreamingResponse

from backend.http.server.app_factory import create_app
from contracts.errors.exceptions import ForbiddenError, RunModelControlsError, UnauthorizedError, ValidationError
from management.api.agent import conversation_run
from management.services.agent import runtime_client
from management.services.agent.preparation import evaluation_snapshot


@pytest.fixture
async def public_client(mocker):
    identity = mocker.patch.object(conversation_run, "get_current_user_id", return_value=("actor", "tenant"))
    app = create_app(enable_monitoring=False)
    app.include_router(conversation_run.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://management",
    ) as client:
        yield client, identity


@pytest.mark.asyncio
async def test_debug_request_preserves_identity_locale_and_time_zone(public_client, mocker):
    client, identity = public_client
    mocker.patch.object(
        conversation_run, "forward_conversation_run",
        return_value=StreamingResponse(iter([b"data: answer\n\n"])),
    )
    request = {"query": "hello", "agent_id": 7, "version_no": 2, "is_debug": True, "model_id": 11}

    response = await client.post("/api/agent/run", json=request, headers={
        "Authorization": "Bearer session", "Cookie": "NEXT_LOCALE=en", "X-User-Timezone": "Asia/Shanghai",
    })

    assert response.status_code == 200
    assert response.content == b"data: answer\n\n"
    identity.assert_called_once_with("Bearer session")
    payload, user, tenant = conversation_run.forward_conversation_run.await_args.args
    assert (user, tenant, payload.language, payload.timezone) == ("actor", "tenant", "en", "Asia/Shanghai")
    assert payload.request == request


@pytest.mark.asyncio
async def test_unsupported_debug_returns_422_without_starting_runtime(public_client, mocker):
    client, _ = public_client
    prepare = mocker.patch.object(evaluation_snapshot, "prepare_debug_snapshot", return_value=None)
    transport = mocker.patch.object(runtime_client, "_agentos_client").return_value

    response = await client.post("/api/agent/run", json={"query": "hello", "agent_id": 7, "is_debug": True})

    assert response.status_code == 422
    assert response.json() == {"message": "Agent resources could not be prepared for AgentOS"}
    prepare.assert_awaited_once()
    assert transport.mock_calls == []


@pytest.mark.asyncio
async def test_debug_preserves_failing_child_context(public_client, mocker):
    client, _ = public_client
    mocker.patch.object(evaluation_snapshot, "prepare_debug_snapshot", side_effect=RunModelControlsError(
        "model_not_available", agent_id=48, agent_name="厨师助手", version_no=1,
    ))
    transport = mocker.patch.object(runtime_client, "_agentos_client").return_value
    response = await client.post("/api/agent/run", json={"query": "hello", "agent_id": 7, "is_debug": True})
    assert response.status_code == 404
    assert response.json() == {"message": {"code": "model_not_available", "details": {
        "agent_id": 48, "agent_name": "厨师助手", "version_no": 1,
    }}}
    assert transport.mock_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,status,detail", [
    (UnauthorizedError("private identity"), 401, "Unauthorized"),
    (ForbiddenError("Access denied"), 403, "Access denied"),
    (ValidationError("Invalid input"), 422, "Invalid input"),
    (RunModelControlsError("model_not_available"), 404, {"code": "model_not_available"}),
    (RunModelControlsError("model_not_available", agent_id=48, agent_name="厨师助手", version_no=1),
     404, {"code": "model_not_available", "details": {"agent_id": 48, "agent_name": "厨师助手", "version_no": 1}}),
    (RunModelControlsError("model_unavailable"), 409, {"code": "model_unavailable"}),
    (RunModelControlsError("model_type_invalid"), 400, {"code": "model_type_invalid"}),
    (RuntimeError("private failure"), 500, "Internal server error, please try again later."),
])
async def test_preparation_failure_maps_to_the_public_error_contract(public_client, mocker, failure, status, detail):
    client, _ = public_client
    mocker.patch.object(conversation_run, "forward_conversation_run", side_effect=failure)

    response = await client.post("/api/agent/run", json={"query": "hello", "agent_id": 7})

    assert response.status_code == status
    assert response.json() == {"message": detail}
