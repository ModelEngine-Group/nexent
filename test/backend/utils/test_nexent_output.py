# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Regression coverage for the server-owned, legacy-compatible client protocol."""

import json

import pytest
from infrastructure.nexent_output import (
    NexentOutputAdapter,
    NexentSSEAdapter,
    adapt_nexent_stream,
    normalize_nexent_history,
)


def event(kind, sequence, **fields):
    return {"schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
            "turn_id": "root", "type": kind, "sequence": sequence, "content": "", **fields}


def body(sequence=1, **fields):
    return event("model_output", sequence, block_id="body", content="Answer", **fields)


def terminal(sequence=2, **fields):
    return event("run_terminal", sequence, **{"status": "completed", "end_reason": "runner_answer",
                 "final_content": "Answer", "final_block_ids": ["body"], **fields})


def saved(events):
    return [{"type": e["type"], "content": json.dumps(e), "unit_index": i} for i, e in enumerate(events)]


def test_text_streams_before_terminal_without_requiring_new_client_types():
    adapter = NexentOutputAdapter()
    out = adapter.push(body())
    assert out[-1]["type"] == "model_output_thinking" and out[-1]["content"] == "Answer"
    assert all("runtime_mode" not in e for e in out)
    assert adapter.push(terminal()) == []
    assert adapter.push({"type": "final_answer", "content": "Answer", "invocation_id": None}) == []
    final = adapter.close()
    assert len(final) == 1 and final[0]["type"] == "final_answer"
    assert final[0]["step_id"] == out[-1]["step_id"]
    assert final[0]["answer_phase"] == "complete"
    assert adapter.close() == []


@pytest.mark.parametrize("capacity", [None, {"context_window_tokens": 1000, "token_threshold": 800,
    "effective_input_limit_tokens": 700, "context_processing_mode": "passthrough"}])
def test_metrics_and_explicit_reasoning_retain_unknowns_and_saved_cm(capacity):
    adapter = NexentOutputAdapter()
    thought = adapter.push(event("model_output_deep_thinking", 1, content="Reason", block_id="a"))
    assert thought[-1]["type"] == "model_output_deep_thinking"
    metrics = adapter.push(event("step_observation", 2, step_number=1, duration=.2,
                                usage={"input_tokens": None, "output_tokens": 0}, context_capacity=capacity))
    assert metrics[-1]["type"] == "token_count"
    data = json.loads(metrics[-1]["content"])
    assert data["step_input_tokens"] is None and data["step_output_tokens"] == 0
    assert data["context_window_tokens"] == (1000 if capacity else None)
    assert data["context_processing_mode"] == ("passthrough" if capacity else None)


@pytest.mark.parametrize("invocation", [None, "child"])
def test_tools_keep_empty_arguments_errors_and_provider_association(invocation):
    adapter = NexentOutputAdapter()
    call = adapter.push(event("tool", 1, local_call_id="call", tool_name="mcp", tool_arguments={},
                              invocation_id=invocation, provider_call_id="provider"))[0]
    result = adapter.push(event("tool_result", 2, local_call_id="call", result='{"data":[]}',
                                invocation_id=invocation, is_error=True, provider_call_id="provider"))[0]
    assert call["type"] == "tool" and call["tool_arguments"] == {}
    assert result["type"] == "execution_logs" and result["content"] == '{"data":[]}'
    assert result["tool_call_id"] == call["tool_call_id"]
    assert result["provider_call_id"] == "provider" and result["is_error"]


@pytest.mark.parametrize("fault,expected", [("missing", "NEXENT_TERMINAL_MISSING"),
    ("duplicate", "NEXENT_OUTPUT_AFTER_TERMINAL"), ("order", "NEXENT_OUTPUT_ORDER_INVALID"),
    ("unpaired", "NEXENT_TOOL_RESULT_UNPAIRED"), ("invalid", "NEXENT_TERMINAL_INVALID")])
