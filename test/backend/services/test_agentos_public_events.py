# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from unittest.mock import AsyncMock

import pytest
from starlette.responses import StreamingResponse

from contracts.agentos import AgentResume
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
    snapshot = mocker.Mock(run_id=CURSOR.run_id)
    compile_debug = mocker.patch.object(evaluation_snapshot, "prepare_debug_snapshot", create=True, new_callable=AsyncMock)
    compile_debug.return_value = None if mode == "unsupported" else snapshot
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
