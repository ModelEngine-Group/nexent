# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from contextlib import aclosing
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from contracts.agentos import AgentResume, CompatibilityConversationRun
from management.services.agent import agentos_events as public_events
from management.services.agent import runtime_client


CURSOR = AgentResume(conversation_id=42, run_id="a" * 32, after_event_id=f"{'a' * 32}:1")


def observer(index, payload):
    return f"id: {CURSOR.run_id}:{index}\nevent: agentos_observer\ndata: {json.dumps(payload)}\n\n".encode()


def response(*chunks, status_code=200):
    async def body():
        for chunk in chunks:
            yield chunk

    return StreamingResponse(body(), status_code=status_code, headers={"X-AgentOS-Run-ID": CURSOR.run_id})


@pytest.mark.asyncio
async def test_public_resume_adapts_only_prepared_frames_and_retains_the_cursor(mocker):
    legacy = b"event: stream_status\ndata: old\n\n"
    event = observer(2, {"type": "final_answer", "content": "answer"})
    terminal = f'id: {CURSOR.run_id}:3\nevent: agentos_terminal\ndata: {{"status":"completed"}}\n\n'.encode()
    source = response(legacy + event[:7], event[7:] + b": keep-alive\n\n" + terminal)
    resume = AsyncMock(return_value=source)
    mocker.patch.object(runtime_client, "_agentos_client").return_value.resume = resume

    output = await runtime_client.forward_conversation_resume(CURSOR, "actor", "tenant")

    assert output.headers["X-AgentOS-Run-ID"] == CURSOR.run_id
    assert b"".join([chunk async for chunk in output.body_iterator]) == (
        legacy + event.replace(b"event: agentos_observer\n", b"") + b": keep-alive\n\n" + terminal
    )
    resume.assert_awaited_once_with(CURSOR, "actor", "tenant")


@pytest.mark.asyncio
async def test_public_resume_keeps_upstream_cursor_failure_unchanged(mocker):
    source = response(b'{"detail":{"code":"AGENTOS_CURSOR_UNAVAILABLE"}}', status_code=410)
    mocker.patch.object(runtime_client, "_agentos_client").return_value.resume = AsyncMock(return_value=source)
    assert await runtime_client.forward_conversation_resume(CURSOR, "actor", "tenant") is source


@pytest.mark.asyncio
async def test_public_resume_signs_only_an_output_of_the_scoped_run(mocker):
    scoped = f"workspace/actor/{CURSOR.run_id}/outputs/result.txt"
    payload = {"type": "file_artifact", "content": {"artifacts": [
        {"object_name": scoped, "name": "result.txt", "file_size_bytes": 5,
         "absolute_path": "/runtime/path", "url": "https://untrusted.invalid", "presigned_url": "stale"},
        {"object_name": f"workspace/other/{CURSOR.run_id}/outputs/other.txt"},
        {"object_name": f"workspace/actor/{'b' * 32}/outputs/other.txt"},
        {"object_name": f"workspace/actor/{CURSOR.run_id}/outputs/../foreign.txt"},
    ]}}
    source = response(observer(2, payload))
    signer = mocker.patch.object(public_events, "enrich_file_uploads_with_presigned_urls")

    async def io(_name, fn, artifacts, *, lane, owner):
        assert lane == "control-io" and owner == "management"
        fn(artifacts)
        return [{**artifacts[0], "presigned_url": "new-url"}]

    mocker.patch.object(public_events, "run_blocking", side_effect=io)
    output = public_events.present_public_resume(source, CURSOR, "actor")
    frame = b"".join([chunk async for chunk in output.body_iterator]).decode()

    assert frame.startswith(f"id: {CURSOR.run_id}:2\ndata: ")
    event = json.loads(frame.split("data: ", 1)[1])
    assert event["type"] == "files"
    fields = {"object_name": scoped, "file_name": "result.txt", "file_size": 5, "status": "success"}
    assert json.loads(event["content"]) == {"file_uploads": [{**fields, "presigned_url": "new-url"}]}
    signer.assert_called_once_with([fields])


