# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.responses import StreamingResponse

from contracts.agent import AgentRequest
from contracts.agentos import AgentLegacyResume, AgentRunLookup, AgentRunReference, AgentStop, CompatibilityConversationRun
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, RuntimeMetadataVersionConflict, RuntimeServiceUnavailableError, RuntimeUpstreamError
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
        "memory_agent_id": None,
    }
    staged = SimpleNamespace(**identity, assistant_message_id=None)
    confirmed = SimpleNamespace(**identity, assistant_message_id=61)
    snapshot = SimpleNamespace(runtime_metadata_version=2, memory_enabled=None)

    async def inline(_name, fn, *args, lane, owner, **kwargs):
        return fn(*args, **kwargs)

    mocker.patch.object(prepared_turn, "run_blocking", side_effect=inline)
    mocker.patch.object(prepared_turn.store, "next_message_index", return_value=8)
    mocker.patch.object(prepared_turn, "get_conversation", return_value={})
    compile_snapshot = mocker.patch.object(prepared_turn, "prepare_conversation_snapshot", return_value=snapshot)
    mocker.patch.object(prepared_turn.store, "stage_turn", side_effect=lambda *_args, **_kwargs: operations.append("stage") or staged)
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
async def test_public_memory_pins_the_snapshot_agent(flow):
    _, compile_snapshot, client, _ = flow
    compile_snapshot.return_value.memory_enabled = True
    compile_snapshot.return_value.resource = SimpleNamespace(agent_id=7)
    await prepared_turn.start_turn(PAYLOAD, AgentRequest.model_validate(PAYLOAD.request), *ACTOR, client)
    assert prepared_turn.store.stage_turn.call_args.args[5]["memory_agent_id"] == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("has_conversation", [True, False])
async def test_clarification_stays_in_management_staging_and_starts_a_new_run(flow, mocker, has_conversation):
    operations, _, client, _ = flow
    request = AgentRequest.model_validate({
        **PAYLOAD.request,
        "conversation_id": REFERENCE.conversation_id if has_conversation else None,
        "clarification_response": {
            "form": {"schema_version": 1, "questions": [{"id": "goal", "type": "text", "title": "Goal?"}]},
            "answers": [{"questionId": "goal", "value": "Continue"}],
        },
    })
    if not has_conversation:
        reject = mocker.patch.object(prepared_turn, "reject_unstaged_turn")
        with pytest.raises(AppException, match="Clarification requires an existing conversation"):
            await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, client)
        client.start_prepared_run.assert_not_awaited()
        reject.assert_awaited_once_with(PAYLOAD, *ACTOR)
        assert operations == []
        return
    result = await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, client)

    assert operations == ["stage", "start", "confirm"]
    assert prepared_turn.store.stage_turn.call_args.args[5]["clarification_response"] == (
        request.clarification_response.model_dump(mode="json")
    )
    assert result.headers["run_id"] == REFERENCE.run_id


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
    client.resume_legacy = AsyncMock()
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)
    lookup = mocker.patch.object(prepared_turn.store, "read_cursorless_resume", return_value=current)
    payload = CompatibilityConversationRun(request={"query": "", "conversation_id": 42}, resume=True)

    response = await runtime_client.forward_conversation_run(payload, *ACTOR)

    lookup.assert_called_once_with(42, *ACTOR)
    assert response.headers["X-Stream-Status"] == "resumed"
    assert response.headers["run_id"] == REFERENCE.run_id
    client.resume_legacy.assert_not_awaited()
    client.start_prepared_run.assert_not_awaited()
    await response.body_iterator.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [
    "completed", "failed", "stopped", "awaiting", "unknown", "foreign", "disabled", "no_assistant_message",
])
async def test_cursorless_resume_handles_only_owned_prepared_turns(flow, mocker, state):
    from fastapi import HTTPException

    from infrastructure.rdb.agent_admission import AdmissionScopeError

    operations, _, client, staged = flow
    client.resume_legacy = AsyncMock()
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)
    lookup = mocker.patch.object(prepared_turn.store, "read_cursorless_resume", return_value={
        "awaiting": staged, "unknown": None,
    }.get(state, state))
    payload = CompatibilityConversationRun(request={"query": "", "conversation_id": 42}, resume=True)
    if state == "foreign":
        lookup.side_effect = AdmissionScopeError
        with pytest.raises(HTTPException) as denied:
            await runtime_client.forward_conversation_run(payload, *ACTOR)
        assert denied.value.status_code == 403
        assert denied.value.detail == "Conversation is not accessible to the current identity"
    elif state == "disabled":
        from contracts.errors.exceptions import WorkbenchError

        lookup.side_effect = WorkbenchError("WORKBENCH_DISABLED", status_code=404)
        with pytest.raises(HTTPException) as denied:
            await runtime_client.forward_conversation_run(payload, *ACTOR)
        assert denied.value.status_code == 404
        assert denied.value.detail == {"code": "WORKBENCH_DISABLED"}
    else:
        result = await runtime_client.forward_conversation_run(payload, *ACTOR)
        if state == "unknown":
            assert result is client.resume_legacy.return_value
        elif state == "awaiting":
            assert json.loads(result.body) == {"status": "streaming", "message": "Waiting for Runtime admission"}
        elif state == "no_assistant_message":
            assert json.loads(result.body) == {"status": None, "message": "Stream already None: no_assistant_message"}
            client.find_active_run.assert_not_awaited()
        else:
            assert json.loads(result.body) == {"status": state, "message": f"Stream already {state}: backend_{state}"}
    lookup.assert_called_once_with(42, *ACTOR)
    if state == "unknown":
        client.resume_legacy.assert_awaited_once_with(AgentLegacyResume(conversation_id=42), *ACTOR)
    else:
        client.resume_legacy.assert_not_awaited()
    assert operations == []
    client.start_prepared_run.assert_not_awaited()
    client.resume.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "failed", "stopped", "running", "mismatch", "missing"])
