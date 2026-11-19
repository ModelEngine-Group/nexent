# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import pytest

from management.services.agent.stream import (
    finalize_buffered_unit_fragments as _finalize_buffered_unit_fragments,
    is_stream_unit_continuation as _is_continuation,
    rollback_model_attempt_units as _rollback_model_attempt_units,
)
from .test_agent_run_final_answers import stream_capture


def test_cmsr_003_rollback_removes_only_matching_attempt_units():
    units = [
        {"type": "model_output_thinking", "_attempt_id": "failed", "unit_content": "leak"},
        {"type": "model_output_thinking", "_attempt_id": "sibling", "unit_content": "keep"},
        {"type": "step_count", "unit_content": "step"},
    ]

    assert _rollback_model_attempt_units(units, "failed") == 1
    assert [unit["unit_content"] for unit in units] == ["keep", "step"]


def test_cmsr_003_attempt_metadata_is_never_persisted():
    units = [
        {
            "type": "model_output_thinking",
            "_attempt_id": "successful",
            "_content_fragments": ["hello", " world"],
            "unit_content": "",
        }
    ]

    assert _finalize_buffered_unit_fragments(units) == len("hello world")
    assert units == [
        {
            "type": "model_output_thinking",
            "unit_content": "hello world",
            "content": "hello world",
        }
    ]


def test_cmsr_003_continuation_requires_matching_attempt_and_invocation():
    current = {
        "type": "model_output_thinking",
        "_attempt_id": "attempt-1",
        "invocation_id": "subagent-1",
    }
    matching = {"attempt_id": "attempt-1", "invocation_id": "subagent-1"}
    sibling = {"attempt_id": "attempt-2", "invocation_id": "subagent-1"}

    assert _is_continuation(current, True, "model_output_thinking", matching)
    assert not _is_continuation(current, True, "model_output_thinking", sibling)


@pytest.mark.asyncio
async def test_cmsr_003_stream_rolls_back_failed_attempt_before_persistence(stream_capture):
    events = [
        {"type": "model_attempt_control", "phase": "begin", "attempt_id": "failed"},
        {"type": "model_output_thinking", "content": "rolled back", "attempt_id": "failed"},
        {"type": "model_attempt_control", "phase": "rollback", "attempt_id": "failed"},
        {"type": "model_attempt_control", "phase": "begin", "attempt_id": "success"},
        {"type": "model_output_thinking", "content": "keep", "attempt_id": "success"},
        {"type": "model_attempt_control", "phase": "commit", "attempt_id": "success"},
        {"type": "final_answer", "content": "done"},
    ]

    published, batch = await stream_capture(events)

    assert published == events
    units = batch["message_units"]
    assert [unit["unit_content"] for unit in units] == ["keep", "done"]
    assert all("_attempt_id" not in unit for unit in units)


@pytest.mark.asyncio
async def test_cmsr_004_terminal_error_is_persisted_once_with_failed_status(stream_capture):
    error = {
        "type": "error", "content": "The model request failed.",
        "error_code": "model_unknown_error", "retryable": False,
    }

    published, batch = await stream_capture([error], status="failed")

    assert published == [error]
    assert batch["terminal_status"] == "failed"
    assert [unit["type"] for unit in batch["message_units"]] == ["error"]
