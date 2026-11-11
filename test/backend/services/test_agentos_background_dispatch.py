# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep background preparation, source selection and projection in Management."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from contracts.agentos import AgentRunReference, AgentStop, BackgroundRun, TrackedBackgroundResult
from infrastructure.agentos_identity import ServicePrincipal
from management.db.conversation.prepared_turn import SavedUserTurn
from management.services.agent import background, runtime_client


ACTOR = ServicePrincipal("actor", "tenant")
REFERENCE = AgentRunReference(run_id="a" * 32, conversation_id=42)
PAYLOAD = BackgroundRun(run_id=REFERENCE.run_id, request={
    "query": "hello", "agent_id": 2, "conversation_id": 42, "model_id": 7,
    "tool_params": {"agents": {"root": {"tools": {"search": {"top_k": 5}}}}},
})


@pytest.fixture
def dispatch(mocker):
    record = {
        "run_id": 5, "runtime_run_id": REFERENCE.run_id, "conversation_id": 42, "user_id": "actor",
        "tenant_id": "tenant", "status": "RUNNING", "user_message_id": 23, "generated_prompt": "hello",
    }

    async def inline(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    mocker.patch.object(background, "_io", side_effect=inline)
    owner = mocker.patch.object(background, "conversation_belongs_to", return_value=True)
    lookup = mocker.patch.object(background.runs, "get_run_by_runtime_id", side_effect=lambda *_args, **_kw: record.copy())
    source = mocker.patch.object(background.turns, "read_saved_user_turn_by_id", return_value=SavedUserTurn(23, 8, "AUTOMATION"))
    mocker.patch.object(background.turns, "read_saved_user_turn_head", side_effect=background.turns.PreparedTurnConflict)
    snapshot = SimpleNamespace(memory_enabled=True, resource=SimpleNamespace(agent_id=2))
    compile_run = mocker.patch.object(background, "prepare_conversation_snapshot", new=AsyncMock(return_value=snapshot))
    writes = []

    def persist(run_id, values, user, *, expected_statuses, tenant_id, expected_source=None):
        assert (run_id, user, tenant_id, expected_statuses) == (5, "actor", "tenant", ["RUNNING"])
        if expected_source is not None and expected_source != {
            "generated_prompt": record.get("generated_prompt"), "user_message_id": record.get("user_message_id"),
        }:
            return None
        writes.append(values.copy())
        record.update(values)
        return record.copy()

    mocker.patch.object(background.runs, "update_run", side_effect=persist)
    finish_task = mocker.patch.object(background.runs, "update_task", side_effect=AssertionError("callback finalized task"))
    result = TrackedBackgroundResult(**REFERENCE.model_dump(), assistant_message_id=61, chunks=3)
    client = SimpleNamespace(
        start_prepared_run=AsyncMock(return_value=REFERENCE), run_tracked_background=AsyncMock(return_value=result),
        stop_run=AsyncMock(),
    )
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)
    project = mocker.patch.object(background, "_project", new=AsyncMock(return_value=result))
    return SimpleNamespace(
        record=record, client=client, owner=owner, lookup=lookup, source=source, compile=compile_run,
        writes=writes, project=project, result=result, finish_task=finish_task,
    )


@pytest.mark.asyncio
async def test_background_pins_source_configuration_and_projection_before_agent_run(dispatch):
    async def start(snapshot, user, tenant):
        assert snapshot is dispatch.compile.return_value and (user, tenant) == ("actor", "tenant")
        assert dispatch.writes == [{"projection_message_index": 9, "projection_memory_agent_id": 2}]
        return REFERENCE

    dispatch.client.start_prepared_run.side_effect = start
    assert await background.dispatch_background(PAYLOAD, ACTOR) == dispatch.result
    request, reference, user, tenant = dispatch.compile.await_args.args
    assert request.model_id == 7 and request.tool_params.agents["root"].tools == {"search": {"top_k": 5}}
    assert request.query == "hello" and request.enable_automation_tool is False
    assert (reference, user, tenant) == (REFERENCE, "actor", "tenant")
    assert dispatch.compile.await_args.kwargs == {"current_user_message_id": 23}
    dispatch.source.assert_called_once_with(42, "actor", "tenant", 23, "hello", None)
    dispatch.lookup.assert_called_once_with(REFERENCE.run_id, "tenant", "actor", conversation_id=42)
    dispatch.project.assert_awaited_once_with(dispatch.client, REFERENCE, dispatch.record)
    dispatch.client.run_tracked_background.assert_not_awaited()
    assert dispatch.record["status"] == "RUNNING"
    dispatch.finish_task.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["unknown", "unrecorded", "unsupported"])