async def test_cursorless_resume_confirms_legacy_receipt_with_agentos(flow, mocker, status):
    _, _, client, _ = flow
    receipt = prepared_turn.store.LegacyResumeReceipt(
        REFERENCE.run_id, 61, status if status in {"completed", "failed", "stopped"} else "completed",
    )
    mocker.patch.object(prepared_turn.store, "read_cursorless_resume", return_value=receipt)
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)
    client.resume_legacy = AsyncMock()
    client.inspect_run = AsyncMock(return_value=SimpleNamespace(
        **REFERENCE.model_dump(), assistant_message_id=62 if status == "mismatch" else 61,
        status=receipt.status if status == "mismatch" else status,
    ))
    if status == "missing":
        client.inspect_run.side_effect = RuntimeUpstreamError(status_code=404, content=b"", headers={})
    payload = CompatibilityConversationRun(request={"query": "", "conversation_id": 42}, resume=True)

    response = await runtime_client.forward_conversation_run(payload, *ACTOR)

    client.inspect_run.assert_awaited_once_with(AgentRunLookup(**REFERENCE.model_dump()), *ACTOR)
    if status in {"completed", "failed", "stopped"}:
        assert json.loads(response.body) == {"status": status, "message": f"Stream already {status}: backend_{status}"}
        client.find_active_run.assert_not_awaited()
        client.resume_legacy.assert_not_awaited()
    else:
        assert response is client.resume_legacy.return_value
        client.find_active_run.assert_awaited_once_with(42, *ACTOR)
        client.resume_legacy.assert_awaited_once_with(AgentLegacyResume(conversation_id=42), *ACTOR)
    client.resume.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "failed", "stopped", "other-message", "other-conversation", "unconfirmed", 404, 422, 503])
async def test_cursorless_resume_inspects_old_terminal_message_without_receipt(flow, mocker, outcome):
    from contracts.agentos import AgentMessageRunLookup

    _, _, client, _ = flow
    status = outcome if outcome in {"completed", "failed", "stopped"} else "failed"
    mocker.patch.object(
        prepared_turn.store, "read_cursorless_resume",
        return_value=prepared_turn.store.LegacyTerminalMessage(61, status),
    )
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)
    client.resume_legacy = AsyncMock()
    client.inspect_run = AsyncMock(return_value=SimpleNamespace(
        conversation_id=43 if outcome == "other-conversation" else 42,
        assistant_message_id=62 if outcome == "other-message" else 61,
        status="running" if outcome == "unconfirmed" else status,
    ))
    if isinstance(outcome, int):
        client.inspect_run.side_effect = RuntimeUpstreamError(status_code=outcome, content=b"", headers={})
    payload = CompatibilityConversationRun(request={"query": "", "conversation_id": 42}, resume=True)

    result = await runtime_client.forward_conversation_run(payload, *ACTOR)

    client.inspect_run.assert_awaited_once_with(AgentMessageRunLookup(conversation_id=42, assistant_message_id=61), *ACTOR)
    client.resume.assert_not_awaited()
    if outcome in {"completed", "failed", "stopped"}:
        assert json.loads(result.body) == {"status": status, "message": f"Stream already {status}: backend_{status}"}
        client.find_active_run.assert_not_awaited()
        client.resume_legacy.assert_not_awaited()
    else:
        client.find_active_run.assert_awaited_once_with(42, *ACTOR)
        client.resume_legacy.assert_awaited_once_with(AgentLegacyResume(conversation_id=42), *ACTOR)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["available", "missing", "expired", "old_runtime", "missing_message", "broken"])
