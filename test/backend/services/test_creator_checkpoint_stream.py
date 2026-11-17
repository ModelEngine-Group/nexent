# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Creator checkpoint framing, terminal truth and cancellation-safe writes."""

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from management.services.conversation import creator_checkpoints as checkpoints


@pytest.fixture
def writes(monkeypatch):
    saved = MagicMock()
    monkeypatch.setattr(checkpoints, "checkpoint_creator_message", saved)

    async def inline(_name, function, *args):
        return function(*args)

    monkeypatch.setattr(checkpoints, "run_blocking", inline)
    return saved


def frame(value):
    return "data: " + json.dumps(value) + "\n\n"


async def source(*events):
    for event in events:
        yield event


def checkpoint(stream):
    return checkpoints.checkpoint_creator_stream(stream, message_id=2, conversation_id=91, user_id="owner")


@pytest.mark.asyncio
async def test_invalid_frames_cannot_allocate_unit_indices_or_hide_valid_output(writes):
    events = source(": heartbeat\ndata: {broken}\ndata: []\ndata: {\"type\":2}\n\n",
                    frame({"type": "final_answer", "content": "valid"}))
    result = [json.loads(chunk[6:]) async for chunk in checkpoint(events)]
    assert result == [{"type": "final_answer", "content": "valid", "unit_index": 0}]
    assert writes.call_args.args[-2:] == ("valid", "completed")
    assert [unit["unit_index"] for unit in writes.call_args.args[3]] == [0]


@pytest.mark.asyncio
async def test_child_terminal_and_unknown_root_outcome_do_not_override_the_parent_answer(writes):
    base = {"schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen", "turn_id": "turn"}
    events = source(
        frame({"type": "final_answer", "content": "root answer"}),
        frame({**base, "type": "run_terminal", "status": "failed", "invocation_id": "child"}),
        frame({**base, "type": "run_terminal", "status": "unknown", "final_content": "foreign"}),
    )
    assert len([item async for item in checkpoint(events)]) == 3
    assert writes.call_args.args[-2:] == ("root answer", "completed")
    assert [unit["unit_index"] for unit in writes.call_args.args[3]] == [0, 1, 2]


@pytest.mark.asyncio
async def test_generator_close_persists_partial_output_as_stopped(writes):
    stream = checkpoint(source(frame({"type": "final_answer", "content": "partial"})))
    await anext(stream)
    await stream.aclose()
    assert writes.call_args.args[-2:] == ("partial", "stopped")
    assert writes.call_args.args[3][0]["unit_content"] == "partial"


@pytest.mark.asyncio
async def test_structured_content_is_saved_as_json_without_losing_card_identity(writes):
    card = {"subtype": "requirement_clarification", "agent_id": 42, "questions": []}
    events = source(
        frame({"type": "nl2a", "content": card}),
        frame({"type": "tool_result", "content": {"result": 1}}),
    )
    output = [json.loads(chunk[6:]) async for chunk in checkpoint(events)]
    assert json.loads(output[0]["content"]) == {**card, "card_id": "2:0"}
    assert output[1]["content"] == {"result": 1}
    saved = [unit for call in writes.call_args_list for unit in call.args[3]]
    assert [unit["unit_index"] for unit in saved] == [0, 1]
    assert json.loads(saved[1]["unit_content"]) == {"result": 1}


@pytest.mark.asyncio
async def test_explicit_error_keeps_the_answer_failed_even_if_more_text_arrives(writes):
    events = source(frame({"type": "error", "content": "service unavailable"}),
                    frame({"type": "final_answer", "content": "partial answer"}))
    assert len([item async for item in checkpoint(events)]) == 2
    assert writes.call_args.args[-2:] == ("partial answer", "failed")
    assert writes.call_args_list[0].args[3][0]["unit_type"] == "error"


@pytest.mark.asyncio
async def test_cancellation_during_a_write_settles_it_before_the_terminal_flush(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    saved = []

    async def database(_name, _function, *args):
        if args[-1] == "streaming":
            entered.set()
            await release.wait()
        saved.append(args)

    monkeypatch.setattr(checkpoints, "run_blocking", database)

    async def consume():
        async for _ in checkpoint(source(frame({"type": "nl2a_state", "content": "state"}))):
            pytest.fail("Cancellation before commit must not publish an uncommitted boundary")

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), timeout=2)
    consumer.cancel()
    await asyncio.sleep(0)
    assert not consumer.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(consumer, timeout=2)
    assert [call[-1] for call in saved] == ["streaming", "stopped"]
    assert [unit["unit_index"] for unit in saved[0][3]] == [0]
    assert saved[1][3] == []

