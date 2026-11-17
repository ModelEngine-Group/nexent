# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared replay drains committed output and fences superseded generations."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from infrastructure.streaming.replay import CompactReplay, replay_after, subscribe_shared_checkpoint


def checkpoint(entries, generation="run", cursor="1-0"):
    return {"generation": generation, "entries": entries, "cursor": cursor}


def decode(frame):
    return json.loads(frame.removeprefix("data: "))


def service(**overrides):
    values = {
        "get_stream_status_async": AsyncMock(return_value={}),
        "get_run_state_async": AsyncMock(return_value={"generation": "run", "status": "running"}),
        "read_replay_checkpoint_async": AsyncMock(),
        "wait_for_stream_events_async": AsyncMock(),
    }
    return SimpleNamespace(**{**values, **overrides})


def test_replay_rejects_a_cursor_from_a_longer_execution():
    with pytest.raises(ValueError, match="another generation"):
        replay_after([], (1, 0))


@pytest.mark.parametrize("raw", ["not-json", "data: [1,2]\n\n"])
def test_replay_preserves_non_object_wire_frames(raw):
    replay = CompactReplay()
    replay.append(raw)
    replay.append('data: {"type":"metric","content":3}\n\n')
    frames, cursor = replay.read_after()
    assert frames[0] == raw
    assert decode(frames[1]) == {"type": "metric", "content": 3}
    assert cursor == (2, 0)
    assert replay.read_after(cursor)[0] == []


@pytest.mark.asyncio
async def test_shared_replay_wakes_and_drains_the_final_delta_without_duplicates():
    first = {"type": "model_output_thinking", "content": "first"}
    second = {"type": "model_output_thinking", "content": "first second"}
    last = {"type": "final_answer", "content": "answer", "answer_phase": "complete"}
    state = service(
        get_stream_status_async=AsyncMock(side_effect=[{}, {"status": "completed"}]),
        read_replay_checkpoint_async=AsyncMock(side_effect=[
            checkpoint([second], cursor="2-0"), checkpoint([second, last], cursor="3-0"),
        ]),
    )
    output = [decode(frame) async for frame in subscribe_shared_checkpoint(
        state, "owner", 91, checkpoint([first]),
    )]
    assert output == [first, {**first, "content": " second"}, last, {"status": "completed"}]
    state.wait_for_stream_events_async.assert_awaited_once_with("owner", 91, "1-0")
    assert state.read_replay_checkpoint_async.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "failed", "stopped"])
@pytest.mark.parametrize("final", [None, checkpoint([{"type": "parse", "content": "foreign"}], "new")])
async def test_terminal_replay_keeps_the_real_outcome_without_reading_a_new_generation(outcome, final):
    state = service(
        get_run_state_async=AsyncMock(return_value={"status": outcome}),
        read_replay_checkpoint_async=AsyncMock(return_value=final),
    )
    output = [decode(frame) async for frame in subscribe_shared_checkpoint(
        state, "owner", 91, checkpoint([]),
    )]
    assert output == [{"status": outcome}]
    state.wait_for_stream_events_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_generation_replaced_during_wait_stops_before_delivering_foreign_output():
    state = service(read_replay_checkpoint_async=AsyncMock(return_value=checkpoint(
        [{"type": "parse", "content": "foreign"}], "new",
    )))
    output = [decode(frame) async for frame in subscribe_shared_checkpoint(
        state, "owner", 91, checkpoint([]),
    )]
    assert output == [{"status": "stopped"}]
    state.get_stream_status_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_checkpoint_after_wait_is_an_error_instead_of_false_completion():
    state = service(read_replay_checkpoint_async=AsyncMock(return_value=None))
    with pytest.raises(RuntimeError, match="no longer available"):
        async for _ in subscribe_shared_checkpoint(state, "owner", 91, checkpoint([])):
            pytest.fail("Missing replay must not synthesize a successful event")