async def test_cursorless_resume_adapts_retained_legacy_journal(flow, mocker, mode):
    from contracts.agentos import AgentResume

    _, _, client, _ = flow
    fallback = StreamingResponse(iter(()))
    client.resume_legacy = AsyncMock(return_value=fallback)
    client.find_active_run.return_value = None if mode == "missing" else REFERENCE.run_id
    client.inspect_run = AsyncMock(return_value=SimpleNamespace(
        **REFERENCE.model_dump(), assistant_message_id=None if mode == "missing_message" else 61,
    ))
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)
    mocker.patch.object(prepared_turn.store, "read_cursorless_resume", return_value=None)
    index = mocker.patch.object(prepared_turn.store, "read_legacy_resume_index", return_value=7)
    closed = AsyncMock()

    async def frames():
        yield f'id: {REFERENCE.run_id}:1\ndata: {{"type":"answer","content":"earlier"}}\n\n'.encode()
        if mode == "broken":
            yield b'event: agentos_error\ndata: {"code":"AGENTOS_CURSOR_UNAVAILABLE"}\n\n'
        else:
            yield f'id: {REFERENCE.run_id}:2\nevent: agentos_terminal\ndata: {{"status":"stopped"}}\n\n'.encode()

    client.resume.return_value = StreamingResponse(
        frames(), status_code=410 if mode == "expired" else 200,
        headers={"X-AgentOS-Replay-Count": "1", "X-AgentOS-Run-ID": REFERENCE.run_id} if mode != "old_runtime" else {},
        background=closed,
    )
    payload = CompatibilityConversationRun(request={"query": "", "conversation_id": 42}, resume=True)
    output = await runtime_client.forward_conversation_run(payload, *ACTOR)

    client.find_active_run.assert_awaited_once_with(42, *ACTOR)
    if mode in {"available", "broken"}:
        assert output.headers["X-Stream-Status"] == "resumed"
        assert output.headers["X-Last-Unit-Index"] == "8"
        assert "X-AgentOS-Run-ID" not in output.headers and "X-AgentOS-Replay-Count" not in output.headers
        chunks = [chunk async for chunk in output.body_iterator]
        assert chunks[0].startswith(b"event: stream_status\n")
        assert json.loads(chunks[0].split(b"data: ", 1)[1]) == {
            "status": "resumed", "last_unit_index": 7, "replay_chunk_count": 1,
        }
        assert json.loads(chunks[1][6:]) == {"type": "answer", "content": "earlier"}
        assert json.loads(chunks[-1].split(b"data: ", 1)[1]) == {
            "status": "failed" if mode == "broken" else "stopped", "last_unit_index": 7,
        }
        if mode == "broken":
            assert json.loads(chunks[2][6:])["type"] == "error"
        client.resume_legacy.assert_not_awaited()
    else:
        assert output is fallback
        client.resume_legacy.assert_awaited_once_with(AgentLegacyResume(conversation_id=42), *ACTOR)
    if mode not in {"missing", "missing_message"}:
        index.assert_called_once_with(42, 61, *ACTOR)
        client.resume.assert_awaited_once_with(AgentResume(**REFERENCE.model_dump()), *ACTOR)
    else:
        index.assert_not_called()
        client.resume.assert_not_awaited()
    assert closed.await_count == (1 if mode in {"expired", "old_runtime"} else 0)


@pytest.mark.asyncio
async def test_explicit_workbench_resume_obeys_disabled_feature_before_lookup(flow, mocker):
    from fastapi import HTTPException

    _, _, client, _ = flow
    client.resume_legacy = AsyncMock()
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)
    mocker.patch.object(runtime_client, "ENABLE_AGENT_WORKBENCH", False)
    lookup = mocker.patch.object(prepared_turn.store, "read_cursorless_resume")
    payload = CompatibilityConversationRun(
        request={"query": "", "conversation_id": 42, "entrypoint": "workbench"}, resume=True,
    )

    with pytest.raises(HTTPException) as denied:
        await runtime_client.forward_conversation_run(payload, *ACTOR)

    assert denied.value.status_code == 404
    assert denied.value.detail == {"code": "WORKBENCH_DISABLED"}
    lookup.assert_not_called()
    client.resume_legacy.assert_not_awaited()