def test_invalid_stream_cannot_produce_final_answer(fault, expected):
    adapter = NexentOutputAdapter()
    adapter.push(body())
    if fault == "duplicate":
        adapter.push(terminal())
        adapter.push(terminal(3))
    elif fault == "order":
        adapter.push(body())
        adapter.push(terminal())
    elif fault == "unpaired":
        adapter.push(event("tool_result", 2, local_call_id="missing"))
        adapter.push(terminal(3))
    elif fault == "invalid":
        adapter.push(terminal(status="bad"))
    result = adapter.close()
    assert [e["type"] for e in result] == ["error"]
    assert result[0]["content"] == expected


@pytest.mark.parametrize("status", ["failed", "stopped"])
def test_persisted_failure_or_cancellation_overrides_completed_root(status):
    adapter = NexentOutputAdapter()
    adapter.push(body())
    adapter.push(terminal())
    out = adapter.close(status)
    assert not any(e["type"] == "final_answer" for e in out)
    assert adapter.status == status


def test_waiting_for_user_has_no_empty_final_answer():
    adapter = NexentOutputAdapter()
    adapter.push(terminal(end_reason="awaiting_input", final_content="", final_block_ids=[]))
    assert adapter.close() == [] and adapter.status == "completed"


def test_child_completes_at_its_boundary_without_completing_parent():
    adapter = NexentOutputAdapter()
    adapter.push(body())
    adapter.push(body(turn_id="child", invocation_id="inv"))
    adapter.push(terminal(turn_id="child", invocation_id="inv"))
    out = adapter.push({"type": "subagent_end", "content": '{"invocation_id":"inv"}'})
    assert [e["type"] for e in out] == ["final_answer", "subagent_end"]
    assert json.loads(out[-1]["content"])["status"] == "completed"
    assert adapter.close()[0]["type"] == "error"


def test_history_is_normalized_once_without_modifying_source_or_interpreting_literal_json():
    literal = json.dumps(terminal(99))
    events = saved([body(), terminal()])
    events.insert(0, {"type": "model_output_thinking", "content": literal})
    before = json.dumps(events)
    output, status = normalize_nexent_history(events, "completed")
    assert json.dumps(events) == before and status == "completed"
    assert output[0]["content"] == literal
    assert [e["type"] for e in output] == ["model_output_thinking", "step_count", "final_answer"]
    assert normalize_nexent_history(output, status) == (output, status)


@pytest.mark.asyncio
async def test_sse_keeps_legacy_frames_and_closes_before_creator_done():
    closed = []

    async def source():
        try:
            yield ': heartbeat\n\n'
            yield 'data: {"status":"connected"}\n\n'
            for e in [body(), terminal(), {"type": "done", "content": ""}]:
                yield NexentSSEAdapter.serialize(e)
        finally:
            closed.append(True)

    frames = [frame async for frame in adapt_nexent_stream(source())]
    assert frames[:2] == [': heartbeat\n\n', 'data: {"status":"connected"}\n\n']
    events = [json.loads(f[5:]) for f in frames[2:]]
    assert [e["type"] for e in events][-2:] == ["final_answer", "done"]
    assert sum(e["type"] == "final_answer" for e in events) == 1 and closed == [True]


def test_legacy_events_pass_through_and_do_not_require_terminal():
    adapter = NexentOutputAdapter()
    legacy = {"type": "model_output_thinking", "content": "Legacy"}
    assert adapter.push(legacy) == [legacy]
    assert adapter.close() == []


@pytest.mark.parametrize("status", ["streaming", "pending", "running"])
def test_partial_history_does_not_invent_a_missing_terminal_error(status):
    result, restored = normalize_nexent_history(saved([body()]), status)
    assert restored == status
    assert any(e["type"] == "model_output_thinking" for e in result)
    assert not any(e["type"] in {"error", "final_answer"} for e in result)


