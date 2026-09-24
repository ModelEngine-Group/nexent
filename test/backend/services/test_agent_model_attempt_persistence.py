import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from management.services.agent import run as agent_run_service
from management.services.agent.run import (
    _finalize_buffered_unit_fragments,
    _is_continuation,
    _rollback_model_attempt_units,
)


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


def _agent_request():
    return SimpleNamespace(
        conversation_id=999,
        history=[],
        is_debug=False,
    )


def _agent_run_info(outcome: str = "completed"):
    return SimpleNamespace(
        agent_config=SimpleNamespace(pre_run_tool_events=()),
        cancellation_scope=None,
        stop_event=asyncio.Event(),
        human_interaction=None,

        attempt_outcome=outcome,
        thread_future=None,
    )


def _configure_stream_mocks(monkeypatch, persisted_batches):
    monkeypatch.setattr(agent_run_service, "save_message", MagicMock(return_value=4242))
    monkeypatch.setattr(
        agent_run_service,
        "persist_assistant_run_batch",
        lambda **kwargs: persisted_batches.append(kwargs),
    )
    monkeypatch.setattr(
        agent_run_service, "_unregister_agent_run_after_execution", MagicMock()
    )
    monkeypatch.setattr(
        agent_run_service.streaming_channel_manager, "complete_channel", AsyncMock()
    )
    monkeypatch.setattr(agent_run_service, "_cleanup_channel_later", AsyncMock())

    async def run_managed(_lane, _spec, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def wait_for_cancel(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(agent_run_service.runtime_thread_manager, "run", run_managed)
    monkeypatch.setattr(agent_run_service, "_poll_runtime_cancel_signal", wait_for_cancel)


@pytest.mark.asyncio
async def test_cmsr_003_stream_rolls_back_failed_attempt_before_persistence(monkeypatch):
    async def fake_agent_run(*_args, **_kwargs):
        yield json.dumps({"type": "model_attempt_control", "content": "", "phase": "begin", "attempt_id": "failed"})
        yield json.dumps({"type": "model_output_thinking", "content": "leak", "attempt_id": "failed"})
        yield json.dumps({"type": "model_attempt_control", "content": "", "phase": "rollback", "attempt_id": "failed"})
        yield json.dumps({"type": "model_attempt_control", "content": "", "phase": "begin", "attempt_id": "success"})
        yield json.dumps({"type": "model_output_thinking", "content": "keep", "attempt_id": "success"})
        yield json.dumps({"type": "model_attempt_control", "content": "", "phase": "commit", "attempt_id": "success"})
        yield json.dumps({"type": "final_answer", "content": "done"})

    persisted_batches = []
    _configure_stream_mocks(monkeypatch, persisted_batches)
    monkeypatch.setattr(agent_run_service, "agent_run", fake_agent_run)
    channel = SimpleNamespace(publish=AsyncMock())

    chunks = [
        chunk
        async for chunk in agent_run_service._stream_agent_chunks(
            _agent_request(),
            "user1",
            "tenant1",
            _agent_run_info(),
            MagicMock(),
            channel=channel,
        )
    ]

    assert len(chunks) == 7
    assert len(persisted_batches) == 1
    units = persisted_batches[0]["message_units"]
    assert [unit["unit_content"] for unit in units] == ["keep", "done"]
    assert all("_attempt_id" not in unit for unit in units)


@pytest.mark.asyncio
async def test_cmsr_004_terminal_error_is_persisted_once_with_failed_status(monkeypatch):
    async def fake_agent_run(*_args, **_kwargs):
        yield json.dumps(
            {
                "type": "error",
                "content": "The model request failed.",
                "error_code": "model_unknown_error",
                "retryable": False,
            }
        )

    persisted_batches = []
    _configure_stream_mocks(monkeypatch, persisted_batches)
    monkeypatch.setattr(agent_run_service, "agent_run", fake_agent_run)
    channel = SimpleNamespace(publish=AsyncMock())

    chunks = [
        chunk
        async for chunk in agent_run_service._stream_agent_chunks(
            _agent_request(),
            "user1",
            "tenant1",
            _agent_run_info("failed"),
            MagicMock(),
            channel=channel,
        )
    ]

    error_chunks = [chunk for chunk in chunks if '"type": "error"' in chunk]
    assert len(error_chunks) == 1
    assert '"retryable": false' in error_chunks[0]
    assert persisted_batches[0]["terminal_status"] == "failed"
    assert [unit["type"] for unit in persisted_batches[0]["message_units"]] == ["error"]