@pytest.mark.asyncio
async def test_event_store_rejection_does_not_create_a_visible_turn(flow):
    operations, _, client, _ = flow
    error = RuntimeUpstreamError(503, b'{"detail":{"code":"AGENTOS_EVENT_STORE_UNAVAILABLE"}}', {})
    client.start_prepared_run.side_effect = error

    with pytest.raises(RuntimeUpstreamError):
        await prepared_turn.start_turn(PAYLOAD, AgentRequest.model_validate(PAYLOAD.request), *ACTOR, client)

    assert operations == ["stage", "close"]
    client.resume.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_prepared_turn_compiles_before_creating_a_conversation(flow, mocker):
    operations, compile_snapshot, client, _ = flow
    mocker.patch.object(prepared_turn.store, "allocate_conversation_id", return_value=REFERENCE.conversation_id)
    payload = PAYLOAD.model_copy(update={"request": {"query": "question", "agent_id": 7,
                                                        "enable_automation_tool": False}, "language": "en"})

    response = await prepared_turn.start_turn(payload, AgentRequest.model_validate(payload.request), *ACTOR, client)

    assert operations == ["stage", "start", "confirm"]
    assert compile_snapshot.await_args.kwargs["new_conversation"] is True
    assert response.headers["conversation_id"] == str(REFERENCE.conversation_id)
    output = b"".join([part async for part in response.body_iterator])
    assert b'"type":"conversation_created"' in output and output.endswith(b"data: answer\n\n")
    client.find_active_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_unexportable_first_turn_never_creates_a_conversation(flow, mocker):
    operations, compile_snapshot, client, _ = flow
    mocker.patch.object(prepared_turn.store, "allocate_conversation_id", return_value=REFERENCE.conversation_id)
    compile_snapshot.return_value = None
    request = AgentRequest(query="question", agent_id=7, enable_automation_tool=False)
    payload = PAYLOAD.model_copy(update={"request": request.model_dump(mode="json", exclude_none=True)})

    assert await prepared_turn.start_turn(payload, request, *ACTOR, client) is None
    assert operations == [] and request.conversation_id is None
    client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["prepared", "unsupported", "ambiguous", "metadata", "active"])
async def test_northbound_dispatch_saves_in_legacy_only_before_agentos_dispatch(mocker, outcome):
    from management.services.agent import conversation_submission

    fallback = AsyncMock(return_value=StreamingResponse(iter(())))
    prepared = StreamingResponse(iter(()))
    start = mocker.patch.object(prepared_turn, "start_turn", return_value=prepared)
    if outcome == "unsupported":
        start.return_value = None
    if outcome == "ambiguous":
        start.side_effect = RuntimeServiceUnavailableError("lost acknowledgement")
    if outcome == "active":
        start.side_effect = prepared_turn.active_turn_conflict()
    release = mocker.patch.object(prepared_turn, "reject_unstaged_turn")
    mocker.patch.object(prepared_turn, "find_pending_turn", return_value=REFERENCE if outcome == "active" else None)

    async def submit(payload, user, tenant, dispatch, *, include_claim_headers):
        assert not include_claim_headers
        assert payload.idempotency_key.startswith("prepared-")
        return await dispatch(payload.model_copy(update={"claimed_run_id": REFERENCE.run_id}), user, tenant)

    mocker.patch.object(conversation_submission, "submit_conversation", side_effect=submit)
    metadata_request = outcome in {"metadata", "active"}
    request = AgentRequest.model_validate({**PAYLOAD.request, "metadata": {} if metadata_request else None})

    if outcome == "ambiguous":
        with pytest.raises(RuntimeServiceUnavailableError):
            await runtime_client.forward_northbound_run(request, *ACTOR, fallback=fallback)
    else:
        response = await runtime_client.forward_northbound_run(request, *ACTOR, fallback=fallback)
        if outcome == "active":
            assert response.status_code == 200 and response.headers["X-Stream-Status"] == "conflict"
            frames = [chunk async for chunk in response.body_iterator]
            assert len(frames) == 1 and frames[0].startswith('data: {"type": "error"')
        else:
            assert response is (fallback.return_value if outcome == "unsupported" else prepared)

    assert start.await_count == 1
    assert start.await_args.kwargs.get("metadata_from_northbound", False) == metadata_request
    assert release.await_count == (1 if outcome == "unsupported" else 0)
    assert fallback.await_count == (1 if outcome == "unsupported" else 0)


