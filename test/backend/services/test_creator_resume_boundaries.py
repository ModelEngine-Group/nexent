# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Creator replay rejects gaps and cannot finalize another generation's turn."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, call

import pytest

from contracts.agent import NL2AgentRunRequest, SystemAgentRef
from contracts.errors.exceptions import RuntimeCoordinationUnavailableError
from management.services.conversation import creator_execution as execution
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
    replay.state.wait_for_stream_events_async.return_value = [("1-0", frame(live_index))]
    monkeypatch.setattr(runtime, "get_message_units", MagicMock(side_effect=[[unit(0)], saved]))
    with pytest.raises(RuntimeError, match=error):
        await read(replay)
    replay.state._run_managed.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_remote_tail_drains_late_checkpoints_and_deduplicates_frames(replay, monkeypatch):
    replay.state.get_run_state_async.side_effect = [
        {"generation": "old", "status": "running"},
        {"generation": "old", "status": "completed"},
    ]
    replay.state.wait_for_stream_events_async.return_value = [("1-0", ": ping\n" + frame(0) + frame(0))]
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


@pytest.fixture
def owned_replay(monkeypatch):
    async def inline(_name, function, *args):
        return function(*args)

    state = SimpleNamespace(get_run_state_async=AsyncMock(return_value={}))
    owned = AsyncMock(return_value=("a" * 32, "running", "nl2agent_main"))
    snapshot = AsyncMock(return_value=None)
    history = Mock(return_value={
        "agent_id": 77,
        "target": {"type": "agent", "id": 8},
        "message_records": [
            {"message_id": 100, "role": "assistant"},
            {"message_id": 102, "role": "user"},
            {"message_id": 101, "role": "assistant"},
        ],
    })
    subscriber = Mock()
    monkeypatch.setattr(execution, "uses_durable_agent_admission", lambda: True)
    monkeypatch.setattr(execution, "run_blocking", inline)
    monkeypatch.setattr(execution.system_agent_provider, "get_creator_ref", Mock(
        return_value=SystemAgentRef("shared", "nl2agent_main", 77, 0),
    ))
    monkeypatch.setattr(execution, "get_conversation_service", Mock(return_value={"conversation_id": 91}))
    monkeypatch.setattr(execution, "get_conversation_history", history)
    monkeypatch.setattr(execution, "authorize_target", lambda target, *_: target)
    monkeypatch.setattr(execution, "get_owned_execution", owned)
    monkeypatch.setattr(execution, "read_owned_stream", snapshot)
    monkeypatch.setattr(execution, "runtime_state_service", state)
    monkeypatch.setattr(execution, "resume_owned_creator", subscriber)
    monkeypatch.setattr(execution, "adapt_nexent_stream", lambda stream: stream)
    return SimpleNamespace(state=state, owned=owned, snapshot=snapshot, history=history, subscriber=subscriber)


async def resume_turn(message_id=None):
    return await execution.start_creation_turn(
        NL2AgentRunRequest(query="resume", agent_id=8, conversation_id=91, resume_message_id=message_id),
        kind="agent", user_id="owner", tenant_id="tenant", stream_factory=AsyncMock(), resume=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("message_id", [None, 101])
async def test_active_creator_without_replay_never_falls_back_to_another_answer(owned_replay, message_id):
    if message_id is None:
        with pytest.raises(RuntimeCoordinationUnavailableError, match="replay is not ready"):
            await resume_turn()
    else:
        stream, conversation_id = await resume_turn(message_id)
        assert conversation_id == 91
        assert [chunk async for chunk in stream] == [
            'event: stream_status\ndata: {"status":"stopped","replay_unavailable":true}\n\n',
        ]
    owned_replay.snapshot.assert_awaited_once_with("owner", 91, "a" * 32)
    owned_replay.history.assert_called_once_with(91, "owner")
    owned_replay.subscriber.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("new_owner", [False, True])
async def test_saved_creator_replay_requires_unchanged_execution_ownership(owned_replay, new_owner):
    next_owner = ("b" * 32, "starting", "nl2agent_main") if new_owner else None
    owned_replay.owned.side_effect = [None, next_owner]
    if new_owner:
        with pytest.raises(RuntimeCoordinationUnavailableError, match="changed during lookup"):
            await resume_turn(101)
        owned_replay.subscriber.assert_not_called()
    else:
        stream, conversation_id = await resume_turn(101)
        assert conversation_id == 91 and stream is owned_replay.subscriber.return_value
        owned_replay.subscriber.assert_called_once_with(
            91, "owner", "tenant", None, None, 101, agent_scope="nl2agent_main",
        )
    assert owned_replay.history.call_args_list == [call(91, "owner"), call(91, "owner")]
    owned_replay.snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_terminal_replay_cannot_replace_a_new_creator_run(owned_replay):
    owned_replay.owned.side_effect = [None, ("b" * 32, "running", "nl2agent_main")]
    owned_replay.state.get_run_state_async.return_value = {"generation": "execution:42"}
    owned_replay.snapshot.return_value = {"generation": "execution:42", "terminal_status": "completed"}
    with pytest.raises(RuntimeCoordinationUnavailableError, match="changed during lookup"):
        await resume_turn()
    owned_replay.snapshot.assert_awaited_once_with("owner", 91, 42)
    owned_replay.subscriber.assert_not_called()


@pytest.mark.asyncio
async def test_local_creator_replay_refuses_an_older_message_pin(owned_replay, monkeypatch):
    monkeypatch.setattr(execution, "uses_durable_agent_admission", lambda: False)
    local_replay = AsyncMock()
    monkeypatch.setattr(execution, "resume_creator", local_replay)
    stream, conversation_id = await resume_turn(100)
    assert conversation_id == 91
    assert [chunk async for chunk in stream] == [
        'event: stream_status\ndata: {"status":"stopped","replay_unavailable":true}\n\n',
    ]
    local_replay.assert_not_awaited()
    owned_replay.state.get_run_state_async.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint", [None, {"entries": [json.loads(frame(0)[6:])], "cursor": "1-0"}])
async def test_terminal_creator_replay_reads_saved_units_only_without_a_checkpoint(replay, monkeypatch, checkpoint):
    lookup = Mock(return_value=[unit(0)])
    monkeypatch.setattr(runtime, "get_message_units", lookup)
    snapshot = {"generation": "old", "checkpoint": checkpoint, "terminal_status": "completed"}
    stream = runtime.resume_owned_creator(91, "owner", "tenant", "old", snapshot, 2, agent_scope="nl2agent_main")
    events = [json.loads(chunk[6:]) async for chunk in stream]
    assert [(event["type"], event["unit_index"], event["content"]) for event in events] == [("final_answer", 0, "0")]
    if checkpoint is None:
        lookup.assert_called_once_with(2)
    else:
        lookup.assert_not_called()
    replay.state.creator_lease_async.assert_not_awaited()
    replay.state.wait_for_stream_events_async.assert_not_awaited()
