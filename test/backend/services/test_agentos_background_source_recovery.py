# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Adopt an old automation prompt without appending or executing it twice."""

import pytest
from fastapi import HTTPException

from contracts.agent import AgentRequest
from management.services.agent import background
from management.services.automation.conversation import automation_conversation_adapter
from .test_agentos_background_dispatch import ACTOR, PAYLOAD, REFERENCE, dispatch


def old_payload():
    return PAYLOAD.model_copy(update={"request": {
        **PAYLOAD.request, "history": [
            {"role": role, "content": "previous"} for _ in range(4) for role in ("user", "assistant")
        ],
    }})


@pytest.fixture(autouse=True)
def source_history(mocker):
    return mocker.patch.object(automation_conversation_adapter, "load_run_prompt", return_value={
        "user_message_id": 23, "assistant_message_index": 9,
        "history": AgentRequest.model_validate(old_payload().request).history,
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["id", "prompt", "both"])
async def test_old_background_pins_owned_source_before_compilation(dispatch, mocker, missing):
    if missing in {"id", "both"}:
        dispatch.record["user_message_id"] = None
    if missing in {"prompt", "both"}:
        dispatch.record["generated_prompt"] = None
    by_head = mocker.patch.object(background.turns, "read_saved_user_turn_head", return_value=dispatch.source.return_value)
    payload = old_payload()
    snapshot = dispatch.compile.return_value

    async def compile_run(*_args, **kwargs):
        assert dispatch.writes == [{"generated_prompt": "hello", "user_message_id": 23}]
        assert kwargs["current_user_message_id"] == 23
        return snapshot

    dispatch.compile.side_effect = compile_run
    assert await background.dispatch_background(payload, ACTOR) == dispatch.result
    assert dispatch.writes == [
        {"generated_prompt": "hello", "user_message_id": 23},
        {"projection_message_index": 9, "projection_memory_agent_id": 2},
    ]
    assert dispatch.record["runtime_run_id"] == REFERENCE.run_id and dispatch.record["status"] == "RUNNING"
    if missing in {"id", "both"}:
        by_head.assert_called_once_with(42, "actor", "tenant", "hello", None)
        background.automation_conversation_adapter.load_run_prompt.assert_called_once_with(
            42, 23, "hello", "actor", "tenant",
        )
    else:
        dispatch.source.assert_called_once_with(42, "actor", "tenant", 23, "hello", None)
    dispatch.client.start_prepared_run.assert_awaited_once_with(snapshot, "actor", "tenant")
    dispatch.client.run_tracked_background.assert_not_awaited()
    dispatch.finish_task.assert_not_called()


@pytest.mark.asyncio
async def test_lost_source_pin_cannot_compile_or_start(dispatch, mocker):
    dispatch.record["generated_prompt"] = None
    mocker.patch.object(background.runs, "update_run", return_value=None)
    with pytest.raises(HTTPException) as denied:
        await background.dispatch_background(PAYLOAD, ACTOR)
    assert denied.value.status_code == 409
    dispatch.compile.assert_not_awaited()
    dispatch.client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["source", "position", "conflict", "scope"])
async def test_recovered_history_must_keep_the_owned_source_boundary(dispatch, mocker, source_history, reason):
    dispatch.record.update(user_message_id=None, generated_prompt=None)
    mocker.patch.object(background.turns, "read_saved_user_turn_head", return_value=dispatch.source.return_value)
    if reason == "source":
        source_history.return_value["user_message_id"] = 24
    elif reason == "position":
        source_history.return_value["assistant_message_index"] = 11
    elif reason == "conflict":
        source_history.side_effect = background.turns.PreparedTurnConflict
    else:
        source_history.side_effect = background.AdmissionScopeError
    if reason == "scope":
        with pytest.raises(HTTPException) as denied:
            await background.dispatch_background(old_payload(), ACTOR)
        assert denied.value.status_code == 404
        dispatch.client.run_tracked_background.assert_not_awaited()
    else:
        with pytest.raises(HTTPException) as denied:
            await background.dispatch_background(old_payload(), ACTOR)
        assert denied.value.status_code == 422
        dispatch.client.run_tracked_background.assert_not_awaited()
    assert not dispatch.writes
    dispatch.compile.assert_not_awaited()
    dispatch.client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_competing_source_pin_cannot_be_overwritten_or_executed(dispatch, mocker):
    dispatch.record.update(user_message_id=None, generated_prompt=None)

    def changed_head(*_args):
        dispatch.record.update(user_message_id=24, generated_prompt="newer source")
        return dispatch.source.return_value

    mocker.patch.object(background.turns, "read_saved_user_turn_head", side_effect=changed_head)
    with pytest.raises(HTTPException) as denied:
        await background.dispatch_background(old_payload(), ACTOR)
    assert denied.value.status_code == 409
    assert dispatch.record["user_message_id"] == 24 and dispatch.record["generated_prompt"] == "newer source"
    dispatch.compile.assert_not_awaited()
    dispatch.client.start_prepared_run.assert_not_awaited()
    dispatch.client.run_tracked_background.assert_not_awaited()


@pytest.mark.asyncio
async def test_unprovable_background_source_never_uses_legacy_execution(dispatch, mocker):
    dispatch.record.update(user_message_id=None, generated_prompt=None)
    mocker.patch.object(background.turns, "read_saved_user_turn_head", side_effect=background.turns.PreparedTurnConflict)
    with pytest.raises(HTTPException) as denied:
        await background.dispatch_background(old_payload(), ACTOR)
    assert denied.value.status_code == 422
    assert dispatch.writes == []
    dispatch.client.run_tracked_background.assert_not_awaited()
    dispatch.compile.assert_not_awaited()
    dispatch.client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["other-origin", "scope", "terminal"])
async def test_old_source_scope_and_compatibility_boundaries(dispatch, mocker, reason):
    dispatch.record.update(user_message_id=None, generated_prompt=None)
    if reason == "terminal":
        dispatch.record["status"] = "SUCCEEDED"
    source = background.turns.SavedUserTurn(23, 8, "CHAT")
    head = mocker.patch.object(background.turns, "read_saved_user_turn_head", return_value=source)
    if reason == "scope":
        head.side_effect = background.AdmissionScopeError
        with pytest.raises(HTTPException) as denied:
            await background.dispatch_background(old_payload(), ACTOR)
        assert denied.value.status_code == 404
        dispatch.client.run_tracked_background.assert_not_awaited()
    else:
        with pytest.raises(HTTPException) as denied:
            await background.dispatch_background(old_payload(), ACTOR)
        assert denied.value.status_code == 422
        dispatch.client.run_tracked_background.assert_not_awaited()
        if reason == "terminal":
            head.assert_not_called()
    assert dispatch.writes == []
    dispatch.compile.assert_not_awaited()
    dispatch.client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_text_in_a_newer_turn_cannot_replace_the_original_history(dispatch, mocker, source_history):
    dispatch.record.update(user_message_id=None, generated_prompt=None)
    mocker.patch.object(background.turns, "read_saved_user_turn_head", return_value=dispatch.source.return_value)
    source_history.return_value["history"] = []
    payload = old_payload()
    with pytest.raises(HTTPException) as denied:
        await background.dispatch_background(payload, ACTOR)
    assert denied.value.status_code == 422
    assert dispatch.writes == []
    dispatch.client.run_tracked_background.assert_not_awaited()
    dispatch.compile.assert_not_awaited()
    dispatch.client.start_prepared_run.assert_not_awaited()
