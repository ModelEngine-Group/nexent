# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserve the original Northbound preparation boundary during handoff."""

from unittest.mock import AsyncMock

import httpx
import pytest
from starlette.responses import StreamingResponse

from contracts.agent import AgentRequest
from infrastructure.agentos_identity import ServicePrincipal
from runtime.api.agent import execution


@pytest.mark.asyncio
async def test_raw_debug_visits_management_with_original_request_before_local_preparation(mocker):
    response = StreamingResponse(iter([b"data: answer\n\n"]))
    dispatch = mocker.patch.object(execution, "dispatch_signed_start", new=AsyncMock(return_value=response))
    legacy = mocker.patch.object(execution, "run_legacy_agent_stream", side_effect=AssertionError("local business preparation"))
    request = AgentRequest(query="hello", agent_id=7, version_no=2, is_debug=True, model_id=11)
    result = await execution._execute_northbound_run(request, "user", "tenant")
    assert result is response
    payload, actor = dispatch.await_args.args
    assert payload.invocation == "northbound" and payload.request == request.model_dump(mode="json", exclude_unset=True)
    assert actor == ServicePrincipal("user", "tenant")
    legacy.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_raw_fallback_cannot_reenter_management(mocker):
    from contracts.agentos import CompatibilityConversationRun

    legacy = mocker.patch.object(execution, "run_legacy_agent_stream", new=AsyncMock(return_value=StreamingResponse(iter([]))))
    dispatch = mocker.patch.object(execution, "dispatch_signed_start", new=AsyncMock())
    payload = CompatibilityConversationRun(
        request={"query": "hello", "agent_id": 7, "is_debug": True},
        invocation="northbound", preparation="legacy",
    )
    await execution.run_agentos_conversation(payload, ServicePrincipal("user", "tenant"))
    legacy.assert_awaited_once()
    assert legacy.await_args.kwargs["skip_user_save"] is True
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,status,detail", [
    ("unauthorized", 401, "original"), ("forbidden", 403, "original"),
    ("validation", 422, "original"), ("model", 404, {"code": "model_not_available"}),
    ("unexpected", 500, "Agent run error."),
    ("upstream", 429, {"code": "RUNTIME_CAPACITY_FULL"}),
])
async def test_management_raw_callback_preserves_original_error_mapping(mocker, failure, status, detail):
    from backend.http.server.app_factory import create_app
    from contracts.agentos import CompatibilityConversationRun, ManagementOperation
    from contracts.constants import environment
    from contracts.errors.exceptions import ForbiddenError, RunModelControlsError, RuntimeUpstreamError, UnauthorizedError, ValidationError
    from infrastructure.agentos_identity import sign_call
    from management.api.agent import compatibility_dispatch

    errors = {
        "unauthorized": UnauthorizedError("original"), "forbidden": ForbiddenError("original"),
        "validation": ValidationError("original"), "model": RunModelControlsError("model_not_available"),
        "unexpected": RuntimeError("private failure"),
        "upstream": RuntimeUpstreamError(429, b'{"code":"RUNTIME_CAPACITY_FULL"}', {
            "Content-Type": "application/json", "Retry-After": "3",
        }),
    }
    mocker.patch.object(environment, "JWT_SECRET", "synthetic-raw-callback-key")
    mocker.patch.object(compatibility_dispatch, "forward_raw_run", new=AsyncMock(side_effect=errors[failure]))
    payload = CompatibilityConversationRun(request={"query": "hello", "is_debug": True}, invocation="northbound")
    body = payload.model_dump_json().encode()
    operation = ManagementOperation.CONVERSATION_DISPATCH
    token = sign_call(operation, body, ServicePrincipal("user", "tenant"))
    app = create_app(enable_monitoring=False)
    app.include_router(compatibility_dispatch.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        response = await client.post("/api" + operation.value, content=body, headers={"Authorization": "Bearer " + token})
    assert response.status_code == status and response.json() == (detail if failure == "upstream" else {"message": detail})
    if failure == "upstream":
        assert response.headers["Retry-After"] == "3"