async def test_old_background_requests_keep_one_explicit_legacy_fallback(dispatch, reason):
    if reason == "unknown":
        dispatch.lookup.side_effect = lambda *_args, **_kw: None
    elif reason == "unrecorded":
        dispatch.record["user_message_id"] = None
    else:
        dispatch.compile.return_value = None
    assert await background.dispatch_background(PAYLOAD, ACTOR) == dispatch.result
    dispatch.client.run_tracked_background.assert_awaited_once_with(
        PAYLOAD.model_copy(update={"preparation": "legacy"}), "actor", "tenant",
    )
    dispatch.client.start_prepared_run.assert_not_awaited()
    dispatch.project.assert_not_awaited()
    assert dispatch.writes == []


@pytest.mark.asyncio
async def test_pending_background_only_resumes_the_original_projection(dispatch):
    dispatch.record["projection_message_index"] = 9
    assert await background.dispatch_background(PAYLOAD, ACTOR) == dispatch.result
    dispatch.compile.assert_not_awaited()
    dispatch.client.start_prepared_run.assert_not_awaited()
    dispatch.project.assert_awaited_once_with(dispatch.client, REFERENCE, dispatch.record)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid,status", [("owner", 404), ("query", 409), ("origin", 422), ("canceled", 409), ("source_write", 409)])
async def test_scope_or_changed_background_cannot_start_runtime(dispatch, mocker, invalid, status):
    if invalid == "owner":
        dispatch.owner.return_value = False
    elif invalid == "query":
        dispatch.record["generated_prompt"] = "different instruction"
    elif invalid == "origin":
        dispatch.source.return_value = SavedUserTurn(23, 8, "CHAT")
    elif invalid == "canceled":
        dispatch.record.update(status="CANCELED", user_message_id=None)
    else:
        mocker.patch.object(background.runs, "update_run", return_value=None)
    with pytest.raises(HTTPException) as rejected:
        await background.dispatch_background(PAYLOAD, ACTOR)
    assert rejected.value.status_code == status
    dispatch.client.start_prepared_run.assert_not_awaited()
    dispatch.client.run_tracked_background.assert_not_awaited()
    dispatch.project.assert_not_awaited()


@pytest.mark.asyncio
async def test_background_disconnect_cancels_the_same_run_and_keeps_projection_metadata(dispatch):
    started = asyncio.Event()

    async def wait(*_args):
        started.set()
        await asyncio.Future()

    dispatch.project.side_effect = wait
    task = asyncio.create_task(background.dispatch_background(PAYLOAD, ACTOR))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    dispatch.client.stop_run.assert_awaited_once_with(AgentStop(**REFERENCE.model_dump(), prevent_start=True), "actor", "tenant")
    assert dispatch.record["projection_message_index"] == 9 and dispatch.record["status"] == "RUNNING"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "unavailable", "upstream"])
async def test_lost_background_ack_uses_owned_management_receipt_before_runtime_inspection(mocker, failure):
    from contracts.agent import AgentRequest
    from contracts.conversation import MessageSource
    from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError
    from management.db.conversation import repository as messages

    errors = {
        "timeout": RuntimeServiceTimeoutError("timeout"),
        "unavailable": RuntimeServiceUnavailableError("unavailable"),
        "upstream": RuntimeUpstreamError(503, b"unavailable", {}),
    }
    client = SimpleNamespace(run_tracked_background=AsyncMock(side_effect=errors[failure]), inspect_run=AsyncMock())
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)

    async def inline(_task, function, *args, **kwargs):
        kwargs.pop("lane", None)
        kwargs.pop("owner", None)
        return function(*args, **kwargs)

    mocker.patch.object(runtime_client, "run_blocking", side_effect=inline)
    lookup = mocker.patch.object(background.runs, "get_run_by_runtime_id", return_value={"projection_message_index": 9})
    receipt = mocker.patch.object(messages, "get_prepared_projection_receipt", return_value=(61, "completed"))
    result = await runtime_client.forward_tracked_background(
        AgentRequest.model_validate(PAYLOAD.request), REFERENCE.run_id, "actor", "tenant",
    )
    assert result == TrackedBackgroundResult(**REFERENCE.model_dump(), assistant_message_id=61, chunks=0)
    lookup.assert_called_once_with(REFERENCE.run_id, "tenant", "actor", conversation_id=42)
    receipt.assert_called_once_with(
        projection_run_id=REFERENCE.run_id, conversation_id=42, message_index=9,
        message_source=MessageSource.AUTOMATION, user_id="actor", tenant_id="tenant",
    )
    client.inspect_run.assert_not_awaited()
