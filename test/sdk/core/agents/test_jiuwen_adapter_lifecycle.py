# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Native Runner streaming and shutdown preserve per-run ownership on every exit."""

import asyncio
import json
from concurrent.futures import Future
from contextlib import nullcontext
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from nexent.core.agents.contracts.config import AgentConfig
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.concurrency import RunCancellationScope
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.utils.observer import MessageObserver, ProcessType


@pytest.fixture
def adapter():
    info = SimpleNamespace(agent_config=AgentConfig(name="fixture", description="Fixture", model_name="model", tools=[],
        pre_run_tool_events=[{"type": "tool", "content": "prepared"}]), observer=MessageObserver(),
        stop_event=Event(), mcp_close_timeout_seconds=2, run_result=None)
    instance = JiuwenAdapter(info)
    instance.scope = RunCancellationScope(info.stop_event)
    instance.query = "Latest request"
    instance.manager = Mock()
    instance.native_agent = SimpleNamespace(ability_manager=Mock())
    instance.native_agent.ability_manager.list.return_value = [SimpleNamespace(id="owned-tool")]
    return instance


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["success", "stream_error", "mcp_error", "cancelled", "stop_event", "release_error"])
async def test_stream_exit_always_closes_stream_session_and_owned_tools(adapter, mocker, ending):
    from openjiuwen.core.runner import Runner

    closed, observed = [], []
    error = RuntimeError("controlled failure")
    adapter.events.emit = lambda event: observed.append(event)
    adapter.events.final_answer = "Completed"
    adapter.mcp = SimpleNamespace(terminal_error=None)
    tokens = []
    original_register = adapter.scope.register_closer

    def register(callback):
        token = original_register(callback)
        tokens.append(token)
        return token

    registered = mocker.patch.object(adapter.scope, "register_closer", side_effect=register)
    unregistered = mocker.patch.object(adapter.scope, "unregister_closer", wraps=adapter.scope.unregister_closer)
    before = set(asyncio.all_tasks())

    async def stream(*args, **kwargs):
        try:
            if ending == "stream_error":
                raise error
            if ending == "mcp_error":
                adapter.mcp.terminal_error = error
            if ending == "cancelled":
                adapter.scope.cancel()
            if ending == "stop_event":
                adapter.run_info.stop_event.set()
                await asyncio.sleep(.2)
            yield {"type": "answer", "content": "Completed"}
        finally:
            closed.append(True)

    streaming = mocker.patch.object(Runner, "run_agent_streaming", side_effect=stream)
    release = mocker.patch.object(Runner, "release", new=AsyncMock(side_effect=error if ending == "release_error" else None))
    remove = mocker.patch.object(Runner.resource_mgr, "remove_tool")
    if ending == "success":
        assert await adapter._run_async() == "Completed"
        assert len(observed) == 1
    elif ending in {"cancelled", "stop_event"}:
        with pytest.raises(asyncio.CancelledError):
            await adapter._run_async()
    else:
        with pytest.raises(RuntimeError, match="controlled failure"):
            await adapter._run_async()
    assert closed == [True]
    release.assert_awaited_once_with(adapter.session_id)
    remove.assert_called_once_with("owned-tool")
    assert registered.call_count == 1
    unregistered.assert_called_once_with(tokens[0])
    streaming.assert_called_once_with(adapter.native_agent,
        {"query": "Latest request", "conversation_id": adapter.session_id}, session=adapter.session_id)
    assert {task for task in asyncio.all_tasks() - before if not task.done()} == set()
    queued = [json.loads(event) for event in adapter.run_info.observer.message_query]
    assert queued[0]["type"] == ProcessType.AGENT_NEW_RUN.value
    assert queued[1]["type"] == ProcessType.OTHER.value


@pytest.mark.parametrize("state,expected", [("completed", "completed"), ("failed", "failed"),
                                          ("stopped", "stopped"), ("waiting", "completed")])
