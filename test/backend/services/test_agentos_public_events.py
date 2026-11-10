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
async def test_closing_the_public_response_closes_the_upstream_subscription():
    closed = []

    async def journal():
        try:
            yield observer(2, {"type": "thought", "content": "step"})
            pytest.fail("Closing the public response consumed another event")
        finally:
            closed.append(True)

    output = public_events.present_public_resume(StreamingResponse(journal()), CURSOR, "actor")
    iterator = output.body_iterator
    assert b"thought" in await anext(iterator)
    await iterator.aclose()
    assert closed == [True]
