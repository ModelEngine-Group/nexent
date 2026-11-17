# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Creator recovery retains the same event meaning across every replay source."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from infrastructure.creator_events import CreatorAnswer, creator_event_content, unit_event, unpack_creator_event
from infrastructure.nexent_output import normalize_nexent_history
from infrastructure.streaming.channels import StreamingChannel
from management.services.conversation import creator_checkpoints as checkpoints
from management.services.conversation import creator_runtime as runtime
from test.backend.services.test_creator_session_recovery import store  # noqa: F401


def frame(event):
    return "data: " + json.dumps(event) + "\n\n"


def saved(index, event):
    return {"unit_index": index, "unit_type": event["type"],
            "unit_content": creator_event_content(event, event.get("content", ""))}


@pytest.mark.parametrize("kind", ["final_answer", "model_output_thinking", "summary", "parse"])
@pytest.mark.parametrize("phase", ["delta", "complete"])
def test_checkpoint_roundtrip_keeps_protocol_fields_and_history_body(kind, phase):
    event = {"type": kind, "content": '{"type":"final_answer","content":"literal JSON"}',
             "answer_phase": phase, "step_id": "step", "attempt_id": "attempt",
             "answer_preview": True, "reclassify_step": True, "invocation_id": "child"}
    unit = saved(3, event)
    assert unit_event(unit) == {**event, "unit_index": 3}
    projected, _ = normalize_nexent_history(
        [{"type": kind, "content": unit["unit_content"], "unit_index": 3}], "streaming"
    )
    assert projected == [{**event, "unit_index": 3}]


@pytest.mark.parametrize("text", ['{"type":"final_answer","content":"ordinary"}',
                                      '{"creator_event_version":2,"event":{"type":"final_answer"}}'])
def test_ordinary_json_answers_are_not_mistaken_for_saved_events(text):
    assert unpack_creator_event(text, "final_answer") is None
    assert unit_event(saved(0, {"type": "final_answer", "content": text}))["content"] == text


def test_legacy_answer_fragments_keep_delta_and_saved_attempt_identity():
    context = {}
    begin = {"type": "model_attempt_control", "phase": "begin", "step_id": "third", "attempt_id": "a"}
    unit_event(saved(0, begin), context)
    parts = [unit_event(saved(i + 1, {"type": "final_answer", "content": text}), context)
             for i, text in enumerate(["Naming paused. ", "Choose another name. ", "Then continue."])]
    assert "".join(p["content"] for p in parts) == "Naming paused. Choose another name. Then continue."
    assert all(p["answer_phase"] == "delta" and p["step_id"] == "third" and p["attempt_id"] == "a" for p in parts)
    confirmed = unit_event(saved(4, {"type": "final_answer", "content": "", "answer_phase": "complete"}))
    assert confirmed["answer_phase"] == "complete" and confirmed["content"] == ""


@pytest.fixture
def recovery(store, monkeypatch):
    store.rows.append({"message_id": 2, "role": "assistant", "message_index": 1,
                       "message_content": "", "status": "streaming", "units": []})
    store.state.get_run_state_async.return_value = {"generation": "owned", "status": "running"}
    monkeypatch.setattr(runtime.streaming_channel_manager, "get_channel", lambda *_: None)
    return store


async def read(store):
    stream = await runtime.resume_creator(91, store.user)
    return [json.loads(frame[6:]) async for frame in stream]


@pytest.mark.asyncio
async def test_local_complete_checkpoint_wins_over_database_and_trimmed_tail(recovery, monkeypatch):
    channel = StreamingChannel(91, recovery.user, history_size=1)
    channel.generation = "owned"
    monkeypatch.setattr("infrastructure.streaming.channels.runtime_state_service.append_stream_event_async", AsyncMock())
    events = [{"type": "final_answer", "content": p, "answer_phase": "delta", "step_id": "s"}
              for p in ["first ", "second ", "last"]]
    for i, event in enumerate(events):
        event["unit_index"] = i
        await channel.publish(frame(event))
    channel.complete()
    assert channel.history_size == 1
    monkeypatch.setattr(runtime.streaming_channel_manager, "get_channel", lambda *_: channel)
    database = MagicMock(side_effect=AssertionError("Healthy local replay must not read database units"))
    monkeypatch.setattr(runtime, "get_message_units", database)
    assert await read(recovery) == events
    assert channel._subscribers == 0
    database.assert_not_called()


