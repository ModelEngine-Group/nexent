# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Use the saved user ID as the history and assistant projection boundary."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.responses import Response

from contracts.agent import AgentRequest
from contracts.agentos import AgentRunReference, CompatibilityConversationRun
from contracts.conversation import MessageSource
from management.db.conversation.prepared_turn import PreparedTurn, SavedUserTurn
from management.services.agent import prepared_turn as service


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_before_stage", [False, True])
async def test_saved_source_pins_history_and_staging_before_any_runtime_start(mocker, changed_before_stage):
    async def inline(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    reference = AgentRunReference(conversation_id=42, run_id="a" * 32)
    source = SavedUserTurn(23, 4, "CHAT")
    request = AgentRequest(query="hello", agent_id=7, conversation_id=42, enable_automation_tool=False)
    payload = CompatibilityConversationRun(
        request=request.model_dump(mode="json"), user_message="saved", idempotency_key="saved-message-23",
        claimed_run_id=reference.run_id,
    )
    turn = PreparedTurn(reference, "actor", "tenant", 5, None, datetime.now(timezone.utc))
    confirmed = PreparedTurn(reference, "actor", "tenant", 5, 61, turn.staged_at)
    snapshot = SimpleNamespace(runtime_metadata_version=0, memory_enabled=False)
    mocker.patch.object(service, "_io", side_effect=inline)
    mocker.patch.object(service, "get_conversation", return_value={})
    next_index = mocker.patch.object(service.store, "next_message_index", side_effect=AssertionError("advanced user index"))
    compile_run = mocker.patch.object(service, "prepare_conversation_snapshot", new=AsyncMock(return_value=snapshot))
    stage = mocker.patch.object(service.store, "stage_turn", return_value=turn)
    if changed_before_stage:
        stage.side_effect = service.store.PreparedTurnConflict
    confirm = mocker.patch.object(service.store, "confirm_turn", return_value=confirmed)
    mocker.patch.object(service, "reject_unstaged_turn", new=AsyncMock())
    stream = mocker.patch.object(service, "_stream_turn", new=AsyncMock(return_value=Response()))
    client = SimpleNamespace(
        find_active_run=AsyncMock(return_value=None), start_prepared_run=AsyncMock(return_value=reference),
    )
    if changed_before_stage:
        with pytest.raises(HTTPException) as rejected:
            await service.start_turn(payload, request, "actor", "tenant", client, saved_user=source)
        assert rejected.value.status_code == 409
        confirm.assert_not_called()
        client.start_prepared_run.assert_not_awaited()
        stream.assert_not_awaited()
    else:
        assert await service.start_turn(payload, request, "actor", "tenant", client, saved_user=source) is stream.return_value
        confirm.assert_called_once_with(turn)
        client.start_prepared_run.assert_awaited_once_with(snapshot, "actor", "tenant")
    options = compile_run.await_args.kwargs
    assert options["current_user_message_id"] == source.message_id
    assert "before_message_index" not in options
    assert stage.call_args.args[4] == source.message_index
    assert stage.call_args.kwargs["saved_user"] == source
    next_index.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [MessageSource.CHAT, MessageSource.AUTOMATION])
async def test_saved_turn_projection_uses_the_reserved_message_origin(mocker, source):
    async def inline(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    turn = SimpleNamespace(
        reference=AgentRunReference(conversation_id=42, run_id="a" * 32), user_id="actor", tenant_id="tenant",
        message_index=5, assistant_message_id=61, memory_agent_id=None, message_source=source,
    )
    mocker.patch.object(service, "_io", side_effect=inline)
    receipt = mocker.patch.object(service, "get_prepared_projection_receipt", return_value=None)
    project = mocker.patch.object(service, "resume_assistant_projection", new=AsyncMock())
    close = mocker.patch.object(service.store, "close_turn")
    await service._finish_projection(turn, SimpleNamespace(resume=AsyncMock()))
    assert receipt.call_args.kwargs["message_source"] == source
    assert project.await_args.kwargs["message_source"] == source
    close.assert_called_once_with(turn)
