# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Preserve the native presentation and propagate Northbound mode into prepared turns."""

import pytest
from starlette.responses import StreamingResponse

from contracts.agent import AgentRequest
from contracts.agentos import CompatibilityConversationRun
from management.services.agent import conversation_submission, prepared_turn, runtime_client


@pytest.fixture
def prepare(mocker):
    async def submit(command, user, tenant, dispatch, **_headers):
        claimed = command.model_copy(update={"claimed_run_id": "a" * 32})
        return await dispatch(claimed, user, tenant)

    mocker.patch.object(runtime_client, "_agentos_client")
    mocker.patch.object(conversation_submission, "submit_conversation", side_effect=submit)
    return mocker.patch.object(prepared_turn, "start_turn", return_value=StreamingResponse(iter(())))


@pytest.mark.asyncio
@pytest.mark.parametrize("options,complete", [({}, True), ({"final_answer_mode": "complete"}, True),
                                             ({"final_answer_mode": "delta"}, False)])
async def test_northbound_chooses_presentation_without_changing_the_prepared_request(prepare, options, complete):
    request = AgentRequest(agent_id=7, query="hello", conversation_id=42)

    response = await runtime_client.forward_northbound_run(request, "user", "tenant", **options)

    assert response is prepare.return_value
    prepare.assert_awaited_once()
    command, parsed, user, tenant, _ = prepare.await_args.args
    assert command.request == request.model_dump(mode="json")
    assert parsed == request and (user, tenant) == ("user", "tenant")
    assert prepare.await_args.kwargs.get("complete_answer", False) is complete
    assert prepare.await_args.kwargs["include_journal_controls"] is False


@pytest.mark.asyncio
async def test_native_route_keeps_journal_controls_and_uses_delta_presentation(prepare):
    command = CompatibilityConversationRun(request={"agent_id": 7, "query": "hello", "conversation_id": 42})

    response = await runtime_client.forward_conversation_run(command, "user", "tenant")

    assert response is prepare.return_value
    prepare.assert_awaited_once()
    assert prepare.await_args.kwargs["include_journal_controls"] is True
    assert "complete_answer" not in prepare.await_args.kwargs
