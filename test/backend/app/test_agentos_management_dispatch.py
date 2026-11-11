# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException, Request
from starlette.responses import StreamingResponse

from backend.http.server.app_factory import create_app
from contracts.agent import AgentRequest
from contracts.agentos import CompatibilityConversationRun, ManagementOperation
from contracts.constants import environment
from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal, sign_call
from management.api.agent import compatibility_dispatch
from runtime.agentos import management_dispatch


@pytest.fixture
def management_endpoint(mocker):
    mocker.patch.object(environment, "JWT_SECRET", "synthetic-dispatch-signing-key")
    app = create_app(enable_monitoring=False)
    app.include_router(compatibility_dispatch.router)
    return app


@pytest.mark.asyncio
async def test_runtime_public_start_uses_signed_management_dispatch(mocker, management_endpoint):
    from runtime.api.agent import execution

    async def response_body():
        yield b'data: {"type":"conversation_created","content":{"conversation_id":42}}\n\n'
        yield b'data: {"type":"done"}\n\n'

    forward = mocker.patch.object(compatibility_dispatch, "forward_conversation_run", new=AsyncMock(
        return_value=StreamingResponse(response_body(), headers={"conversation_id": "42"}),
    ))
    mocker.patch.object(execution, "_gateway_session_principal", return_value=ServicePrincipal("actor", "tenant"))
    legacy = mocker.patch.object(execution, "run_legacy_agent_stream", side_effect=AssertionError("legacy start"))
    transport = httpx.ASGITransport(app=management_endpoint)
    client = AgentOSClient("http://management", lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs))
    mocker.patch.object(management_dispatch, "management_client", return_value=client)
    request = AgentRequest(agent_id=7, query="hello", is_debug=False)
    context = Request({"type": "http", "headers": [
        (b"cookie", b"NEXT_LOCALE=en"), (b"x-user-timezone", b"Asia/Shanghai"),
    ]})

    response = await execution.agent_run_api(request, context, resume=False)

    assert response.status_code == 200 and response.headers["conversation_id"] == "42"
    body = b"".join([chunk async for chunk in response.body_iterator])
    assert b"conversation_created" in body and b'"done"' in body
    payload, user, tenant = forward.await_args.args
    assert (user, tenant, payload.language, payload.timezone) == ("actor", "tenant", "en", "Asia/Shanghai")
    assert payload.request["agent_id"] == 7 and payload.request["is_debug"] is False
    legacy.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected", [False, True])
@pytest.mark.parametrize("existing_claim", [False, True])
async def test_signed_claim_reaches_prepared_dispatch_with_original_run_id(
    mocker, management_endpoint, rejected, existing_claim,
):
    from management.services.agent import conversation_submission, prepared_turn, runtime_client
    from infrastructure.rdb.agent_admission import AdmissionClaim

    async def direct(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    mocker.patch.object(conversation_submission, "_control_io", side_effect=direct)
    mocker.patch.object(conversation_submission, "conversation_belongs_to", return_value=True)
    validate = mocker.patch.object(conversation_submission, "authorize_conversation_dispatch", return_value=True)
    run_id = "a" * 32
    claim = mocker.patch.object(conversation_submission, "claim_conversation_run", return_value=AdmissionClaim(
        run_id, "pending", None, False, True,
    ))
    mocker.patch.object(runtime_client, "_agentos_client", return_value=object())
    prepared = mocker.patch.object(prepared_turn, "start_turn", new=AsyncMock(
        return_value=StreamingResponse(iter([b"data: done\n\n"]), headers={"conversation_id": "42"}),
    ))
    if rejected:
        prepared.side_effect = HTTPException(
            status_code=422, detail={"code": "AGENTOS_RESOURCE_UNSUPPORTED"}, headers={"Retry-After": "7"},
        )
    payload = CompatibilityConversationRun(
        request={"query": "hello", "agent_id": 7, "conversation_id": 42, "is_debug": False},
        idempotency_key="claim", claimed_run_id=run_id if existing_claim else None,
    )
    client = AgentOSClient("http://management", lambda **kwargs: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=management_endpoint), **kwargs,
    ))

    response = await client.dispatch_conversation(payload, "actor", "tenant")

    assert response.status_code == (422 if rejected else 200)
    assert response.headers["X-AgentOS-Run-ID"] == run_id
    body = b"".join([chunk async for chunk in response.body_iterator])
    if rejected:
        assert response.headers["Retry-After"] == "7"
        assert b"AGENTOS_RESOURCE_UNSUPPORTED" in body
    else:
        assert body == b"data: done\n\n"
    assert prepared.await_args.args[0] == payload.model_copy(update={"claimed_run_id": run_id})
    assert prepared.await_args.args[2:4] == ("actor", "tenant")
    if existing_claim:
        assert validate.call_args.kwargs == {"consume": False}
        claim.assert_not_called()
    else:
        validate.assert_not_called()
        claim.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["unsigned", "modified_body", "wrong_operation", "query"])
async def test_management_dispatch_verifies_body_and_operation(mocker, management_endpoint, invalid):
    actor = ServicePrincipal("actor", "tenant")
    payload = CompatibilityConversationRun(request={"query": "hello", "agent_id": 7})
    body = payload.model_dump_json().encode()
    operation = ManagementOperation.CONVERSATION_DISPATCH
    token = sign_call(ManagementOperation.NL2AGENT_TOOL if invalid == "wrong_operation" else operation, body, actor)
    headers = {} if invalid == "unsigned" else {"Authorization": f"Bearer {token}"}
    if invalid == "modified_body":
        body = body.replace(b"hello", b"other")
    path = f"/api{operation.value}" + ("?extra=1" if invalid == "query" else "")
    forward = mocker.patch.object(compatibility_dispatch, "forward_conversation_run", new=AsyncMock())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=management_endpoint), base_url="http://management") as client:
        response = await client.post(path, content=body, headers=headers)
    assert response.status_code == (400 if invalid == "query" else 401)
    forward.assert_not_called()
