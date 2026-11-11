# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Move old saved-user Northbound starts through signed Management preparation."""

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from backend.http.server.app_factory import create_app
from contracts.agentos import CompatibilityConversationRun
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError
from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.agent_admission import AdmissionClaim, AdmissionScopeError
from management.api.agent import compatibility_dispatch
from management.db.conversation.prepared_turn import PreparedTurnConflict, SavedUserTurn
from management.services.agent import conversation_submission, prepared_turn, runtime_client
from runtime.agentos import admission, management_dispatch
from runtime.agentos.compatibility import create_compatibility_router
from runtime.agentos.middleware import AgentOSMiddleware
from runtime.api.agent import execution


@pytest.fixture
def boundary(mocker):
    mocker.patch.object(environment, "JWT_SECRET", "synthetic-saved-user-signing-key")

    async def inline(_task, function, *args, **kwargs):
        kwargs.pop("lane", None)
        kwargs.pop("owner", None)
        return function(*args, **kwargs)

    mocker.patch.object(runtime_client, "run_blocking", side_effect=inline)
    for unit in (conversation_submission, admission):
        mocker.patch.object(unit, "_control_io", side_effect=inline)
        mocker.patch.object(unit, "conversation_belongs_to", return_value=True)
    source = mocker.patch.object(prepared_turn.store, "read_saved_user_turn", return_value=SavedUserTurn(23, 0, "CHAT"))
    claim = mocker.patch.object(conversation_submission, "claim_conversation_run", return_value=AdmissionClaim(
        "a" * 32, "pending", None, False, True,
    ))
    mocker.patch.object(admission, "authorize_conversation_dispatch", return_value=True)
    mocker.patch.object(prepared_turn, "find_pending_turn", new=AsyncMock(return_value=None))
    legacy = mocker.patch.object(execution, "run_legacy_agent_stream", new=AsyncMock(return_value=StreamingResponse(
        iter([b"data: legacy\n\n"]), headers={"conversation_id": "42"},
    )))
    prepare = mocker.patch.object(prepared_turn, "start_turn", new=AsyncMock(return_value=StreamingResponse(
        iter([b"data: prepared\n\n"]), headers={"conversation_id": "42"},
    )))
    runtime = create_app(enable_monitoring=False)
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(create_compatibility_router(
        execution.run_agentos_compatibility, None, conversation_run=execution.run_agentos_conversation,
    ))
    manager = create_app(enable_monitoring=False)
    manager.include_router(compatibility_dispatch.router)
    run_client = AgentOSClient("http://runtime", lambda **kwargs: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime), **kwargs,
    ))
    manager_client = AgentOSClient("http://management", lambda **kwargs: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=manager), **kwargs,
    ))
    mocker.patch.object(management_dispatch, "management_client", return_value=manager_client)
    mocker.patch.object(runtime_client, "_agentos_client", return_value=run_client)
    return run_client, source, claim, prepare, legacy


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("history_count", [0, 2])
async def test_raw_northbound_reuses_saved_source_and_only_executes_once(boundary, fallback, history_count):
    client, source, claim, prepare, legacy = boundary
    source.return_value = SavedUserTurn(23, history_count * 2, "CHAT")
    if fallback:
        prepare.return_value = None
    response = await client.run({
        "query": "hello", "agent_id": 7, "conversation_id": 42, "is_debug": False,
        "history": [{"role": role, "content": "previous"} for _ in range(history_count) for role in ("user", "assistant")],
    }, "actor", "tenant")

    assert response.status_code == 200 and response.headers["conversation_id"] == "42"
    assert b"".join([part async for part in response.body_iterator]) == (
        b"data: legacy\n\n" if fallback else b"data: prepared\n\n"
    )
    source.assert_called_once_with(42, "actor", "tenant", history_count * 2, "hello", None)
    claim.assert_called_once()
    payload = prepare.await_args.args[0]
    assert payload.user_message == "saved" and payload.idempotency_key == "saved-message-23"
    assert payload.claimed_run_id == "a" * 32
    assert prepare.await_args.kwargs["saved_user"] == source.return_value
    assert prepare.await_args.kwargs["include_journal_controls"] is False
    if fallback:
        legacy.assert_awaited_once()
        assert legacy.await_args.kwargs["skip_user_save"] is True
        assert legacy.await_args.kwargs["agent_request"]._projection_run_id == "a" * 32
    else:
        legacy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,status", [(AdmissionScopeError, 404), (PreparedTurnConflict, 409)])
async def test_saved_source_rejection_cannot_claim_prepare_or_execute(boundary, failure, status):
    client, source, claim, prepare, legacy = boundary
    source.side_effect = failure
    response = await client.run({
        "query": "hello", "agent_id": 7, "conversation_id": 42, "is_debug": False,
    }, "actor", "tenant")
    assert response.status_code == status
    assert b"AGENTOS_RUN_" in b"".join([part async for part in response.body_iterator])
    claim.assert_not_called()
    prepare.assert_not_awaited()
    legacy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("conversation_id,is_debug", [(None, False), (0, False), (42, True)])
async def test_invalid_saved_source_mode_never_reads_claims_or_executes(boundary, conversation_id, is_debug):
    client, source, claim, prepare, legacy = boundary
    response = await client.run_conversation(CompatibilityConversationRun(
        request={"query": "hello", "agent_id": 7, "conversation_id": conversation_id, "is_debug": is_debug},
        user_message="saved",
    ), "actor", "tenant")
    assert response.status_code == 422
    assert b"AGENTOS_INVALID_SAVED_USER_REQUEST" in b"".join([part async for part in response.body_iterator])
    source.assert_not_called()
    claim.assert_not_called()
    prepare.assert_not_awaited()
    legacy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,status", [(RuntimeServiceTimeoutError, 504), (RuntimeServiceUnavailableError, 503)])
async def test_raw_saved_handoff_failure_does_not_execute_locally(mocker, failure, status):
    forward = mocker.patch.object(execution, "dispatch_saved_start", new=AsyncMock(side_effect=failure("unavailable")))
    legacy = mocker.patch.object(execution, "run_legacy_agent_stream", new=AsyncMock())
    with pytest.raises(HTTPException) as rejected:
        await execution.run_agentos_compatibility(
            {"query": "hello", "agent_id": 7, "conversation_id": 42, "is_debug": False},
            ServicePrincipal("actor", "tenant"),
        )
    assert rejected.value.status_code == status
    forward.assert_awaited_once()
    legacy.assert_not_awaited()
