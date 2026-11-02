# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Northbound compatibility at the canonical stream publication boundary."""

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from .test_agent_run_final_answers import service_tests, stream_capture


def answer(content, phase="delta", **metadata):
    return {"type": "final_answer", "content": content, "answer_phase": phase,
            "step_id": "root-step", **metadata}


def answers(events):
    return [event for event in events if event.get("type") == "final_answer"]


@pytest.mark.asyncio
@pytest.mark.parametrize("verified", ["", "Verified answer"])
async def test_complete_first_answer_contains_the_entire_canonical_result(stream_capture, verified):
    source = [
        {"type": "tool", "content": "progress"},
        answer("\n"), answer("Hello "), answer("世界"),
        answer(verified, "complete", agent_name="root"),
    ]
    events, batch = await stream_capture(source, final_answer_mode="complete")
    expected = verified or "\nHello 世界"
    assert [event["content"] for event in answers(events)] == [expected]
    assert answers(events)[0]["answer_phase"] == "complete"
    assert answers(events)[0]["agent_name"] == "root"
    assert events[0]["type"] == "tool" and events[-1]["type"] == "final_answer"
    assert batch["message_content"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [None, "delta"])
async def test_native_default_and_explicit_delta_keep_the_existing_protocol(stream_capture, mode):
    source = [answer("\n"), answer("Full answer"), answer("", "complete")]
    options = {} if mode is None else {"final_answer_mode": mode}
    events, batch = await stream_capture(source, **options)
    assert [(event["content"], event["answer_phase"]) for event in answers(events)] == [
        ("\n", "delta"), ("Full answer", "delta"), ("", "complete"),
    ]
    assert batch["message_content"] == "\nFull answer"


@pytest.mark.asyncio
async def test_complete_preserves_legacy_unphased_final_answers(stream_capture):
    events, batch = await stream_capture(
        [{"type": "final_answer", "content": "Legacy fallback"}], final_answer_mode="complete")
    assert [event["content"] for event in answers(events)] == ["Legacy fallback"]
    assert batch["message_content"] == "Legacy fallback"


@pytest.mark.asyncio
async def test_complete_joins_root_fragments_across_parallel_children(stream_capture):
    events, batch = await stream_capture([
        answer("Root "),
        answer("Child result", invocation_id="child"),
        answer("", "complete", invocation_id="child"),
        answer("result"), answer("", "complete"),
    ], final_answer_mode="complete")
    assert [event["content"] for event in answers(events)] == ["Root result"]
    assert not answers(events)[0].get("invocation_id")
    assert batch["message_content"] == "Root result"
    assert any(unit.get("invocation_id") == "child" for unit in batch["message_units"])


@pytest.mark.asyncio
async def test_complete_uses_only_the_reclassified_final_step(stream_capture):
    events, batch = await stream_capture([
        answer("Rejected draft", step_id="old-step"),
        {"type": "model_output_thinking", "content": "Reclassified ", "step_id": "final-step"},
        {"type": "model_output_code", "content": "answer", "step_id": "final-step"},
        answer("", "complete", step_id="final-step", reclassify_step=True),
    ], final_answer_mode="complete")
    assert [event["content"] for event in answers(events)] == ["Reclassified answer"]
    assert batch["message_content"] == "Reclassified answer"
    assert [event["type"] for event in events[:2]] == ["model_output_thinking", "model_output_code"]


@pytest.mark.asyncio
async def test_complete_discards_rolled_back_answers(stream_capture):
    events, batch = await stream_capture([
        answer("Rejected", attempt_id="failed"),
        answer("", "complete", attempt_id="failed"),
        {"type": "model_attempt_control", "phase": "rollback", "attempt_id": "failed"},
        answer("Accepted", attempt_id="ok"), answer("", "complete", attempt_id="ok"),
    ], final_answer_mode="complete")
    assert [event["content"] for event in answers(events)] == ["Accepted"]
    assert events[0]["phase"] == "rollback"
    assert batch["message_content"] == "Accepted"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [
    [answer("Partial")],
    [answer("Child", invocation_id="child"), answer("", "complete", invocation_id="child")],
    [answer(" \n"), answer("", "complete")],
    [answer("Rejected", attempt_id="failed"), answer("", "complete", attempt_id="failed"),
     {"type": "model_attempt_control", "phase": "rollback", "attempt_id": "failed"}],
])
async def test_complete_never_promotes_partial_child_blank_or_rolled_back_output(stream_capture, source):
    events, _ = await stream_capture(source, final_answer_mode="complete")
    assert answers(events) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,stopped", [("failed", False), ("stopped", False), ("completed", True)])
async def test_complete_does_not_publish_an_answer_for_failed_or_stopped_runs(stream_capture, outcome, stopped):
    events, batch = await stream_capture(
        [answer("Draft"), answer("", "complete")],
        outcome=outcome, stopped=stopped, final_answer_mode="complete")
    assert answers(events) == []
    assert batch["terminal_status"] == ("stopped" if stopped else outcome)


@pytest.mark.asyncio
async def test_complete_stream_exception_does_not_publish_success(stream_capture):
    events, batch = await stream_capture(
        [answer("Draft"), answer("", "complete"), RuntimeError("controlled failure")],
        final_answer_mode="complete")
    assert answers(events) == []
    assert any(event["type"] == "error" for event in events)
    assert batch["terminal_status"] == "failed"


@pytest.mark.asyncio
async def test_complete_cancellation_does_not_publish_success(stream_capture):
    with pytest.raises(asyncio.CancelledError):
        await stream_capture(
            [answer("Draft"), answer("", "complete"), asyncio.CancelledError()],
            final_answer_mode="complete")
    published = [json.loads(call.args[0].removeprefix("data: ").strip())
                 for call in stream_capture.channel.publish.call_args_list]
    assert answers(published) == []


@pytest.mark.asyncio
async def test_complete_persistence_failure_does_not_publish_success(stream_capture, monkeypatch):
    monkeypatch.setattr(service_tests.agent_execution, "persist_assistant_run_batch",
                        MagicMock(side_effect=RuntimeError("controlled persistence failure")))
    events, batch = await stream_capture(
        [answer("Draft"), answer("", "complete")], final_answer_mode="complete")
    assert answers(events) == [] and batch is None
    assert any(event["type"] == "error" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("raises", [False, True])
async def test_complete_message_creation_failure_does_not_publish_success(stream_capture, monkeypatch, raises):
    save = MagicMock(return_value=None)
    if raises:
        save.side_effect = RuntimeError("controlled message creation failure")
    monkeypatch.setattr(service_tests.agent_execution, "save_message", save)
    events, batch = await stream_capture(
        [answer("Whole "), answer("answer"), answer("", "complete")], final_answer_mode="complete")
    assert answers(events) == []
    assert any(event["type"] == "error" for event in events)
    assert batch is None
