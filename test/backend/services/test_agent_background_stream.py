# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise background streaming with real terminal projection and isolated I/O."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from contracts.agent import AgentRequest
from management.services.agent import execution
from management.services.agent.background import BackgroundExecutionState
from nexent.core.utils.observer import ProcessType


@pytest.fixture
def stream_runtime(monkeypatch):
    channel = SimpleNamespace(publish=AsyncMock())
    info = SimpleNamespace(
        stop_event=asyncio.Event(), cancellation_scope=None,
        agent_config=SimpleNamespace(pre_run_tool_events=()),
        # The real AgentRunInfo always carries an observer; the execution
        # stream attaches its run-local execution history to it.
        observer=Mock(),
        attempt_outcome="completed", thread_future=None,
    )
    persist = Mock()
    mark_failed = Mock()
    unregister = Mock(return_value=True)
    complete = AsyncMock()

    async def managed(_lane, _spec, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def poll(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(execution, "runtime_thread_manager", SimpleNamespace(run=managed))
    monkeypatch.setattr(execution, "agent_run_manager", SimpleNamespace(unregister_agent_run=unregister))
    monkeypatch.setattr(execution, "persist_assistant_run_batch", persist)
    monkeypatch.setattr(execution, "update_message_status", mark_failed)
    monkeypatch.setattr(execution, "save_message", Mock(return_value=42))
    monkeypatch.setattr(execution, "_poll_runtime_cancel_signal", poll)
    monkeypatch.setattr(execution, "_cleanup_channel_later", AsyncMock())
    monkeypatch.setattr(execution, "streaming_channel_manager", SimpleNamespace(
        get_or_create_channel=AsyncMock(return_value=channel), complete_channel=complete,
    ))
    request = AgentRequest(query="fixture", agent_id=1, conversation_id=9)
    request._message_source = "AUTOMATION"
    create = Mock(return_value=42)
    state = BackgroundExecutionState(create_assistant=create)

    def start(source, background=True):
        monkeypatch.setattr(execution, "agent_run", source)
        return execution._stream_agent_chunks(
            request, "owner", "tenant", info, None, channel=channel,
            execution_state=state if background else None,
        )

    return SimpleNamespace(start=start, info=info, state=state, persist=persist,
                           create=create, mark_failed=mark_failed, complete=complete,
                           channel=channel, unregister=unregister)


@pytest.mark.asyncio
@pytest.mark.parametrize("case,expected,code", [
    ("success", "completed", None),
    ("retry_error", "completed", None),
    ("typed_error", "failed", "MODEL_FAILED"),
    ("empty_error", "failed", "AUTOMATION_EXECUTION_FAILED"),
    ("exception", "failed", "AUTOMATION_EXECUTION_FAILED"),
    ("missing_outcome", "failed", "AUTOMATION_OUTCOME_MISSING"),
    ("persistence", "failed", "AUTOMATION_PERSISTENCE_FAILED"),
    ("default_creator", "completed", None),
])
async def test_background_stream_reports_current_persisted_outcome(stream_runtime, case, expected, code):
    runtime = stream_runtime
    if case == "default_creator":
        runtime.state.create_assistant = None
    if case == "missing_outcome":
        runtime.info.attempt_outcome = None
    elif case in {"typed_error", "empty_error"}:
        runtime.info.attempt_outcome = "failed"
    if case == "persistence":
        runtime.persist.side_effect = RuntimeError("transaction rolled back")

    async def source(*args, **kwargs):
        yield json.dumps({"type": "model_output_thinking", "content": "partial"})
        if case == "exception":
            raise RuntimeError("model transport failed")
        if case in {"typed_error", "retry_error", "empty_error"}:
            yield json.dumps({"type": "error", "content": "" if case == "empty_error" else "model failed",
                              "error_code": None if case == "empty_error" else "MODEL_FAILED"})

    chunks = [chunk async for chunk in runtime.start(source)]
    assert chunks and "partial" in chunks[0]
    result = runtime.state.result()
    assert result["assistant_message_id"] == 42
    assert result["status"] == expected
    assert result["error_code"] == code
    assert result["persisted"] is (case != "persistence")
    if code is None:
        assert result["error_message"] is None
    elif case == "typed_error":
        assert result["error_message"] == "model failed"
    runtime.persist.assert_called_once()
    batch = runtime.persist.call_args.kwargs
    assert batch["message_id"] == 42 and batch["conversation_id"] == 9
    assert batch["message_units"][0]["unit_content"] == "partial"
    if case == "persistence":
        runtime.mark_failed.assert_called_once_with(42, "failed", "owner")
    else:
        assert batch["terminal_status"] == expected
    runtime.complete.assert_awaited_once_with(conversation_id=9, user_id="owner", status=expected)
    runtime.unregister.assert_called_once()
    if case != "default_creator":
        assert runtime.create.call_args.args[0].role == "assistant"


@pytest.mark.asyncio
async def test_assistant_creation_failure_has_no_false_identity_or_batch(stream_runtime):
    runtime = stream_runtime
    runtime.create.side_effect = RuntimeError("binding transaction failed")

    async def source(*args, **kwargs):
        pytest.fail("Generation cannot start without its assistant binding")
        yield

    with pytest.raises(RuntimeError, match="binding transaction"):
        _ = [chunk async for chunk in runtime.start(source)]
    assert runtime.state.result()["error_code"] == "AUTOMATION_MESSAGE_CREATE_FAILED"
    assert runtime.state.assistant_message_id is None
    runtime.persist.assert_not_called()


@pytest.mark.asyncio
async def test_background_stream_cancellation_saves_partial_output_before_propagating(stream_runtime):
    runtime = stream_runtime
    waiting = asyncio.Event()

    async def source(*args, **kwargs):
        yield json.dumps({"type": "model_output_thinking", "content": "partial"})
        waiting.set()
        await asyncio.Event().wait()

    async def consume():
        return [chunk async for chunk in runtime.start(source)]

    task = asyncio.create_task(consume())
    await asyncio.wait_for(waiting.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.info.stop_event.is_set()
    assert runtime.state.result()["status"] == "stopped"
    assert runtime.state.persisted is True
    assert runtime.persist.call_args.kwargs["terminal_status"] == "stopped"
    assert runtime.persist.call_args.kwargs["message_units"][0]["unit_content"] == "partial"


@pytest.mark.asyncio
@pytest.mark.parametrize("background", [False, True])
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_workspace_artifact_failure_preserves_background_finalization(
    monkeypatch, stream_runtime, background, failure,
):
    runtime = stream_runtime
    interrupted = asyncio.CancelledError() if failure == "cancel" else RuntimeError("artifact service failed")

    async def source(*args, **kwargs):
        yield json.dumps({"type": ProcessType.FILE_ARTIFACT.value,
                          "content": {"artifacts": [{"object_name": "fixture/report.csv"}]}})

    monkeypatch.setattr(execution, "_enrich_file_uploads_with_presigned_urls", Mock(side_effect=interrupted))
    if not background or failure == "cancel":
        with pytest.raises(type(interrupted)):
            _ = [chunk async for chunk in runtime.start(source, background)]
    else:
        _ = [chunk async for chunk in runtime.start(source)]
    if background:
        expected = "stopped" if failure == "cancel" else "failed"
        assert runtime.state.result()["status"] == expected
        assert runtime.state.persisted is True
        assert runtime.persist.call_args.kwargs["terminal_status"] == expected
        if failure == "error":
            assert runtime.state.error_code == "AUTOMATION_ARTIFACT_FAILED"
    else:
        runtime.persist.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,failure", [("skill", "publish"), ("workspace", "publish"), ("skill", "upload")])
async def test_artifact_side_channel_failures_do_not_skip_assistant_batch(
    monkeypatch, stream_runtime, kind, failure,
):
    runtime = stream_runtime
    artifact = {"absolute_path": "/fixture/report.csv", "object_name": "fixture/report.csv"}
    process = AsyncMock(return_value=[artifact])
    if failure == "upload":
        process.side_effect = RuntimeError("skill upload failed")
    monkeypatch.setattr(execution, "_process_skill_file_uploads", process)
    monkeypatch.setattr(execution, "_enrich_file_uploads_with_presigned_urls", lambda value: value)
    monkeypatch.setattr(execution, "_transform_skill_files_to_standard_format", lambda value: value)
    if failure == "publish":
        runtime.channel.publish.side_effect = RuntimeError("subscriber already closed")

    async def source(*args, **kwargs):
        yield json.dumps({"type": (ProcessType.SKILL_ARTIFACT if kind == "skill" else ProcessType.FILE_ARTIFACT).value,
                          "content": {"artifacts": [artifact]}})

    _ = [chunk async for chunk in runtime.start(source)]
    assert runtime.state.result()["status"] == "completed"
    runtime.persist.assert_called_once()
    assert runtime.persist.call_args.kwargs["skill_files"] == ([] if failure == "upload" else [artifact])