@pytest.mark.asyncio
@pytest.mark.parametrize("created", [False, True])
async def test_closing_the_public_response_closes_the_upstream_subscription(created):
    closed = []

    async def journal():
        try:
            yield observer(2, {"type": "thought", "content": "step"})
            pytest.fail("Closing the public response consumed another event")
        finally:
            closed.append(True)

    output = public_events.present_public_resume(StreamingResponse(journal()), CURSOR, "actor", created=created)
    iterator = output.body_iterator
    expected = b"conversation_created" if created else b"thought"
    assert expected in await anext(iterator)
    await iterator.aclose()
    assert closed == [True]


@pytest.mark.asyncio
async def test_failed_prepared_turn_presents_an_error_before_the_terminal_frame():
    terminal = f'id: {CURSOR.run_id}:2\nevent: agentos_terminal\ndata: {{"status":"failed"}}\n\n'.encode()
    on_terminal = AsyncMock()
    output = public_events.present_public_resume(response(terminal), CURSOR, "actor", on_terminal=on_terminal)

    frames = [chunk async for chunk in output.body_iterator]

    assert json.loads(frames[0].removeprefix(b"data: "))["type"] == "error"
    assert frames[1:] == [terminal]
    on_terminal.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_ephemeral_frames_preserve_observers_and_only_sign_run_owned_files(mocker):
    scoped = f"workspace/actor/{CURSOR.run_id}/outputs/result.txt"
    frame = lambda event: ("data: " + json.dumps(event) + "\n\n").encode()
    observer_frame = frame({"type": "final_answer", "content": "answer"})
    artifact = frame({"type": "file_artifact", "content": {"artifacts": [
        {"object_name": scoped, "name": "result.txt", "absolute_path": "/runtime/path"},
        {"object_name": f"workspace/other/{CURSOR.run_id}/outputs/foreign.txt"},
    ]}})
    raw_path = frame({"type": "skill_artifact", "content": {"absolute_path": "/runtime/private"}})
    source = response(observer_frame[:7], observer_frame[7:] + artifact + raw_path)
    signer = mocker.patch.object(public_events, "run_blocking", return_value=[{"object_name": scoped, "presigned_url": "url"}])

    output = public_events.present_ephemeral_stream(source, "actor", CURSOR.run_id)
    chunks = [chunk async for chunk in output.body_iterator]
    assert chunks[0] == observer_frame and len(chunks) == 2
    assert json.loads(json.loads(chunks[1][6:])["content"]) == {
        "file_uploads": [{"object_name": scoped, "presigned_url": "url"}],
    }
    assert signer.await_args.args[2] == [{"object_name": scoped, "file_name": "result.txt", "status": "success"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["unsupported", "unavailable"])
async def test_a2a_falls_back_only_before_prepared_dispatch(mocker, mode):
    from types import SimpleNamespace

    from contracts.agent import AgentRequest
    from contracts.errors.exceptions import RuntimeServiceUnavailableError
    from management.services.agent.preparation import evaluation_snapshot

    request = AgentRequest(query="query", agent_id=7, version_no=2, is_debug=True)
    snapshot = SimpleNamespace(run_id=CURSOR.run_id) if mode == "unavailable" else None
    mocker.patch.object(evaluation_snapshot, "prepare_a2a_snapshot", return_value=snapshot)
    fallback = mocker.patch.object(runtime_client, "forward_agent_run", return_value=response())
    client = mocker.patch.object(runtime_client, "_agentos_client").return_value
    client.run_ephemeral = AsyncMock(side_effect=RuntimeServiceUnavailableError("lost response"))
    if mode == "unsupported":
        assert await runtime_client.forward_a2a_run(request, "actor", "tenant") is fallback.return_value
        client.run_ephemeral.assert_not_awaited()
    else:
        with pytest.raises(RuntimeServiceUnavailableError):
            await runtime_client.forward_a2a_run(request, "actor", "tenant")
        client.run_ephemeral.assert_awaited_once_with(snapshot, "actor", "tenant")
        fallback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["prepared", "unsupported", "denied", "upstream_error"])
