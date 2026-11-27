# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Existing SSE and restored history carry the same structured failure diagnosis."""

import json

import pytest

from management.services.conversation.nexent_output import (
    NexentOutputAdapter,
    NexentSSEAdapter,
    normalize_nexent_history,
)


@pytest.mark.parametrize("category", ["MODEL_TIMEOUT", "mcp_auth_failed", "tool_execution_error", "sandbox_timeout"])
def test_error_text_and_code_agree_for_sse_and_history(category):
    terminal = {
        "schema_version": 1,
        "runtime_mode": "native_agent",
        "agent_core": "jiuwen",
        "turn_id": "run",
        "type": "run_terminal",
        "sequence": 1,
        "content": "",
        "status": "failed",
        "end_reason": category,
        "final_content": "",
        "final_block_ids": [],
        "error": {
            "category": category,
            "scope": "protocol",
            "safe_message": "Safe specific failure",
            "retryable": False,
            "request_id": "request",
        },
    }
    adapter = NexentOutputAdapter()
    assert adapter.push(terminal) == []
    live = adapter.close()
    assert len(live) == 1
    assert live[0]["type"] == "error" and live[0]["error_code"] == category
    assert live[0]["request_id"] == "request" and live[0]["retryable"] is False
    history, status = normalize_nexent_history(
        [{"type": "run_terminal", "content": json.dumps(terminal), "unit_index": 0}], "failed"
    )
    assert status == "failed"
    fields = ("type", "content", "error_code", "retryable", "request_id")
    assert {key: history[0][key] for key in fields} == {key: live[0][key] for key in fields}
    sse = NexentSSEAdapter()
    assert sse.push("data: " + json.dumps(terminal) + "\n\n") == []
    frames = sse.close()
    assert len(frames) == 1
    assert json.loads(frames[0][5:])["error_code"] == category
    assert adapter.close() == []


def test_invalid_terminal_does_not_promote_unvalidated_error_metadata():
    adapter = NexentOutputAdapter()
    adapter.push(
        {
            "schema_version": 1,
            "runtime_mode": "native_agent",
            "agent_core": "jiuwen",
            "turn_id": "run",
            "type": "run_terminal",
            "sequence": 1,
            "content": "",
            "status": "failed",
            "end_reason": "invalid",
            "final_content": "",
            "final_block_ids": [],
            "error": {"category": "private category", "request_id": "private request", "safe_message": "private"},
        }
    )
    error = adapter.close()[0]
    assert error["content"] == "NEXENT_TERMINAL_INVALID"
    assert "error_code" not in error and "request_id" not in error


def test_missing_terminal_identifies_last_boundary_in_live_and_history(caplog):
    event = {
        "schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
        "turn_id": "turn-reference", "sequence": 3, "type": "model_output", "content": "private model output",
    }
    adapter = NexentOutputAdapter(channel="journal_stream")
    adapter.push(event)
    live, = adapter.close("failed")
    assert adapter.close() == []
    history, status = normalize_nexent_history([event], "failed")
    assert status == "failed" and history[-1] == live
    assert live["error_code"] == "NEXENT_TERMINAL_MISSING"
    assert live["request_id"] == "turn-reference" and "final result" in live["content"]
    assert caplog.text.count("event=nexent_terminal_missing") == 2
    for entry in ("channel=journal_stream", "channel=history", "last_event='model_output'",
                  "last_sequence=3", "turn_id=turn-reference", "close_status=failed"):
        assert entry in caplog.text
    assert "private model output" not in caplog.text


def test_stopped_partial_stream_does_not_log_missing_terminal(caplog):
    adapter = NexentOutputAdapter()
    adapter.push({"schema_version": 1, "runtime_mode": "native_agent", "turn_id": "stopped",
                  "type": "model_output", "sequence": 1, "content": "partial"})
    assert adapter.close("stopped") == []
    assert "event=nexent_terminal_missing" not in caplog.text
