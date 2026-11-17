# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Complete-mode previews are wire-only projections of canonical root answers."""

import json
from unittest.mock import MagicMock

import pytest

from .test_agent_run_final_answers import service_tests, stream_capture
from .test_northbound_final_answer_stream import answer, answers


def previews(events):
    return [event for event in events if event.get("answer_preview")]


@pytest.mark.asyncio
@pytest.mark.parametrize("verified", ["", "Corrected answer"])
async def test_preview_arrives_before_source_completion_and_is_not_persisted(stream_capture, verified):
    def source():
        yield {"type": "model_output_thinking", "content": "Real thought", "step_id": "root-step"}
        yield answer("Hello ", attempt_id="accepted", agent_name="root")
        published = [json.loads(call.args[0].removeprefix("data: ").strip())
                     for call in stream_capture.channel.publish.call_args_list]
        assert [event["content"] for event in previews(published)] == ["Hello "]
        assert answers(published) == []
        yield answer("世界", attempt_id="accepted", agent_name="root")
        yield answer(verified, "complete", agent_name="root")

    events, batch = await stream_capture(source(), final_answer_mode="complete")
    assert [event["content"] for event in previews(events)] == ["Hello ", "世界"]
    for event in previews(events):
        assert event["type"] == "model_output_thinking"
        assert event["answer_phase"] == "delta"
        assert event["step_id"] == "root-step" and event["attempt_id"] == "accepted"
        assert event["agent_name"] == "root"
        assert event["unit_index"] == previews(events)[0]["unit_index"]
        if not verified:
            assert event["unit_index"] == answers(events)[0]["unit_index"]
    assert events[0]["content"] == "Real thought" and not events[0].get("answer_preview")
    expected = verified or "Hello 世界"
    assert [event["content"] for event in answers(events)] == [expected]
    assert batch["message_content"] == expected
    assert [(unit["type"], unit["content"]) for unit in batch["message_units"]] == [
        ("model_output_thinking", "Real thought"), ("final_answer", expected)]
    assert all("answer_preview" not in unit for unit in batch["message_units"])


@pytest.mark.asyncio
async def test_child_answer_never_becomes_root_preview(stream_capture):
    events, batch = await stream_capture([
        answer("Root "), answer("Child", invocation_id="child"),
        answer("", "complete", invocation_id="child"), answer("answer"), answer("", "complete"),
    ], final_answer_mode="complete")
    assert [event["content"] for event in previews(events)] == ["Root ", "answer"]
    assert [event["content"] for event in answers(events)] == ["Root answer"]
    assert any(unit.get("invocation_id") == "child" for unit in batch["message_units"])


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{}, {"final_answer_mode": "delta"},
                                     {"final_answer_mode": "complete", "core": "other"}])
async def test_only_smolagents_complete_mode_produces_previews(stream_capture, options):
    source = [answer("Body"), answer("", "complete")]
    events, _ = await stream_capture(source, **options)
    assert previews(events) == []
    if options.get("final_answer_mode") != "complete":
        assert [(event["content"], event["answer_phase"]) for event in answers(events)] == [
            ("Body", "delta"), ("", "complete")]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["failed", "stopped"])
async def test_failed_or_stopped_preview_never_becomes_confirmed_answer(stream_capture, outcome):
    events, batch = await stream_capture(
        [answer("Partial"), answer("", "complete")], outcome=outcome, final_answer_mode="complete")
    assert [event["content"] for event in previews(events)] == ["Partial"]
    assert answers(events) == []
    assert batch["terminal_status"] == outcome


@pytest.mark.asyncio
async def test_rollback_drops_rejected_preview_from_canonical_storage(stream_capture):
    events, batch = await stream_capture([
        {"type": "model_attempt_control", "phase": "begin", "attempt_id": "failed"},
        answer("Rejected", attempt_id="failed"),
        {"type": "model_attempt_control", "phase": "rollback", "attempt_id": "failed"},
        answer("Accepted", attempt_id="ok"), answer("", "complete", attempt_id="ok"),
    ], final_answer_mode="complete")
    assert [event["content"] for event in previews(events)] == ["Rejected", "Accepted"]
    assert next(event for event in events if event.get("phase") == "rollback")["attempt_id"] == "failed"
    assert [event["content"] for event in answers(events)] == ["Accepted"]
    assert batch["message_content"] == "Accepted"
    assert [unit["content"] for unit in batch["message_units"] if unit["type"] == "final_answer"] == ["Accepted"]


@pytest.mark.asyncio
async def test_persistence_error_leaves_preview_unconfirmed(stream_capture, monkeypatch):
    monkeypatch.setattr(service_tests.agent_execution, "persist_assistant_run_batch",
                        MagicMock(side_effect=RuntimeError("controlled persistence failure")))
    events, batch = await stream_capture(
        [answer("Draft"), answer("", "complete")], final_answer_mode="complete")
    assert [event["content"] for event in previews(events)] == ["Draft"]
    assert answers(events) == [] and batch is None
    assert any(event["type"] == "error" for event in events)


@pytest.mark.asyncio
async def test_jiuwen_keeps_native_output_and_its_complete_answer(stream_capture):
    native = {"schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
              "turn_id": "turn"}
    events, batch = await stream_capture([
        {**native, "type": "model_output", "content": "Native answer", "block_id": "body", "sequence": 1},
        {"type": "final_answer", "content": "Native answer"},
        {**native, "type": "run_terminal", "content": "", "sequence": 2, "status": "completed",
         "end_reason": "runner_answer", "final_content": "Native answer", "final_block_ids": ["body"]},
    ], core="jiuwen", final_answer_mode="complete")
    assert previews(events) == []
    assert [event["content"] for event in answers(events)] == ["Native answer"]
    assert batch["message_content"] == "Native answer"
