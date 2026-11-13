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
@pytest.mark.parametrize("via_runtime", [False, True])
async def test_signed_claim_reaches_prepared_dispatch_with_original_run_id(
    mocker, management_endpoint, rejected, existing_claim, via_runtime,
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
        language="en", timezone="Asia/Shanghai",
    )
    management_client = AgentOSClient("http://management", lambda **kwargs: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=management_endpoint), **kwargs,
    ))
    if via_runtime:
        from runtime.agentos import admission
        from runtime.agentos.compatibility import create_compatibility_router
        from runtime.agentos.middleware import AgentOSMiddleware
        from runtime.api.agent import execution

        mocker.patch.object(management_dispatch, "management_client", return_value=management_client)
        mocker.patch.object(admission, "admit_conversation_run", side_effect=AssertionError("Runtime consumed claim"))
        mocker.patch.object(execution, "run_legacy_agent_stream", side_effect=AssertionError("Runtime prepared resources"))
        runtime = create_app(enable_monitoring=False)
        runtime.add_middleware(AgentOSMiddleware)
        runtime.include_router(create_compatibility_router(None, None, conversation_run=execution.run_agentos_conversation))
        client = AgentOSClient("http://runtime", lambda **kwargs: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), **kwargs,
        ))
        response = await client.run_conversation(payload, "actor", "tenant")
    else:
        response = await management_client.dispatch_conversation(payload, "actor", "tenant")

    assert response.status_code == (422 if rejected else 200)
    assert response.headers["X-AgentOS-Run-ID"] == run_id
    body = b"".join([chunk async for chunk in response.body_iterator])
    if rejected:
        assert response.headers["Retry-After"] == "7"
        assert b"AGENTOS_RESOURCE_UNSUPPORTED" in body
    else:
        assert body == b"data: done\n\n"
    expected = {"claimed_run_id": run_id}
    if via_runtime:
        expected["preparation"] = "management"
    assert prepared.await_args.args[0] == payload.model_copy(update=expected)
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


@pytest.mark.asyncio
async def test_signed_legacy_fallback_prepares_once_then_consumes_the_same_claim(mocker, management_endpoint):
    from infrastructure.rdb.agent_admission import conversation_request_fingerprint
    from management.services.agent import conversation_submission, prepared_turn, runtime_client
    from runtime.agentos import admission
    from runtime.agentos.compatibility import create_compatibility_router
    from runtime.agentos.middleware import AgentOSMiddleware
    from runtime.api.agent import execution

    async def direct(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    payload = CompatibilityConversationRun(
        request={"query": "hello", "agent_id": 7, "conversation_id": 42, "is_debug": False},
        idempotency_key="existing", claimed_run_id="a" * 32, language="en", timezone="Asia/Shanghai",
    )
    mocker.patch.object(conversation_submission, "_control_io", side_effect=direct)
    mocker.patch.object(admission, "_control_io", side_effect=direct)
    for unit in (conversation_submission, admission):
        mocker.patch.object(unit, "conversation_belongs_to", return_value=True)
    validate = mocker.patch.object(conversation_submission, "authorize_conversation_dispatch", return_value=True)
    consume = mocker.patch.object(admission, "authorize_conversation_dispatch", return_value=True)
    claim = mocker.patch.object(conversation_submission, "claim_conversation_run", side_effect=AssertionError("second claim"))
    prepare = mocker.patch.object(prepared_turn, "start_turn", new=AsyncMock(return_value=None))
    mocker.patch.object(prepared_turn, "find_pending_turn", new=AsyncMock(return_value=None))
    legacy = mocker.patch.object(execution, "run_legacy_agent_stream", new=AsyncMock(return_value=StreamingResponse(
        iter([b"data: legacy\n\n"]), headers={"conversation_id": "42"},
    )))
    runtime = create_app(enable_monitoring=False)
    runtime.add_middleware(AgentOSMiddleware)
    observed = []

    async def dispatch(request, actor):
        observed.append((request, actor))
        assert len(observed) <= 2, "conversation handoff looped"
        return await execution.run_agentos_conversation(request, actor)

    runtime.include_router(create_compatibility_router(None, None, conversation_run=dispatch))
    runtime_client_instance = AgentOSClient("http://runtime", lambda **kwargs: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime), **kwargs,
    ))
    management_client_instance = AgentOSClient("http://management", lambda **kwargs: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=management_endpoint), **kwargs,
    ))
    mocker.patch.object(runtime_client, "_agentos_client", return_value=runtime_client_instance)
    mocker.patch.object(management_dispatch, "management_client", return_value=management_client_instance)

    response = await runtime_client_instance.run_conversation(payload, "actor", "tenant")

    assert response.status_code == 200
    assert b"".join([chunk async for chunk in response.body_iterator]) == b"data: legacy\n\n"
    assert response.headers["X-AgentOS-Run-ID"] == payload.claimed_run_id
    assert [request.preparation for request, _ in observed] == [None, "legacy"]
    assert all(actor == ServicePrincipal("actor", "tenant") for _, actor in observed)
    assert all(request.request == payload.request and request.claimed_run_id == payload.claimed_run_id for request, _ in observed)
    assert prepare.await_args.args[0].preparation == "management"
    prepare.assert_awaited_once()
    legacy.assert_awaited_once()
    claim.assert_not_called()
    assert validate.call_args.args == consume.call_args.args
    assert validate.call_args.kwargs == {"consume": False} and consume.call_args.kwargs == {}
    expected = conversation_request_fingerprint({
        "request": payload.request, "resume": False, "language": "en", "timezone": "Asia/Shanghai",
    })
    assert consume.call_args.args[1] == expected
    assert "preparation" not in payload.model_dump() and "preparation" not in payload.model_dump_json()

    rejected = await management_client_instance.dispatch_conversation(
        payload.model_copy(update={"preparation": "legacy"}), "actor", "tenant",
    )
    assert rejected.status_code == 422
    assert b"AGENTOS_INVALID_PREPARATION_HANDOFF" in b"".join([chunk async for chunk in rejected.body_iterator])
    prepare.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,status", [("unavailable", 503), ("timeout", 504)])
async def test_signed_handoff_transport_failure_never_consumes_or_executes(mocker, failure, status):
    from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError
    from runtime.agentos import admission
    from runtime.api.agent import execution

    error = RuntimeServiceUnavailableError if failure == "unavailable" else RuntimeServiceTimeoutError
    forward = mocker.patch.object(execution, "dispatch_signed_start", new=AsyncMock(side_effect=error("unavailable")))
    consume = mocker.patch.object(admission, "admit_conversation_run", new=AsyncMock())
    legacy = mocker.patch.object(execution, "run_legacy_agent_stream", new=AsyncMock())
    payload = CompatibilityConversationRun(
        request={"query": "hello", "agent_id": 7}, idempotency_key="existing", claimed_run_id="a" * 32,
    )
    actor = ServicePrincipal("actor", "tenant")

    with pytest.raises(HTTPException) as rejected:
        await execution.run_agentos_conversation(payload, actor)

    assert rejected.value.status_code == status
    forward.assert_awaited_once_with(payload, actor)
    consume.assert_not_awaited()
    legacy.assert_not_awaited()