def test_parallel_invocations_with_identical_local_ids_remain_distinct():
    adapter = NexentOutputAdapter()
    calls = [adapter.push(event("tool", 1, turn_id=child, invocation_id=child,
             local_call_id="same", tool_name="mcp"))[0] for child in ["a", "b"]]
    results = [adapter.push(event("tool_result", 2, turn_id=child, invocation_id=child,
               local_call_id="same", result=child))[0] for child in ["b", "a"]]
    assert calls[0]["tool_call_id"] != calls[1]["tool_call_id"]
    assert results[0]["tool_call_id"] == calls[1]["tool_call_id"]
    assert results[1]["tool_call_id"] == calls[0]["tool_call_id"]


def test_wrapped_history_tool_and_plain_duplicate_logs_are_paired_once():
    events = [body(), {"type": "tool", "content": "", "tool_call_id": "call", "tool_name": "mcp"},
              event("tool_result", 2, local_call_id="call", result="Result", provider_call_id="provider"),
              {"type": "execution_logs", "content": "Result", "tool_call_id": "call"}, terminal(3)]
    source = saved([events[0]]) + events[1:2] + saved([events[2]]) + events[3:4] + saved([events[4]])
    output, status = normalize_nexent_history(source, "completed")
    tool = next(e for e in output if e["type"] == "tool")
    results = [e for e in output if e["type"] == "execution_logs"]
    assert len(results) == 1 and results[0]["tool_call_id"] == tool["tool_call_id"]
    assert tool["provider_call_id"] == "provider" and status == "completed"


@pytest.mark.parametrize("kind", ["human_interaction", "nl2a", "skill_body", "file_content"])
def test_business_cards_and_artifact_events_pass_through(kind):
    adapter = NexentOutputAdapter()
    content = '{"questions":[],"value":null}'
    projected = adapter.push(event(kind, 1, content=content))
    assert projected[0]["type"] == kind and projected[0]["content"] == content
    assert "runtime_mode" not in projected[0]


@pytest.mark.asyncio
async def test_cancelling_stream_closes_owned_source_without_fabricating_a_terminal():
    closed = []

    async def source():
        try:
            yield NexentSSEAdapter.serialize(body())
            raise AssertionError("Cancelled consumers must not resume the producer")
        finally:
            closed.append(True)

    stream = adapt_nexent_stream(source())
    assert "step_count" in await anext(stream)
    await stream.aclose()
    assert closed == [True]


@pytest.mark.parametrize("fields", [{"error": ["malformed"]}, {"final_content": ""},
    {"end_reason": "awaiting_input"}])
def test_invalid_terminal_payload_is_a_controlled_legacy_error(fields):
    adapter = NexentOutputAdapter()
    adapter.push(body())
    adapter.push(terminal(**fields))
    assert adapter.close()[0]["content"] == "NEXENT_TERMINAL_INVALID"


def test_legacy_tool_projection_does_not_mutate_the_input_record():
    events = [{"type": "tool", "content": "", "tool_call_id": "call"}]
    before = json.dumps(events)
    normalize_nexent_history(events, "completed")
    assert json.dumps(events) == before


def test_active_history_resume_exposes_established_types_without_a_fake_terminal():
    from management.services.conversation.service import _build_streaming_message

    records = [{"role": "assistant", "message_id": 7, "message_index": 1, "status": "streaming",
                "message_content": "", "units": [{"unit_type": "model_output", "unit_index": 4,
                "unit_content": json.dumps(body())}]}]
    before = json.dumps(records)
    result = _build_streaming_message(records)
    assert result["status"] == "streaming" and result["message_id"] == 7
    assert result["last_unit"]["unit_type"] == "model_output_thinking"
    assert result["last_unit"]["unit_content"] == "Answer" and result["last_unit"]["unit_index"] == 4
    assert not any(u["unit_type"] in {"error", "final_answer"} for u in result["units"])
    assert json.dumps(records) == before
