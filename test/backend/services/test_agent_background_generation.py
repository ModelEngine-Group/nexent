# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Background work binds ownership and retry behavior to one admitted run."""

from unittest.mock import AsyncMock

import pytest
from starlette.responses import Response

from contracts.errors.exceptions import AgentBackgroundError
from infrastructure.rdb.agent_admission import AdmissionClaim
from management.api.agent import conversation_run
from management.services.agent import background_compatibility as service
from management.services.conversation import creator_runtime
from .test_agentos_compatibility_background import ACTOR, PAYLOAD, REFERENCE, flow


@pytest.mark.asyncio
async def test_preparation_failure_leaves_no_assistant_or_started_runtime(flow):
    error = RuntimeError("invalid model configuration")
    flow.preparation.side_effect = error
    with pytest.raises(RuntimeError) as failed:
        await service.run_background(flow.client, PAYLOAD, ACTOR)

    assert failed.value is error
    flow.reject.assert_called_once()
    flow.stage.assert_not_called()
    flow.confirm.assert_not_called()
    flow.client.start_prepared_run.assert_not_awaited()
    flow.project.assert_not_awaited()


@pytest.mark.asyncio
async def test_interrupted_projection_retries_the_same_confirmation_without_a_second_run(flow):
    flow.project.side_effect = RuntimeError("stream opening failed")

    with pytest.raises(RuntimeError, match="stream opening failed"):
        await service.run_background(flow.client, PAYLOAD, ACTOR)
    flow.confirm.assert_called_once_with(flow.staged)
    flow.close.assert_not_called()
    flow.reject.assert_not_called()

    flow.claim.return_value = AdmissionClaim(REFERENCE.run_id, "admitted", 42, True, False)
    flow.read.return_value = flow.confirmed
    flow.project.side_effect = None
    result = await service.run_background(flow.client, PAYLOAD, ACTOR)

    assert result.run_id == REFERENCE.run_id and result.assistant_message_id == 61
    flow.client.start_prepared_run.assert_awaited_once_with(flow.snapshot, ACTOR.user_id, ACTOR.tenant_id)
    flow.stage.assert_called_once()
    flow.close.assert_called_once_with(flow.confirmed)
    assert flow.project.await_count == 2
    assert all(call.kwargs["assistant_message_id"] == 61 for call in flow.project.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("memory_agent", [None, 7])
async def test_execution_failure_does_not_repeat_background_or_leave_its_slot_open(flow, memory_agent):
    flow.confirmed.memory_agent_id = memory_agent
    flow.project.return_value.status = "failed"

    with pytest.raises(AgentBackgroundError, match="AGENTOS_BACKGROUND_NOT_COMPLETED"):
        await service.run_background(flow.client, PAYLOAD, ACTOR)

    flow.client.start_prepared_run.assert_awaited_once_with(flow.snapshot, ACTOR.user_id, ACTOR.tenant_id)
    flow.close.assert_called_once_with(flow.confirmed)
    assert flow.project.await_args.kwargs.get("memory_agent_id") == memory_agent


@pytest.mark.asyncio
async def test_background_with_no_precreated_prompt_only_projects_its_automation_assistant(flow):
    result = await service.run_background(flow.client, PAYLOAD, ACTOR)

    assert result.assistant_message_id == 61 and result.chunks == 2
    assert flow.stage.call_args.args[1:5] == (REFERENCE, ACTOR.user_id, ACTOR.tenant_id, 0)
    assert flow.stage.call_args.kwargs == {"omitted_user": True, "background_run": True}
    assert flow.project.await_args.kwargs["message_source"] == "AUTOMATION"
    flow.close.assert_called_once_with(flow.confirmed)


@pytest.mark.asyncio
async def test_generation_specific_stop_never_signals_a_different_agent_run(mocker):
    generation = "b" * 32
    mocker.patch.object(conversation_run, "get_current_user_id", return_value=(ACTOR.user_id, ACTOR.tenant_id))
    creator_stop = mocker.patch.object(creator_runtime, "stop_creator", return_value=False)
    find_active = mocker.patch.object(conversation_run, "forward_active_run", return_value=REFERENCE.run_id)
    signed_stop = mocker.patch.object(conversation_run, "forward_scoped_stop", new=AsyncMock())

    result = await conversation_run.stop_conversation("42", Response(), authorization="token", generation=generation)

    assert result["status"] == "success" and result["already_stopped"] is True
    creator_stop.assert_awaited_once_with(42, ACTOR.user_id, generation)
    find_active.assert_not_awaited()
    signed_stop.assert_not_awaited()