@pytest.mark.asyncio
async def test_shared_checkpoint_wins_over_database_and_keeps_complete_confirmation(recovery, monkeypatch):
    recovery.state.enabled = True
    events = [{"type": "final_answer", "content": "full answer", "answer_phase": "delta", "unit_index": 0},
              {"type": "final_answer", "content": "", "answer_phase": "complete", "unit_index": 1}]
    checkpoint = {"generation": "owned", "entries": events, "cursor": "2-0"}
    recovery.state.read_replay_checkpoint_async.return_value = checkpoint
    recovery.state.get_stream_status_async = AsyncMock(return_value={"status": "completed"})
    recovery.state.get_run_state_async.return_value = {"generation": "owned", "status": "completed"}
    monkeypatch.setattr(runtime, "get_message_units", MagicMock(side_effect=AssertionError("Unexpected database replay")))
    output = await read(recovery)
    assert output == [*events, {"status": "completed"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["missing", "foreign", "unavailable", "empty", "offline"])
async def test_unusable_shared_checkpoint_falls_back_to_legacy_database(recovery, source):
    recovery.state.enabled = True
    recovery.rows[-1].update(status="completed", units=[saved(0, {"type": "final_answer", "content": "old complete answer"})])
    if source == "foreign":
        recovery.state.read_replay_checkpoint_async.return_value = {"generation": "other", "entries": []}
    elif source == "unavailable":
        recovery.state.read_replay_checkpoint_async.side_effect = RuntimeError("Redis unavailable")
    elif source == "empty":
        recovery.state.read_replay_checkpoint_async.return_value = {"generation": "owned", "entries": []}
    elif source == "offline":
        recovery.state.read_replay_checkpoint_async.side_effect = RedisConnectionError("Redis offline")
    output = await read(recovery)
    assert output[0]["content"] == "old complete answer" and output[0]["answer_phase"] == "delta"


@pytest.mark.asyncio
async def test_disappearing_checkpoint_resumes_durable_suffix_without_duplicates(recovery):
    recovery.state.enabled = True
    first = {"type": "final_answer", "content": "first ", "answer_phase": "delta", "unit_index": 0}
    recovery.state.read_replay_checkpoint_async.side_effect = [
        {"generation": "owned", "entries": [first], "cursor": "1-0"}, None,
    ]
    recovery.state.get_stream_status_async = AsyncMock(return_value={})
    recovery.state.wait_for_stream_events_async = AsyncMock(return_value=[])
    recovery.rows[-1].update(status="completed", units=[saved(0, first), saved(1, {"type": "final_answer", "content": "last", "answer_phase": "delta"})])
    output = await read(recovery)
    assert [p["unit_index"] for p in output] == [0, 1]
    assert "".join(p["content"] for p in output) == "first last"


@pytest.mark.asyncio
async def test_redis_disconnect_mid_replay_uses_the_database_suffix(recovery):
    recovery.state.enabled = True
    first = {"type": "final_answer", "content": "first ", "answer_phase": "delta", "unit_index": 0}
    recovery.state.read_replay_checkpoint_async.side_effect = [
        {"generation": "owned", "entries": [first], "cursor": "1-0"}, RedisConnectionError("Redis offline"),
    ]
    recovery.state.get_stream_status_async = AsyncMock(return_value={})
    recovery.state.wait_for_stream_events_async = AsyncMock(return_value=[])
    recovery.rows[-1].update(status="completed", units=[saved(0, first), saved(1, {"type": "final_answer", "content": "last", "answer_phase": "delta"})])
    output = await read(recovery)
    assert [p["unit_index"] for p in output] == [0, 1]
    assert "".join(p["content"] for p in output) == "first last"


@pytest.mark.asyncio
async def test_actual_checkpoint_generator_preserves_delta_and_complete_semantics(monkeypatch):
    writes = []
    async def write(_name, _function, *args):
        writes.extend(args[3])
    monkeypatch.setattr(checkpoints, "run_blocking", write)
    events = [{"type": "final_answer", "content": "part", "answer_phase": "delta", "step_id": "s"},
              {"type": "final_answer", "content": "", "answer_phase": "complete", "step_id": "s"}]
    async def source():
        for event in events:
            yield frame(event)
    wire = [json.loads(item[6:]) async for item in checkpoints.checkpoint_creator_stream(source(), message_id=2, conversation_id=91, user_id="user")]
    assert [unit_event(unit) for unit in writes] == wire
    assert [e["answer_phase"] for e in wire] == ["delta", "complete"]


def test_persisted_answer_replaces_confirmed_text_and_rolls_back_attempts():
    answer = CreatorAnswer()
    answer.push({"type": "final_answer", "content": "old", "step_id": "first", "answer_phase": "delta"})
    answer.push({"type": "model_attempt_control", "phase": "begin", "attempt_id": "retry"})
    answer.push({"type": "final_answer", "content": "discard", "step_id": "second", "answer_phase": "delta"})
    assert answer.content == "discard"
    answer.push({"type": "model_attempt_control", "phase": "rollback", "attempt_id": "retry"})
    assert answer.content == "old"
    answer.push({"type": "final_answer", "content": "ignored child", "invocation_id": "child"})
    answer.push({"type": "final_answer", "content": "accepted", "answer_phase": "complete"})
    answer.push({"type": "final_answer", "content": "", "answer_phase": "complete"})
    assert answer.content == "accepted"


@pytest.mark.asyncio
async def test_foreign_local_channel_cannot_replace_the_owned_database_answer(recovery, monkeypatch):
    recovery.rows[-1].update(status="completed", units=[saved(0, {"type": "final_answer", "content": "owned"})])
    channel = SimpleNamespace(generation="other", subscribe_with_history=MagicMock())
    monkeypatch.setattr(runtime.streaming_channel_manager, "get_channel", lambda *_: channel)
    assert (await read(recovery))[0]["content"] == "owned"
    channel.subscribe_with_history.assert_not_called()


def test_legacy_context_restores_the_previous_step_after_rollback():
    context = {}
    unit_event(saved(0, {"type": "model_attempt_control", "phase": "begin", "step_id": "first", "attempt_id": "a"}), context)
    unit_event(saved(1, {"type": "model_attempt_control", "phase": "begin", "step_id": "second", "attempt_id": "b"}), context)
    unit_event(saved(2, {"type": "model_attempt_control", "phase": "rollback", "attempt_id": "b"}), context)
    event = unit_event(saved(3, {"type": "final_answer", "content": "restored"}), context)
    assert event["step_id"] == "first" and event["attempt_id"] == "a"


def test_known_storage_version_with_another_event_type_is_left_as_literal_text():
    text = json.dumps({"creator_event_version": 1, "event": {"type": "summary", "content": "literal"}})
    assert unpack_creator_event(text, "final_answer") is None
    assert unit_event({"unit_type": "final_answer", "unit_index": 0, "unit_content": text})["content"] == text


@pytest.mark.asyncio
async def test_database_gap_is_rejected_instead_of_returning_a_truncated_answer(recovery):
    recovery.rows[-1].update(status="completed", units=[saved(0, {"type": "final_answer", "content": "first"}),
                                                      saved(2, {"type": "final_answer", "content": "last"})])
    with pytest.raises(RuntimeError, match="checkpoint has a gap"):
        await read(recovery)


@pytest.mark.asyncio
async def test_legacy_redis_tail_fills_a_durable_gap_before_the_live_event(recovery, monkeypatch):
    recovery.state.enabled = True
    recovery.state.get_run_state_async.side_effect = [
        {"generation": "owned", "status": "running"}, {"generation": "owned", "status": "completed"},
    ]
    events = [{"type": "final_answer", "content": str(i), "answer_phase": "delta", "unit_index": i} for i in range(3)]
    units = [saved(i, event) for i, event in enumerate(events)]
    monkeypatch.setattr(runtime, "get_message_units", MagicMock(side_effect=[units[:1], units[:2], units]))
    recovery.state.wait_for_stream_events_async = AsyncMock(return_value=[("3-0", frame(events[2]))])
    assert [p["content"] for p in await read(recovery)] == ["0", "1", "2"]
