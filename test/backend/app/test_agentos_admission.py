# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.responses import Response

from contracts.agent import AgentRequest
from contracts.agentos import CompatibilityConversationRun
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.agent_admission import AdmissionClaim, AdmissionRequestConflict
from runtime.agentos import admission

RUN_ID = "a" * 32
ACTOR = ServicePrincipal("actor", "tenant")


def payload(query="question", **values):
    return CompatibilityConversationRun(
        request={"query": query, **values}, idempotency_key="client-123",
    )


@pytest.fixture
def claim_store(mocker):
    records = {}

    async def control_io(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    def claim(scope, fingerprint, user_id, tenant_id):
        assert (user_id, tenant_id) == (ACTOR.user_id, ACTOR.tenant_id)
        if scope not in records:
            records[scope] = (fingerprint, "pending", None)
            return AdmissionClaim(RUN_ID, "pending", None, False, True)
        expected, status, conversation_id = records[scope]
        if fingerprint != expected:
            raise AdmissionRequestConflict
        return AdmissionClaim(RUN_ID, status, conversation_id, bool(conversation_id), False)

    def bind(scope, run_id, user_id, tenant_id, *, conversation_id, journal_available):
        assert (run_id, user_id, tenant_id) == (RUN_ID, ACTOR.user_id, ACTOR.tenant_id)
        expected = records[scope][0]
        records[scope] = (expected, "admitted" if conversation_id is not None else "rejected", conversation_id)
        return True

    mocker.patch.object(admission, "_control_io", side_effect=control_io)
    mocker.patch.object(admission, "claim_conversation_run", side_effect=claim)
    mocker.patch.object(admission, "set_conversation_admission", side_effect=bind)
    mocker.patch.object(admission, "conversation_belongs_to", return_value=True)
    return bind


@pytest.mark.asyncio
async def test_concurrent_and_lost_response_retries_reuse_one_run(claim_store):
    sent = payload()
    first_request = AgentRequest.model_validate(sent.request)
    started = asyncio.Event()
    release = asyncio.Event()
    never_execute = AsyncMock()

    async def execute():
        assert first_request._projection_run_id == RUN_ID
        started.set()
        await release.wait()
        claim_store(first_request._run_admission_scope, RUN_ID, ACTOR.user_id, ACTOR.tenant_id,
                    conversation_id=42, journal_available=True)
        return Response(headers={"conversation_id": "42"})

    first = asyncio.create_task(admission.admit_conversation_run(sent, first_request, ACTOR, execute))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        pending = await admission.admit_conversation_run(sent, AgentRequest(query="question"), ACTOR, never_execute)
        assert pending.status_code == 202
        assert pending.headers["X-AgentOS-Run-ID"] == RUN_ID
        assert json.loads(pending.body)["status"] == "pending"
    finally:
        release.set()
        original = await first
    assert original.headers["X-AgentOS-Run-ID"] == RUN_ID

    replay = await admission.admit_conversation_run(sent, AgentRequest(query="question"), ACTOR, never_execute)
    assert replay.status_code == 202 and replay.headers["conversation_id"] == "42"
    assert json.loads(replay.body) == {
        "run_id": RUN_ID, "status": "admitted", "conversation_id": 42, "journal_available": True,
    }
    admission.conversation_belongs_to.assert_called_once_with(42, user_id="actor", tenant_id="tenant")
    never_execute.assert_not_called()


@pytest.mark.asyncio
async def test_conflict_and_unauthorized_conversation_never_execute(claim_store):
    sent = payload()
    await admission.admit_conversation_run(
        sent, AgentRequest(query="question"), ACTOR, AsyncMock(return_value=Response()),
    )
    execute = AsyncMock()
    with pytest.raises(HTTPException) as conflict:
        await admission.admit_conversation_run(payload("changed"), AgentRequest(query="changed"), ACTOR, execute)
    assert conflict.value.status_code == 409

    admission.conversation_belongs_to.return_value = False
    with pytest.raises(HTTPException) as forbidden:
        await admission.admit_conversation_run(
            payload(conversation_id=42), AgentRequest(query="question", conversation_id=42), ACTOR, execute,
        )
    assert forbidden.value.status_code == 404
    execute.assert_not_called()


@pytest.mark.asyncio
async def test_known_rejection_is_retained_with_original_run_id(claim_store):
    sent = payload()
    execute = AsyncMock(side_effect=HTTPException(status_code=429, headers={"Retry-After": "7"}))
    with pytest.raises(HTTPException) as first:
        await admission.admit_conversation_run(sent, AgentRequest(query="question"), ACTOR, execute)
    assert first.value.headers["X-AgentOS-Run-ID"] == RUN_ID
    assert first.value.headers["Retry-After"] == "7"

    retry = await admission.admit_conversation_run(sent, AgentRequest(query="question"), ACTOR, execute)
    assert retry.status_code == 409
    assert json.loads(retry.body)["status"] == "rejected"
    assert retry.headers["X-AgentOS-Run-ID"] == RUN_ID
    execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_outcome_does_not_reacquire_or_launch_another_run(claim_store):
    sent = payload()
    execute = AsyncMock(side_effect=HTTPException(status_code=500))
    with pytest.raises(HTTPException) as first:
        await admission.admit_conversation_run(sent, AgentRequest(query="question"), ACTOR, execute)
    assert first.value.headers["X-AgentOS-Run-ID"] == RUN_ID

    retry = await admission.admit_conversation_run(sent, AgentRequest(query="question"), ACTOR, execute)
    assert retry.status_code == 202 and retry.headers["Retry-After"] == "1"
    assert json.loads(retry.body)["status"] == "pending"
    assert retry.headers["X-AgentOS-Run-ID"] == RUN_ID
    execute.assert_awaited_once()
