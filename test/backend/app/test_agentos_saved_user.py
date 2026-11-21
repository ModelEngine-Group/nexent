# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind a prepared AgentOS run to its saved user message in Management."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from contracts.agentos import CompatibilityConversationRun
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, ValidationError
from infrastructure.rdb.agent_admission import AdmissionClaim, AdmissionScopeError
from management.db.conversation.prepared_turn import PreparedTurnConflict, SavedUserTurn
from management.services.agent import conversation_submission, prepared_turn, runtime_client


@pytest.fixture
def boundary(mocker):
    async def inline(_task, function, *args, **kwargs):
        kwargs.pop("lane", None)
        kwargs.pop("owner", None)
        return function(*args, **kwargs)

    mocker.patch.object(runtime_client, "run_blocking", side_effect=inline)
    mocker.patch.object(conversation_submission, "_control_io", side_effect=inline)
    mocker.patch.object(conversation_submission, "conversation_belongs_to", return_value=True)
    source = mocker.patch.object(prepared_turn.store, "read_saved_user_turn", return_value=SavedUserTurn(23, 0, "CHAT"))
    claim = mocker.patch.object(conversation_submission, "claim_conversation_run", return_value=AdmissionClaim(
        "a" * 32, "pending", None, False, True,
    ))
    mocker.patch.object(prepared_turn, "find_pending_turn", return_value=None)
    prepare = mocker.patch.object(prepared_turn, "start_turn", return_value=StreamingResponse(
        iter([b"data: prepared\n\n"]), headers={"conversation_id": "42"},
    ))
    client = mocker.patch.object(runtime_client, "_agentos_client").return_value
    client.resume_legacy = AsyncMock()
    return source, claim, prepare, client


def command(**request_fields):
    return CompatibilityConversationRun(
        request={"query": "hello", "agent_id": 7, "conversation_id": 42, **request_fields},
        user_message="saved",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("history_count", [0, 2])
async def test_saved_source_is_reused_by_prepared_turn(boundary, history_count):
    source, claim, prepare, client = boundary
    source.return_value = SavedUserTurn(23, history_count * 2, "CHAT")
    history = [{"role": role, "content": "previous"}
               for _ in range(history_count) for role in ("user", "assistant")]

    response = await runtime_client.forward_conversation_run(command(history=history), "actor", "tenant")

    assert response.status_code == 200 and response.headers["conversation_id"] == "42"
    assert b"".join([part async for part in response.body_iterator]) == b"data: prepared\n\n"
    source.assert_called_once_with(42, "actor", "tenant", history_count * 2, "hello", None)
    claim.assert_called_once()
    payload, request, user, tenant, transport = prepare.await_args.args
    assert (user, tenant, transport) == ("actor", "tenant", client)
    assert request.conversation_id == 42
    assert payload.user_message == "saved" and payload.idempotency_key == "saved-message-23"
    assert payload.claimed_run_id == "a" * 32
    assert prepare.await_args.kwargs["saved_user"] == source.return_value
    assert prepare.await_args.kwargs["include_journal_controls"] is False
    client.resume_legacy.assert_not_awaited()


@pytest.mark.asyncio
async def test_unsupported_saved_source_is_not_reopened_as_legacy(boundary):
    _, _, prepare, client = boundary
    prepare.return_value = None
    with pytest.raises(ValidationError, match="could not be prepared"):
        await runtime_client.forward_conversation_run(command(), "actor", "tenant")
    prepare.assert_awaited_once()
    client.resume_legacy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,status", [(AdmissionScopeError, 404), (PreparedTurnConflict, 409)])
async def test_saved_source_rejection_cannot_claim_or_prepare(boundary, failure, status):
    source, claim, prepare, client = boundary
    source.side_effect = failure
    with pytest.raises(HTTPException) as response:
        await runtime_client.forward_conversation_run(command(), "actor", "tenant")
    assert response.value.status_code == status
    assert response.value.detail["code"].startswith("AGENTOS_RUN_")
    claim.assert_not_called()
    prepare.assert_not_awaited()
    client.resume_legacy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("conversation_id,is_debug", [(None, False), (0, False), (42, True)])
async def test_invalid_saved_source_mode_never_reads_claims_or_prepares(boundary, conversation_id, is_debug):
    source, claim, prepare, client = boundary
    with pytest.raises(HTTPException) as response:
        await runtime_client.forward_conversation_run(
            command(conversation_id=conversation_id, is_debug=is_debug), "actor", "tenant",
        )
    assert response.value.status_code == 422
    assert response.value.detail == {"code": "AGENTOS_INVALID_SAVED_USER_REQUEST"}
    source.assert_not_called()
    claim.assert_not_called()
    prepare.assert_not_awaited()
    client.resume_legacy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeServiceTimeoutError, RuntimeServiceUnavailableError])
async def test_saved_start_transport_failure_does_not_retry_as_legacy(boundary, failure):
    _, claim, prepare, client = boundary
    prepare.side_effect = failure("unavailable")
    with pytest.raises(failure):
        await runtime_client.forward_conversation_run(command(), "actor", "tenant")
    claim.assert_called_once()
    prepare.assert_awaited_once()
    client.resume_legacy.assert_not_awaited()
