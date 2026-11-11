# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserve the internal new-conversation path without a fabricated user row."""

import pytest

from contracts.agent import AgentRequest
from management.services.agent import prepared_turn, raw_execution, runtime_client
from .test_prepared_public_turn import ACTOR, PAYLOAD, REFERENCE, flow


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_users", [0, 4])
async def test_raw_new_turn_keeps_legacy_assistant_index_and_skips_user(flow, mocker, prior_users):
    operations, compile_snapshot, client, _ = flow
    mocker.patch.object(prepared_turn.store, "allocate_conversation_id", return_value=42)
    request = AgentRequest.model_validate({
        **PAYLOAD.request, "conversation_id": None,
        "history": [{"role": "user", "content": "earlier"} for _ in range(prior_users)],
    })
    response = await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, client, omitted_user=True)
    call = prepared_turn.store.stage_turn.call_args
    assert call.args[4] == prior_users * 2 and call.kwargs["omitted_user"] is True
    assert call.kwargs["initial_title"]
    assert compile_snapshot.await_args.kwargs["preserve_shared_reasoning"] is True
    assert compile_snapshot.await_args.kwargs["new_conversation"] is True
    assert operations == ["stage", "start", "confirm"]
    assert response.headers["conversation_id"] == "42"


@pytest.mark.asyncio
async def test_omitted_user_cannot_be_requested_for_an_existing_conversation(flow):
    operations, _, client, _ = flow
    with pytest.raises(ValueError):
        await prepared_turn.start_turn(PAYLOAD, AgentRequest.model_validate(PAYLOAD.request), *ACTOR, client, omitted_user=True)
    assert not operations
    client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("supported", [True, False])
async def test_raw_new_dispatch_uses_claimed_agentos_turn_or_one_original_fallback(mocker, supported):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from starlette.responses import StreamingResponse
    from contracts.agentos import CompatibilityConversationRun
    from infrastructure.agentos_identity import ServicePrincipal
    from management.services.agent import conversation_submission

    payload = CompatibilityConversationRun(request={"query": "hello", "agent_id": 7}, invocation="northbound")
    response = StreamingResponse(iter([]))
    start = mocker.patch.object(prepared_turn, "start_turn", return_value=response if supported else None)
    reject = mocker.patch.object(prepared_turn, "reject_unstaged_turn")
    debug = mocker.patch.object(raw_execution, "prepare_raw_debug", return_value=None)
    client = SimpleNamespace(run_conversation=AsyncMock(return_value=response))
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)

    async def claim(candidate, user, tenant, dispatch, **options):
        assert candidate.idempotency_key and options == {"include_claim_headers": False}
        return await dispatch(candidate.model_copy(update={"claimed_run_id": REFERENCE.run_id}), user, tenant)

    mocker.patch.object(conversation_submission, "submit_conversation", side_effect=claim)
    result = await raw_execution.forward_raw_run(payload, ServicePrincipal(*ACTOR))
    assert result is response
    assert start.await_args.kwargs == {"include_journal_controls": False, "omitted_user": True}
    assert start.await_args.args[0].claimed_run_id == REFERENCE.run_id
    debug.assert_not_awaited()
    if supported:
        client.run_conversation.assert_not_awaited()
        reject.assert_not_awaited()
        assert result.headers["Connection"] == "keep-alive"
    else:
        reject.assert_awaited_once()
        client.run_conversation.assert_awaited_once_with(payload.model_copy(update={"preparation": "legacy"}), *ACTOR)