@pytest.mark.asyncio
async def test_northbound_translates_and_closes_legacy_admission_conflict(mocker):
    from starlette.background import BackgroundTask

    close = AsyncMock()
    runtime_response = StreamingResponse(
        iter(()), status_code=409, headers={"X-Stream-Status": "conflict"}, background=BackgroundTask(close),
    )
    mocker.patch.object(runtime_client, "forward_conversation_run", return_value=runtime_response)

    response = await runtime_client.forward_northbound_run(
        AgentRequest(query="hello", conversation_id=42, agent_id=7), *ACTOR, fallback=AsyncMock(),
    )

    assert response.status_code == 200
    assert len([frame async for frame in response.body_iterator]) == 1
    close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_northbound_stop_fences_pending_run_without_legacy_stop(mocker):
    pending = SimpleNamespace(reference=REFERENCE, user_id=ACTOR[0], tenant_id=ACTOR[1])
    find = mocker.patch.object(prepared_turn, "find_pending_turn", return_value=pending)
    client = SimpleNamespace(
        stop=AsyncMock(), stop_run=AsyncMock(return_value=SimpleNamespace(cancellation_requested=True)),
    )
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)

    result = await runtime_client.forward_agent_stop(REFERENCE.conversation_id, *ACTOR)

    find.assert_awaited_once_with(REFERENCE.conversation_id, *ACTOR)
    client.stop_run.assert_awaited_once_with(AgentStop(**REFERENCE.model_dump(), prevent_start=True), *ACTOR)
    client.stop.assert_not_awaited()
    assert result["message"] == "successfully stopped agent run for user_id actor, run_id 42"


@pytest.mark.asyncio
async def test_northbound_stop_targets_registered_run_without_legacy_stop(mocker):
    mocker.patch.object(prepared_turn, "find_pending_turn", return_value=None)
    client = SimpleNamespace(
        find_active_run=AsyncMock(return_value=REFERENCE.run_id), stop=AsyncMock(),
        stop_run=AsyncMock(return_value=SimpleNamespace(cancellation_requested=True)),
    )
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)

    result = await runtime_client.forward_agent_stop(REFERENCE.conversation_id, *ACTOR)

    client.find_active_run.assert_awaited_once_with(REFERENCE.conversation_id, *ACTOR)
    client.stop_run.assert_awaited_once_with(AgentStop(**REFERENCE.model_dump()), *ACTOR)
    client.stop.assert_not_awaited()
    assert result == {"status": "success", "message": "successfully stopped agent run for user_id actor, run_id 42"}


@pytest.mark.asyncio
@pytest.mark.parametrize("northbound", [False, True])
async def test_prepared_turn_stages_metadata_and_keeps_the_snapshot_version_header(flow, northbound):
    operations, compile_snapshot, client, _ = flow
    request = AgentRequest.model_validate({**PAYLOAD.request, "metadata": {}})

    response = await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, client, metadata_from_northbound=northbound)

    assert operations == ["stage", "start", "confirm"]
    assert compile_snapshot.await_args.kwargs.get("metadata_from_northbound", False) is northbound
    assert prepared_turn.store.stage_turn.call_args.args[5]["metadata_update"] == {
        "expected_version": 1, "value": {},
    }
    assert response.headers["X-Runtime-Metadata-Version"] == "2"
    await response.body_iterator.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("northbound", [False, True])
async def test_metadata_conflict_after_admission_fences_the_run(flow, northbound):
    operations, _, client, _ = flow
    prepared_turn.store.confirm_turn.side_effect = RuntimeMetadataVersionConflict(8)
    client.stop_run = AsyncMock()
    request = AgentRequest.model_validate({**PAYLOAD.request, "metadata": {"project": "new"}})

    with pytest.raises(AppException) as error:
        await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, client, metadata_from_northbound=northbound)

    assert error.value.error_code == ErrorCode.CHAT_METADATA_VERSION_CONFLICT
    assert error.value.details == {"current_version": 8}
    client.stop_run.assert_awaited_once_with(AgentStop(**REFERENCE.model_dump(), prevent_start=True), *ACTOR)
    assert operations == ["stage", "start", "close"]
    client.resume.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_discards_run_stopped_before_runtime_admission(flow):
    operations, _, client, staged = flow
    client.inspect_run = AsyncMock(return_value=SimpleNamespace(
        **REFERENCE.model_dump(), status="stopped", latest_event_id=None,
        cancellation_requested=True, resource_versions=None,
    ))
    await prepared_turn.reconcile_turn(staged, client)
    assert operations == ["close"]
    client.resume.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", ["configuration", "metadata"])