async def test_public_debug_selects_agentos_before_compatibility(mocker, mode):
    from fastapi import HTTPException

    from contracts.agentos import CompatibilityConversationRun
    from contracts.errors.exceptions import RuntimeServiceUnavailableError
    from management.services.agent.preparation import evaluation_snapshot

    payload = CompatibilityConversationRun(request={"agent_id": 7, "query": "hello", "is_debug": True}, language="en")
    snapshot = SimpleNamespace(run_id=CURSOR.run_id)
    prepared = SimpleNamespace(payload=snapshot, knowledge=None, workbench=None)
    compile_debug = mocker.patch.object(evaluation_snapshot, "prepare_debug_snapshot", create=True, new_callable=AsyncMock)
    compile_debug.return_value = None if mode == "unsupported" else prepared
    upstream = response(b'data: {"type":"final_answer","content":"answer"}\n\n')
    client = mocker.patch.object(runtime_client, "_agentos_client").return_value
    client.run_ephemeral = AsyncMock(return_value=upstream)
    client.run_conversation = AsyncMock(return_value=upstream)
    if mode == "denied":
        compile_debug.side_effect = HTTPException(status_code=403)
        with pytest.raises(HTTPException) as exc:
            await runtime_client.forward_conversation_run(payload, "actor", "tenant")
        assert exc.value.status_code == 403
    elif mode == "upstream_error":
        client.run_ephemeral.side_effect = RuntimeServiceUnavailableError("lost response")
        with pytest.raises(RuntimeServiceUnavailableError):
            await runtime_client.forward_conversation_run(payload, "actor", "tenant")
    else:
        result = await runtime_client.forward_conversation_run(payload, "actor", "tenant")
        assert result.status_code == 200

    if mode == "unsupported":
        client.run_conversation.assert_awaited_once_with(payload, "actor", "tenant")
    else:
        client.run_conversation.assert_not_awaited()
    if mode in {"prepared", "upstream_error"}:
        client.run_ephemeral.assert_awaited_once_with(snapshot, "actor", "tenant")
    else:
        client.run_ephemeral.assert_not_awaited()


@pytest.mark.asyncio
async def test_debug_scope_precedes_observers_and_disconnect_closes_runtime():
    closed = False

    async def body():
        nonlocal closed
        try:
            yield b": agentos-ready\n\n"
            raise AssertionError("The browser disconnected before reading the model stream")
        finally:
            closed = True

    source = StreamingResponse(body())
    event = {"type": "knowledge_scope_resolved", "content": {"warnings": []}}
    output = public_events.present_ephemeral_stream(source, "actor", CURSOR.run_id, opening_events=[event])
    async with aclosing(output.body_iterator) as events:
        assert json.loads((await anext(events))[6:]) == event
    assert closed


@pytest.mark.asyncio
async def test_debug_scope_does_not_mask_runtime_rejection():
    source = response(b'{"code":"AGENTOS_RESOURCE_UNSUPPORTED"}', status_code=422)
    event = {"type": "knowledge_scope_resolved", "content": {"warnings": []}}
    assert public_events.present_ephemeral_stream(source, "actor", CURSOR.run_id, opening_events=[event]) is source


