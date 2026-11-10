# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.responses import StreamingResponse

from contracts.agent import AgentRequest
from contracts.agentos import AgentRunLookup, AgentRunReference, AgentStop, CompatibilityConversationRun
from contracts.errors.exceptions import RuntimeServiceUnavailableError, RuntimeUpstreamError
from management.services.agent import prepared_turn, runtime_client


ACTOR = ("actor", "tenant")
REFERENCE = AgentRunReference(conversation_id=42, run_id="a" * 32)
PAYLOAD = CompatibilityConversationRun(
    request={"query": "question", "agent_id": 7, "conversation_id": 42, "enable_automation_tool": False},
    idempotency_key="once", claimed_run_id=REFERENCE.run_id,
)


@pytest.fixture
def flow(mocker):
    operations = []
    identity = {
        "reference": REFERENCE, "user_id": ACTOR[0], "tenant_id": ACTOR[1], "message_index": 9,
        "staged_at": datetime.now(timezone.utc) - timedelta(minutes=2),
    }
    staged = SimpleNamespace(**identity, assistant_message_id=None)
    confirmed = SimpleNamespace(**identity, assistant_message_id=61)
    snapshot = SimpleNamespace(runtime_metadata_version=2)

    async def inline(_name, fn, *args, lane, owner, **kwargs):
        return fn(*args, **kwargs)

    mocker.patch.object(prepared_turn, "run_blocking", side_effect=inline)
    mocker.patch.object(prepared_turn.store, "next_message_index", return_value=8)
    compile_snapshot = mocker.patch.object(prepared_turn, "prepare_conversation_snapshot", return_value=snapshot)
    mocker.patch.object(prepared_turn.store, "stage_turn", side_effect=lambda *_: operations.append("stage") or staged)
    mocker.patch.object(prepared_turn.store, "confirm_turn", side_effect=lambda *_: operations.append("confirm") or confirmed)
    mocker.patch.object(prepared_turn.store, "close_turn", side_effect=lambda *_args, **_kwargs: operations.append("close"))

    async def start(*args):
        assert args == (snapshot, *ACTOR)
        assert operations == ["stage"]
        operations.append("start")
        return REFERENCE

    async def chunks():
        yield b"data: answer\n\n"

    client = SimpleNamespace(
        find_active_run=AsyncMock(return_value=None), start_prepared_run=AsyncMock(side_effect=start),
        resume=AsyncMock(return_value=StreamingResponse(chunks(), media_type="text/event-stream")),
    )
    return operations, compile_snapshot, client, staged


@pytest.mark.asyncio
async def test_public_prepared_stages_confirms_and_uses_signed_journal(flow):
    operations, compile_snapshot, client, _ = flow
    result = await prepared_turn.start_turn(PAYLOAD, AgentRequest.model_validate(PAYLOAD.request), *ACTOR, client)

    assert operations == ["stage", "start", "confirm"]
    assert compile_snapshot.await_args.kwargs["before_message_index"] == 8
    assert result.headers["run_id"] == REFERENCE.run_id and result.headers["conversation_id"] == "42"
    assert result.headers["X-Runtime-Metadata-Version"] == "2"
    assert b"".join([chunk async for chunk in result.body_iterator]) == b"data: answer\n\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("known", [False, True])
async def test_public_prepared_only_releases_a_definitive_rejection(flow, known):
    operations, _, client, _ = flow
    error = RuntimeUpstreamError(409, b"", {}) if known else RuntimeServiceUnavailableError("lost response")
    client.start_prepared_run.side_effect = error
    with pytest.raises(type(error)):
        await prepared_turn.start_turn(PAYLOAD, AgentRequest.model_validate(PAYLOAD.request), *ACTOR, client)

    assert operations == (["stage", "close"] if known else ["stage"])
    client.resume.assert_not_awaited()


@pytest.mark.asyncio
async def test_unsupported_snapshot_leaves_the_compatibility_path_available(flow):
    operations, compile_snapshot, client, _ = flow
    compile_snapshot.return_value = None
    result = await prepared_turn.start_turn(PAYLOAD, AgentRequest.model_validate(PAYLOAD.request), *ACTOR, client)
    assert result is None and operations == []
    client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_confirms_a_lost_ack_and_projects_into_the_reserved_message(flow, mocker):
    operations, _, client, staged = flow
    client.inspect_run = AsyncMock(return_value=SimpleNamespace(
        **REFERENCE.model_dump(), status="completed", latest_event_id=f"{REFERENCE.run_id}:3",
    ))
    mocker.patch.object(prepared_turn, "get_prepared_projection_receipt", return_value=None)
    project = mocker.patch.object(prepared_turn, "resume_assistant_projection")

    await prepared_turn.reconcile_turn(staged, client)

    client.inspect_run.assert_awaited_once_with(AgentRunLookup(**REFERENCE.model_dump()), *ACTOR)
    assert project.await_args.args[1:] == (REFERENCE, *ACTOR)
    assert project.await_args.kwargs["assistant_message_id"] == 61
    assert operations == ["confirm", "close"]
    client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_unobserved_admission_is_fenced_before_discarding_the_staged_input(flow):
    operations, _, client, staged = flow
    client.inspect_run = AsyncMock(side_effect=RuntimeUpstreamError(404, b"", {}))
    client.stop_run = AsyncMock(return_value=SimpleNamespace(
        **REFERENCE.model_dump(), status="stopped", latest_event_id=None,
    ))

    await prepared_turn.reconcile_turn(staged, client)

    client.stop_run.assert_awaited_once_with(AgentStop(**REFERENCE.model_dump(), prevent_start=True), *ACTOR)
    assert operations == ["close"]
    client.start_prepared_run.assert_not_awaited()
    client.resume.assert_not_awaited()


@pytest.mark.asyncio
async def test_cursorless_resume_uses_the_pending_prepared_turn(flow, mocker):
    _, _, client, staged = flow
    current = SimpleNamespace(**{**vars(staged), "assistant_message_id": 61})
    client.run_conversation = AsyncMock()
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)
    mocker.patch.object(prepared_turn.store, "pending_turn", return_value=current)
    payload = CompatibilityConversationRun(request={"query": "", "conversation_id": 42}, resume=True)

    response = await runtime_client.forward_conversation_run(payload, *ACTOR)

    assert response.headers["X-Stream-Status"] == "resumed"
    assert response.headers["run_id"] == REFERENCE.run_id
    client.run_conversation.assert_not_awaited()
    client.start_prepared_run.assert_not_awaited()
    await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_event_store_rejection_does_not_create_a_visible_turn(flow):
    operations, _, client, _ = flow
    error = RuntimeUpstreamError(503, b'{"detail":{"code":"AGENTOS_EVENT_STORE_UNAVAILABLE"}}', {})
    client.start_prepared_run.side_effect = error

    with pytest.raises(RuntimeUpstreamError):
        await prepared_turn.start_turn(PAYLOAD, AgentRequest.model_validate(PAYLOAD.request), *ACTOR, client)

    assert operations == ["stage", "close"]
    client.resume.assert_not_awaited()
