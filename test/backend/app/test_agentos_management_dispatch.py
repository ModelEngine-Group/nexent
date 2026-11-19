# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The public start retains the Management claim and signs only prepared Runtime input."""

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from starlette.responses import StreamingResponse

from contracts.agentos import AgentOperation, AgentRunReference
from contracts.constants import environment
from infrastructure.agentos_identity import ServicePrincipal, sign_call
from infrastructure.rdb.agent_admission import AdmissionClaim
from management.services.agent import conversation_submission, prepared_turn, runtime_client
from runtime.agentos import prepared_run
from runtime.agentos.middleware import AgentOSMiddleware
from test.backend.app.test_agentos_prepared_run import payload
from test.backend.app.test_agentos_raw_handoff import public_client


RUN_ID = "a" * 32
ACTOR = ServicePrincipal("actor", "tenant")


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected", [False, True])
async def test_public_claim_reaches_preparation_once_and_retains_id(public_client, mocker, rejected):
    client, _ = public_client

    async def direct(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    mocker.patch.object(conversation_submission, "_control_io", side_effect=direct)
    mocker.patch.object(conversation_submission, "conversation_belongs_to", return_value=True)
    claim = mocker.patch.object(conversation_submission, "claim_conversation_run", side_effect=[
        AdmissionClaim(RUN_ID, "pending", None, False, True),
        AdmissionClaim(RUN_ID, "pending", None, False, False),
    ])
    preclaimed = mocker.patch.object(conversation_submission, "authorize_conversation_dispatch")
    transport = mocker.patch.object(runtime_client, "_agentos_client").return_value
    prepare = mocker.patch.object(prepared_turn, "start_turn", return_value=StreamingResponse(
        iter([b"data: done\n\n"]), headers={"conversation_id": "42"},
    ))
    if rejected:
        prepare.side_effect = HTTPException(
            status_code=422, detail={"code": "AGENTOS_RESOURCE_UNSUPPORTED"}, headers={"Retry-After": "7"},
        )
    request = {"query": "hello", "agent_id": 7, "conversation_id": 42, "is_debug": False}
    headers = {"Idempotency-Key": "claim", "X-User-Timezone": "Asia/Shanghai", "Cookie": "NEXT_LOCALE=en"}

    first = await client.post("/api/agent/run", json=request, headers=headers)
    retry = await client.post("/api/agent/run", json=request, headers=headers)

    assert first.status_code == (422 if rejected else 200)
    if rejected:
        assert first.json() == {"message": {"code": "AGENTOS_RESOURCE_UNSUPPORTED"}}
        assert first.headers["Retry-After"] == "7"
    else:
        assert first.content == b"data: done\n\n"
    assert first.headers["X-AgentOS-Run-ID"] == retry.headers["X-AgentOS-Run-ID"] == RUN_ID
    assert retry.status_code == 202 and retry.json()["status"] == "pending"
    prepare.assert_awaited_once()
    command, _, user, tenant, agentos = prepare.await_args.args
    assert (user, tenant, agentos) == (ACTOR.user_id, ACTOR.tenant_id, transport)
    assert command.claimed_run_id == RUN_ID
    assert (command.request, command.language, command.timezone) == (request, "en", "Asia/Shanghai")
    assert claim.call_count == 2 and claim.call_args_list[0] == claim.call_args_list[1]
    preclaimed.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["valid", "unsigned", "changed_body", "wrong_operation", "query"])
async def test_runtime_prepared_dispatch_verifies_body_and_operation(mocker, payload, condition):
    mocker.patch.object(environment, "JWT_SECRET", "synthetic-prepared-dispatch-signing-key")
    app = FastAPI()
    app.add_middleware(AgentOSMiddleware)
    app.include_router(prepared_run.create_prepared_run_router())
    admission = mocker.patch.object(prepared_run, "start_prepared_run", new=AsyncMock(
        return_value=AgentRunReference(run_id=RUN_ID, conversation_id=42),
    ))
    body = payload.model_dump_json().encode()
    operation = AgentOperation.STOP if condition == "wrong_operation" else AgentOperation.RUN
    token = sign_call(operation, body, ACTOR)
    headers = {} if condition == "unsigned" else {"Authorization": f"Bearer {token}"}
    if condition == "changed_body":
        body = body.replace(b"question", b"modified")
    path = AgentOperation.RUN.value + ("?extra=1" if condition == "query" else "")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as client:
        response = await client.post(path, content=body, headers=headers)

    if condition == "valid":
        assert response.status_code == 202
        assert response.json() == {"run_id": RUN_ID, "conversation_id": 42}
        admission.assert_awaited_once_with(payload, ACTOR)
    else:
        assert response.status_code == (400 if condition == "query" else 401)
        admission.assert_not_awaited()
