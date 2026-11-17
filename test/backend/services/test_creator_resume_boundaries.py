# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Creator replay rejects gaps and cannot finalize another generation's turn."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from management.services.conversation import creator_runtime as runtime
from test.backend.services.test_creator_session_recovery import store  # noqa: F401


def unit(index):
    return {"unit_index": index, "unit_type": "final_answer", "unit_content": str(index)}


def frame(index):
    return "data: " + json.dumps({"type": "final_answer", "unit_index": index, "content": str(index)}) + "\n\n"


@pytest.fixture
def replay(store, monkeypatch):
    store.rows.append({
        "message_id": 2, "role": "assistant", "message_index": 1,
        "message_content": "", "status": "streaming", "units": [],
    })
    store.state.enabled = True
    store.state.get_run_state_async.return_value = {"generation": "old", "status": "running"}
    store.state.wait_for_stream_events_async = AsyncMock()
    store.state.mark_run_finished = MagicMock()
    channel = MagicMock(return_value=None)
    monkeypatch.setattr(runtime.streaming_channel_manager, "get_channel", channel)

    async def inline(_name, function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(runtime, "run_blocking", inline)
    return store


async def read(store):
    stream = await runtime.resume_creator(91, store.user)
    return [json.loads(chunk[6:]) async for chunk in stream]


@pytest.mark.asyncio
async def test_resume_without_an_assistant_cannot_start_a_new_turn(store):
    with pytest.raises(ValueError, match="no answer to resume"):
        await runtime.resume_creator(91, store.user)
    assert store.rows == []


@pytest.mark.asyncio
async def test_terminal_remote_run_drains_checkpoint_lag_without_marking_interrupted(replay, monkeypatch):
    replay.state.get_run_state_async.return_value = {"generation": "old", "status": "completed"}
    monkeypatch.setattr(runtime, "get_message_units", MagicMock(side_effect=[[], [unit(0)]]))
    output = await read(replay)
    assert [event["content"] for event in output] == ["0"]
    replay.state.creator_lease_async.assert_not_awaited()
    replay.state._run_managed.assert_not_awaited()


@pytest.mark.asyncio
async def test_remote_replay_tracks_stream_cursor_and_drains_terminal_checkpoint(replay, monkeypatch):
    replay.state.get_run_state_async.side_effect = [
        {"generation": "old", "status": "running"},
        {"generation": "old", "status": "running"},
        {"generation": "old", "status": "completed"},
    ]
    replay.state.wait_for_stream_events_async.side_effect = [
        [("1-0", ": ping\n" + frame(0))],
        [("2-0", frame(1))],
    ]
    monkeypatch.setattr(runtime, "get_message_units", MagicMock(side_effect=[[], [unit(0), unit(1), unit(2)]]))
    output = await read(replay)
    assert [event["unit_index"] for event in output] == [0, 1, 2]
    assert [event["content"] for event in output] == ["0", "1", "2"]
    assert [call.args[-1] for call in replay.state.wait_for_stream_events_async.await_args_list] == ["0-0", "1-0"]
    replay.state._run_managed.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("during_interruption", [False, True])
async def test_new_generation_cannot_be_marked_failed_by_an_old_subscriber(replay, monkeypatch, during_interruption):
    replay.state.creator_lease_async.return_value = not during_interruption
    replay.state.get_run_state_async.side_effect = [
        {"generation": "old", "status": "running"},
        {"generation": "new", "status": "running"},
    ]
    persist = MagicMock()
    monkeypatch.setattr(runtime, "checkpoint_creator_message", persist)
    assert await read(replay) == []
    persist.assert_not_called()
    replay.state._run_managed.assert_not_awaited()
    replay.state.wait_for_stream_events_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_checkpoint_winning_the_lock_is_not_overwritten_as_failed(replay, monkeypatch):
    replay.state.creator_lease_async.return_value = False
    persist = MagicMock(side_effect=ValueError("answer already finalized"))
    monkeypatch.setattr(runtime, "checkpoint_creator_message", persist)
    assert await read(replay) == []
    persist.assert_called_once()
    replay.state._run_managed.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("saved,live_index,error", [
    ([unit(0), unit(2)], 3, "checkpoint has a gap"),
    ([unit(0)], 2, "buffer is incomplete"),
])
async def test_missing_durable_units_are_reported_instead_of_silently_skipped(replay, monkeypatch, saved, live_index, error):
    async def tail(_cursor):
        yield frame(live_index)

    channel = SimpleNamespace(history_start_index=7, subscribe_with_history=tail)
    monkeypatch.setattr(runtime.streaming_channel_manager, "get_channel", lambda *_: channel)
    monkeypatch.setattr(runtime, "get_message_units", MagicMock(side_effect=[[unit(0)], saved]))
    with pytest.raises(RuntimeError, match=error):
        await read(replay)
    replay.state._run_managed.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_local_tail_drains_late_checkpoints_and_deduplicates_frames(replay, monkeypatch):
    async def tail(cursor):
        assert cursor == 7
        yield ": ping\n" + frame(0) + frame(0)

    channel = SimpleNamespace(history_start_index=7, subscribe_with_history=tail)
    monkeypatch.setattr(runtime.streaming_channel_manager, "get_channel", lambda *_: channel)
    monkeypatch.setattr(runtime, "get_message_units", MagicMock(side_effect=[[], [unit(0), unit(1)]]))
    output = await read(replay)
    assert [event["unit_index"] for event in output] == [0, 1]
    assert [event["content"] for event in output] == ["0", "1"]
    replay.state._run_managed.assert_not_awaited()


@pytest.mark.asyncio
async def test_interruption_drains_committed_units_before_appending_the_error(replay, monkeypatch):
    replay.rows[-1].update(units=[unit(0), unit(1)], message_content="01")
    replay.state.creator_lease_async.return_value = False
    monkeypatch.setattr(runtime, "get_message_units", MagicMock(side_effect=[[], [unit(0), unit(1)]]))
    output = await read(replay)
    assert [event["unit_index"] for event in output] == [0, 1, 2]
    assert [event["content"] for event in output[:2]] == ["0", "1"]
    assert output[-1]["type"] == "error"
    assert replay.rows[-1]["status"] == "failed"
    assert [unit["unit_index"] for unit in replay.rows[-1]["units"]] == [0, 1, 2]
    assert replay.state._run_managed.await_args.args[-1] == "old"

