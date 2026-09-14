"""Presentation events must not restart or stall the running Agent iterator."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from services.human_interaction.stream import stream_with_guidance


@pytest.mark.asyncio
async def test_guidance_is_visible_during_a_blocked_agent_call_and_not_duplicated():
    resume = asyncio.Event()
    inputs = []
    starts = []

    async def source():
        starts.append(True)
        await resume.wait()
        yield 'completed-agent-chunk'

    port = SimpleNamespace(visible_guidance=lambda: list(inputs))
    stream = stream_with_guidance(source(), port, poll_seconds=0.01)
    first = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    inputs.append({"request_id": "first", "text": "First guidance", "created_at": "2026-09-14T12:00:00Z"})
    event = json.loads(await asyncio.wait_for(first, 2))
    assert event["type"] == "user_steering"
    assert json.loads(event["content"])["text"] == "First guidance"
    assert not resume.is_set()
    inputs.append({"request_id": "second", "text": "Second guidance", "created_at": "2026-09-14T12:00:01Z"})
    event = json.loads(await asyncio.wait_for(anext(stream), 2))
    assert json.loads(event["content"])["request_id"] == "second"
    resume.set()
    assert [chunk async for chunk in stream] == ['completed-agent-chunk']
    assert starts == [True]


@pytest.mark.asyncio
async def test_stream_checks_guidance_at_completion_without_querying_for_every_token():
    reads = []
    inputs = []

    def visible_guidance():
        reads.append(True)
        return inputs

    async def source():
        for index in range(200):
            yield str(index)
        inputs.append({"request_id": "last", "text": "Accepted before completion", "created_at": "now"})

    chunks = [chunk async for chunk in stream_with_guidance(
        source(), SimpleNamespace(visible_guidance=visible_guidance), poll_seconds=10,
    )]
    assert chunks[:200] == [str(index) for index in range(200)]
    assert json.loads(json.loads(chunks[-1])["content"])["request_id"] == "last"
    assert len(reads) == 2


@pytest.mark.asyncio
async def test_closing_guidance_stream_closes_its_pending_iterator():
    started = asyncio.Event()
    closed = asyncio.Event()

    async def source():
        try:
            started.set()
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            closed.set()

    stream = stream_with_guidance(source(), SimpleNamespace(visible_guidance=list), poll_seconds=0.01)
    pending = asyncio.create_task(anext(stream))
    await asyncio.wait_for(started.wait(), 2)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert closed.is_set()


@pytest.mark.asyncio
async def test_durable_event_ids_allow_replay_without_skipping_snapshot_backlog(monkeypatch):
    from unittest.mock import MagicMock
    from services.human_interaction import application

    snapshot = {"run_id": "run", "conversation_id": 7, "status": "COMPLETED", "event_seq": 3}
    service = MagicMock()
    service.snapshot.return_value = snapshot
    service.repository.events.return_value = [
        {"seq": 2, "payload": {"type": "human_decision", "content": {"status": "DECIDED"}}},
        {"seq": 3, "payload": {"chunk_cipher": "encrypted"}},
    ]
    service.cipher.open.return_value = 'data: {"type":"final_answer","content":"done"}\n\n'
    monkeypatch.setattr(application, "require_enabled", lambda: service)
    response = await application.stream_run("run", "tenant", "owner", after=1)
    chunks = [chunk async for chunk in response.body_iterator]
    assert chunks[0].startswith("data: ")
    assert not chunks[0].startswith("id:")
    assert chunks[1].startswith("id: 2\ndata: ")
    assert chunks[2] == 'id: 3\ndata: {"type":"final_answer","content":"done"}\n\n'
    assert chunks[-1].startswith("data: ")
    service.repository.events.assert_called_once_with("run", 1)
    assert all(call.args == ("run", "tenant", "owner") for call in service.snapshot.call_args_list)


@pytest.mark.asyncio
async def test_future_event_cursor_is_rejected_before_streaming(monkeypatch):
    from unittest.mock import MagicMock
    from services.human_interaction import application
    from services.human_interaction.models import InteractionError

    service = MagicMock()
    service.snapshot.return_value = {"event_seq": 3}
    monkeypatch.setattr(application, "require_enabled", lambda: service)
    with pytest.raises(InteractionError) as error:
        await application.stream_run("run", "tenant", "owner", after=4)
    assert error.value.status_code == 422
    service.repository.events.assert_not_called()
