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