async def test_workbench_stale_revision_rejects_before_runtime(mocker, stale):
    from fastapi import HTTPException

    from contracts.agent import WorkbenchSessionConfig

    config = WorkbenchSessionConfig(mode="generic_chat")
    request = AgentRequest(
        query="question", entrypoint="workbench", conversation_id=REFERENCE.conversation_id,
        workbench=config, expected_workbench_config_version=1 if stale == "configuration" else 2,
        metadata={}, expected_metadata_version=3,
    )
    mocker.patch.object(prepared_turn, "get_conversation", return_value={
        "workbench_config": config.model_dump(mode="json"), "workbench_config_version": 2,
        "runtime_metadata_version": 4,
    })

    async def inline(_name, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    mocker.patch.object(prepared_turn, "_io", side_effect=inline)
    reject = mocker.patch.object(prepared_turn, "reject_unstaged_turn")
    client = SimpleNamespace(start_prepared_run=AsyncMock())
    if stale == "configuration":
        with pytest.raises(HTTPException) as error:
            await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, client)
        assert error.value.status_code == 409
        assert error.value.detail == {"code": "WORKBENCH_CONFIG_VERSION_CONFLICT", "current_version": 2}
    else:
        with pytest.raises(AppException) as error:
            await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, client)
        assert error.value.error_code == ErrorCode.CHAT_METADATA_VERSION_CONFLICT
        assert error.value.details == {"current_version": 4}
    reject.assert_awaited_once_with(PAYLOAD, *ACTOR)
    client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_unsupported_workbench_uses_unchanged_compatibility_request(mocker):
    from management.services.agent import conversation_submission

    payload = CompatibilityConversationRun(request={
        "query": "question", "entrypoint": "workbench", "workbench": {"mode": "generic_chat"},
    })
    response = StreamingResponse(iter(()))
    client = SimpleNamespace(run_conversation=AsyncMock(return_value=response))
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)
    mocker.patch.object(prepared_turn, "start_turn", return_value=None)
    reject = mocker.patch.object(prepared_turn, "reject_unstaged_turn")

    async def submit(claimed, owner, tenant, dispatch, *, include_claim_headers):
        assert not include_claim_headers
        assert claimed.idempotency_key.startswith("prepared-")
        return await dispatch(claimed.model_copy(update={"claimed_run_id": REFERENCE.run_id}), owner, tenant)

    mocker.patch.object(conversation_submission, "submit_conversation", side_effect=submit)
    assert await runtime_client.forward_conversation_run(payload, *ACTOR) is response
    assert reject.await_args.args[0].claimed_run_id == REFERENCE.run_id
    client.run_conversation.assert_awaited_once_with(payload.model_copy(update={"preparation": "legacy"}), *ACTOR)


@pytest.mark.asyncio
async def test_native_knowledge_scope_conflict_cancels_the_admitted_run(flow, mocker):
    operations, compile_snapshot, client, _ = flow
    old_scope = {"schema_version": 1, "local": {"mode": "inherit", "knowledge_ids": []}}
    request = AgentRequest.model_validate({**PAYLOAD.request, "knowledge_scope": {"local": {"mode": "disabled"}}})
    desired = request.knowledge_scope.model_dump(mode="json")
    prepared_turn.get_conversation.return_value = {"knowledge_scope": old_scope}
    native = SimpleNamespace(resolution=SimpleNamespace(desired_scope=desired))
    mocker.patch.object(prepared_turn, "prepare_native_knowledge", return_value=native)
    prepared_turn.store.confirm_turn.side_effect = prepared_turn.store.PreparedTurnConflict()
    client.stop_run = AsyncMock()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, client)

    assert error.value.status_code == 409
    assert compile_snapshot.await_args.kwargs["native_knowledge"] is native
    assert prepared_turn.store.stage_turn.call_args.args[5]["knowledge_update"] == {
        "expected": old_scope, "value": desired,
    }
    client.stop_run.assert_awaited_once_with(AgentStop(**REFERENCE.model_dump(), prevent_start=True), *ACTOR)
    assert operations == ["stage", "start", "close"]