@pytest.mark.asyncio
@pytest.mark.parametrize("image,status", [(False, 200), (True, 200), (True, 422), (True, None)])
async def test_workbench_debug_skill_grant_wraps_runtime_preparation(mocker, image, status):
    from contracts.agent import WorkbenchSessionConfig
    from contracts.errors.exceptions import RuntimeServiceUnavailableError

    scope_calls = []
    prepare = SimpleNamespace(
        payload=SimpleNamespace(
            run_id=CURSOR.run_id, resource=SimpleNamespace(
                agent_id=7, version_no=3, workbench_skill_refs=[object()],
                tools=[SimpleNamespace(tool_id="ind_aidp_search", version="4")] if image else [],
            ),
        ),
        workbench=WorkbenchSessionConfig(mode="generic_chat", skill_mounts=[{"skill_id": 5}]),
    )

    async def grant_io(_task, function, *args, **kwargs):
        scope_calls.append((function, args))

    mocker.patch.object(runtime_client, "run_blocking", side_effect=grant_io)

    async def dispatch(payload, user, tenant):
        assert payload is prepare.payload
        assert len(scope_calls) == 1
        fn, (scope, actor, mounts) = scope_calls[0]
        assert fn is runtime_client.open_workbench_debug_grant
        assert (scope.run_id, scope.agent_id, scope.agent_version) == (CURSOR.run_id, 7, 3)
        assert (actor.user_id, actor.tenant_id) == (user, tenant)
        assert mounts.mounts[0].skill_id == 5
        if status is None:
            raise RuntimeServiceUnavailableError("upstream failed")
        return result

    result = response(b"data: {}\n\n", status_code=status or 500)
    client = SimpleNamespace(run_ephemeral=dispatch)
    if status is None:
        with pytest.raises(RuntimeServiceUnavailableError):
            await runtime_client._run_prepared_debug(client, prepare, "actor", "tenant")
    else:
        assert await runtime_client._run_prepared_debug(client, prepare, "actor", "tenant") is result
    if image and status == 200:
        assert scope_calls[1:] == []
    else:
        assert scope_calls[1:] == [(runtime_client.close_workbench_debug_grant, (CURSOR.run_id,))]


@pytest.mark.asyncio
@pytest.mark.parametrize("resume,is_debug", [(False, False), (False, True), (True, False)])
async def test_disabled_workbench_is_rejected_before_legacy_dispatch(mocker, resume, is_debug):
    mocker.patch.object(runtime_client, "ENABLE_AGENT_WORKBENCH", False)
    client = mocker.patch.object(runtime_client, "_agentos_client")
    payload = CompatibilityConversationRun(
        request={
            "entrypoint": "workbench",
            "query": "hello",
            "conversation_id": 42 if resume else None,
            "is_debug": is_debug,
            "workbench": {"mode": "generic_chat", "model_id": 1},
        },
        resume=resume,
    )

    with pytest.raises(HTTPException) as error:
        await runtime_client.forward_conversation_run(payload, "actor", "tenant")

    assert error.value.status_code == 404
    assert error.value.detail == {"code": "WORKBENCH_DISABLED"}
    client.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("result", ["completed", "running", "missing", "wrong_run", "wrong_conversation", "no_message"])
async def test_background_recovers_only_matching_completed_run_after_lost_response(mocker, result):
    from contracts.agent import AgentRequest
    from contracts.agentos import AgentRunLookup
    from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeUpstreamError

    original_error = RuntimeServiceTimeoutError("lost response")
    client = mocker.patch.object(runtime_client, "_agentos_client").return_value
    client.run_tracked_background = AsyncMock(side_effect=original_error)
    client.inspect_run = AsyncMock(return_value=SimpleNamespace(
        run_id="b" * 32 if result == "wrong_run" else CURSOR.run_id,
        conversation_id=43 if result == "wrong_conversation" else CURSOR.conversation_id,
        status="running" if result == "running" else "completed",
        assistant_message_id=None if result == "no_message" else 81,
    ))
    if result == "missing":
        client.inspect_run.side_effect = RuntimeUpstreamError(status_code=404, content=b"", headers={})
    request = AgentRequest(query="scheduled", conversation_id=CURSOR.conversation_id, agent_id=7)

    if result == "completed":
        recovered = await runtime_client.forward_tracked_background(request, CURSOR.run_id, "actor", "tenant")
        assert recovered.model_dump() == {
            "run_id": CURSOR.run_id, "conversation_id": CURSOR.conversation_id, "assistant_message_id": 81, "chunks": 0,
        }
    else:
        with pytest.raises(RuntimeServiceTimeoutError) as error:
            await runtime_client.forward_tracked_background(request, CURSOR.run_id, "actor", "tenant")
        assert error.value is original_error

    assert client.run_tracked_background.await_count == 1
    client.inspect_run.assert_awaited_once_with(
        AgentRunLookup(run_id=CURSOR.run_id, conversation_id=CURSOR.conversation_id), "actor", "tenant",
    )
