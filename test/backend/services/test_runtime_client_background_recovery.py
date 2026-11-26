# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Use only matching durable results when the background response is lost."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import Response

from contracts.agent import AgentRequest
from contracts.agentos import AgentRunLookup, CompatibilityConversationRun
from contracts.errors.exceptions import RuntimeUpstreamError
from management.db.automation import repository as runs
from management.db.conversation import repository as conversations
from infrastructure.rdb.agent_admission import AdmissionScopeError
from management.services.agent import background, prepared_turn, runtime_client

RUN_ID = "a" * 32


@pytest.mark.parametrize("outcome", ["receipt", "db-failure", "runtime-receipt", "foreign", "missing", "reject"])
async def test_background_recovery_keeps_original_scope_and_error(mocker, outcome):
    async def inline(_label, callback, *args, lane, owner, **kwargs):
        assert (lane, owner) == ("control-io", "management")
        return callback(*args, **kwargs)

    mocker.patch.object(runtime_client, "run_blocking", side_effect=inline)
    error = RuntimeUpstreamError(409 if outcome == "reject" else 503, b"", {})
    dispatch = mocker.patch.object(background, "dispatch_background", side_effect=error)
    read = mocker.patch.object(runs, "get_run_by_runtime_id", return_value={"projection_message_index": 3})
    if outcome == "db-failure":
        read.side_effect = SQLAlchemyError("database inaccessible")
    receipt = mocker.patch.object(conversations, "get_prepared_projection_receipt",
                                  return_value=(61, "completed") if outcome == "receipt" else None)
    inspect = AsyncMock(return_value=SimpleNamespace(
        run_id=RUN_ID, conversation_id=43 if outcome == "foreign" else 42, status="completed", assistant_message_id=62,
    ))
    if outcome == "missing":
        inspect.side_effect = RuntimeUpstreamError(404, b"", {})
    mocker.patch.object(runtime_client, "_agentos_client", return_value=SimpleNamespace(inspect_run=inspect))
    request = AgentRequest(query="question", conversation_id=42, agent_id=7)
    expected_id = {"receipt": 61, "runtime-receipt": 62, "db-failure": 62}.get(outcome)
    if expected_id is None:
        with pytest.raises(RuntimeUpstreamError) as failure:
            await runtime_client.forward_tracked_background(request, RUN_ID, "actor", "tenant")
        assert failure.value is error
    else:
        result = await runtime_client.forward_tracked_background(request, RUN_ID, "actor", "tenant")
        assert (result.run_id, result.conversation_id, result.assistant_message_id, result.chunks) == (RUN_ID, 42, expected_id, 0)

    payload, actor = dispatch.await_args.args
    assert payload.run_id == RUN_ID and actor.user_id == "actor" and actor.tenant_id == "tenant"
    if outcome in {"receipt", "reject"}:
        inspect.assert_not_awaited()
    else:
        inspect.assert_awaited_once_with(AgentRunLookup(run_id=RUN_ID, conversation_id=42), "actor", "tenant")
    if outcome == "reject":
        read.assert_not_called()
        receipt.assert_not_called()
    else:
        read.assert_called_once_with(RUN_ID, "tenant", "actor", conversation_id=42)


@pytest.mark.parametrize("error,expected,code", [
    (AdmissionScopeError, 404, "AGENTOS_RUN_NOT_FOUND"),
    (prepared_turn.store.PreparedTurnConflict, 409, "AGENTOS_RUN_ALREADY_ACTIVE"),
])
async def test_saved_user_admission_rejects_scope_or_changed_source(mocker, error, expected, code):
    source = mocker.patch.object(runtime_client, "run_blocking", side_effect=error)
    mocker.patch.object(runtime_client, "_agentos_client")
    submit = mocker.patch("management.services.agent.conversation_submission.submit_conversation")
    payload = CompatibilityConversationRun(
        request={"query": "question", "agent_id": 7, "conversation_id": 42}, user_message="saved",
    )
    with pytest.raises(HTTPException) as exc:
        await runtime_client.forward_conversation_run(payload, "actor", "tenant")
    assert (exc.value.status_code, exc.value.detail["code"]) == (expected, code)
    assert source.await_args.args[2:] == (42, "actor", "tenant", 0, "question", None)
    submit.assert_not_awaited()


async def test_northbound_closes_a_conflict_response_before_rendering_busy_stream(mocker):
    cleanup = AsyncMock()
    upstream = Response(status_code=409, headers={"X-Stream-Status": "conflict"}, background=cleanup)
    forward = mocker.patch.object(runtime_client, "forward_conversation_run", return_value=upstream)
    request = AgentRequest(query="question", agent_id=7, conversation_id=42)
    response = await runtime_client.forward_northbound_run(request, "actor", "tenant", final_answer_mode="delta")
    cleanup.assert_awaited_once()
    assert forward.await_args.kwargs == {"northbound": True, "complete_answer": False}
    assert response.status_code == 200
    assert response is not upstream