def test_close_releases_only_owned_pending_executions_and_is_idempotent(adapter, mocker, state, expected):
    from openjiuwen.core.runner import Runner

    adapter.context_bridge = Mock()
    adapter.mcp, adapter.resources = Mock(), Mock()
    pending, done = Future(), Future()
    done.set_result("finished")
    adapter._tool_executions = [SimpleNamespace(execution_id="pending", future=pending),
                                SimpleNamespace(execution_id="done", future=done)]
    adapter._run_completed = state == "completed"
    adapter.events.waiting_for_input = state == "waiting"
    if state == "stopped":
        adapter.run_info.stop_event.set()
    finish = mocker.patch.object(adapter.events, "finish", return_value="public-result")
    mocker.patch.object(Runner.resource_mgr, "get_tool", return_value=object())
    remove = mocker.patch.object(Runner.resource_mgr, "remove_tool")
    adapter.close()
    adapter.close()
    finish.assert_called_once_with(expected)
    assert adapter.run_info.run_result == "public-result"
    adapter.context_bridge.close.assert_called_once()
    adapter.mcp.close.assert_called_once()
    adapter.resources.close.assert_called_once()
    remove.assert_called_once_with("owned-tool")
    adapter.manager.cancel.assert_called_once_with("pending", reason="Jiuwen tool cleanup",
        wait_timeout=2, mark_stuck_on_timeout=True)
    assert not pending.cancelled() and done.result() == "finished"


def test_mcp_close_failure_still_closes_resources_and_reports_failure(adapter, mocker):
    from openjiuwen.core.runner import Runner

    adapter._run_completed = True
    adapter.mcp = Mock()
    adapter.mcp.close.side_effect = RuntimeError("close failed")
    adapter.resources = Mock()
    mocker.patch.object(Runner.resource_mgr, "get_tool", return_value=None)
    finish = mocker.patch.object(adapter.events, "finish", return_value="failed-result")
    with pytest.raises(RuntimeError, match="close failed"):
        adapter.close()
    adapter.resources.close.assert_called_once()
    finish.assert_called_once_with("failed")
    assert adapter.run_info.run_result == "failed-result"


@pytest.mark.parametrize("ending", ["answer", "missing_terminal", "boundary", "cancel", "cancel_at_boundary"])
def test_run_converts_terminal_and_cancellation_outcomes_without_fabricated_answers(adapter, mocker, ending):
    loop = Mock()
    mocker.patch("nexent.core.agents.cores.jiuwen.execution_loop.get_execution_loop", return_value=loop)
    loop.run.return_value = "Answer"
    adapter.events.final_answer = "Answer" if ending == "answer" else None
    if ending in {"boundary", "cancel_at_boundary"}:
        adapter.run_info.observer.boundary_reached = True
    if ending in {"cancel", "cancel_at_boundary"}:
        loop.run.side_effect = asyncio.CancelledError
    if ending == "missing_terminal":
        with pytest.raises(RuntimeError, match="without a terminal answer"):
            adapter.run()
        assert adapter.events.last_error is not None and not adapter._run_completed
    elif ending == "cancel":
        with pytest.raises(RunTerminated):
            adapter.run()
        assert not adapter._run_completed
    else:
        assert adapter.run() == ("Answer" if ending == "answer" else "")
        assert adapter._run_completed
        assert adapter.events.waiting_for_input is (ending != "answer")
    loop.run.assert_called_once_with(adapter._run_async, cancel=adapter.scope.cancel)


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["deadline", "caller_cancel", "tool_timeout", "already_cancelled"])
async def test_business_call_cancels_only_its_managed_execution_and_preserves_timeout_origin(adapter, ending):
    import time

    future = Future()
    execution = SimpleNamespace(execution_id="owned", future=future)
    adapter.manager.submit.return_value = execution
    adapter.run_info.collaboration_timeout_seconds = 1
    adapter.run_info.model_deadline = time.monotonic() - 1 if ending == "deadline" else None
    adapter._observe_tool = Mock(return_value=nullcontext())
    forward = Mock()
    lane = "model-tool-io" if ending == "tool_timeout" else "control-io"
    if ending == "tool_timeout":
        future.set_exception(TimeoutError("tool deadline"))
    if ending == "already_cancelled":
        adapter.scope.cancel()
    handler = adapter._business_handler("child", forward, lane=lane)
    if ending == "caller_cancel":
        task = asyncio.create_task(handler(task="Work"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif ending == "already_cancelled":
        with pytest.raises(asyncio.CancelledError):
            await handler(task="Work")
        adapter.manager.submit.assert_not_called()
    else:
        with pytest.raises(TimeoutError):
            await handler(task="Work")
    if ending in {"deadline", "caller_cancel"}:
        assert adapter.manager.cancel.call_args.args[0] == "owned"
        assert adapter.manager.cancel.call_args.kwargs["mark_stuck_on_timeout"] is False
        assert adapter.scope.cancelled is (ending == "deadline")
    else:
        adapter.manager.cancel.assert_not_called()
    forward.assert_not_called()
