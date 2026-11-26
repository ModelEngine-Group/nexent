# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""A cancelled native call keeps ownership until its real worker exits."""

import asyncio
from concurrent.futures import Future
from contextlib import nullcontext
from contextvars import ContextVar
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.concurrency import RunCancellationScope


def adapter():
    lifecycle = Mock()
    lifecycle.begin.side_effect = ["handler", "worker"]
    info = SimpleNamespace(_runtime_run_lifecycle=lifecycle)
    instance = JiuwenAdapter.__new__(JiuwenAdapter)
    instance.run_info = info
    instance.scope = RunCancellationScope(Event())
    instance.manager = Mock()
    instance._child_context = ContextVar("jiuwen_child_context", default=(None, None))
    instance._tool_executions = []
    instance._observe_tool = Mock(return_value=nullcontext())
    instance._resource_result = Mock()
    instance.delegation = Mock()
    return instance, lifecycle


@pytest.mark.asyncio
async def test_cancelled_native_worker_retains_ownership_until_actual_completion():
    instance, lifecycle = adapter()
    future = Future()
    assert future.set_running_or_notify_cancel()
    instance.manager.submit.return_value = SimpleNamespace(execution_id="owned", future=future)
    task = asyncio.create_task(instance._business_handler("upload_to_s3", Mock())())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert lifecycle.begin.call_count == 2
    lifecycle.finish.assert_called_once_with("handler")
    assert not future.done()
    future.set_result("uploaded")
    assert [call.args[0] for call in lifecycle.finish.call_args_list] == ["handler", "worker"]


@pytest.mark.asyncio
async def test_submit_failure_releases_both_lifetime_holders():
    instance, lifecycle = adapter()
    instance.manager.submit.side_effect = RuntimeError("capacity unavailable")
    with pytest.raises(RuntimeError, match="capacity unavailable"):
        await instance._business_handler("tool", Mock())()
    assert [call.args[0] for call in lifecycle.finish.call_args_list] == ["worker", "handler"]


@pytest.mark.asyncio
async def test_async_tool_keeps_handler_ownership_across_await():
    instance, lifecycle = adapter()
    entered, release = asyncio.Event(), asyncio.Event()

    async def work():
        entered.set()
        await release.wait()
        return "finished"

    task = asyncio.create_task(instance._business_handler("async-tool", work)())
    await asyncio.wait_for(entered.wait(), timeout=2)
    lifecycle.begin.assert_called_once_with("callback")
    lifecycle.finish.assert_not_called()
    release.set()
    assert await task == "finished"
    lifecycle.finish.assert_called_once_with("handler")


@pytest.mark.asyncio
async def test_sync_tool_returning_awaitable_keeps_handler_ownership_until_await_finishes():
    instance, lifecycle = adapter()
    entered, release = asyncio.Event(), asyncio.Event()

    async def result():
        entered.set()
        await release.wait()
        return "finished"

    future = Future()
    future.set_result(result())
    instance.manager.submit.return_value = SimpleNamespace(execution_id="owned", future=future)
    task = asyncio.create_task(instance._business_handler("tool", Mock())())
    await asyncio.wait_for(entered.wait(), timeout=2)
    lifecycle.finish.assert_called_once_with("worker")
    release.set()
    assert await task == "finished"
    assert [call.args[0] for call in lifecycle.finish.call_args_list] == ["worker", "handler"]


def test_jiuwen_explicit_local_fallback_clears_container_mapping(mocker):
    from nexent.core.agents.sandbox.config import SandboxLevel
    from nexent.core.agents.sandbox import execution

    instance, _ = adapter()
    instance.run_info.sandbox_config = SimpleNamespace(
        level=SandboxLevel.KUBERNETES, scope=SimpleNamespace(value="system"),
    )
    tool = SimpleNamespace(workspace_mapping=object())
    instance.business_tools = {"upload_to_s3": tool}
    instance.resources = SimpleNamespace(
        workspace_mapping=tool.workspace_mapping, _sandbox_executors=[],
        agent=SimpleNamespace(python_executor=None),
    )
    local = SimpleNamespace(_nexent_backend="local")
    mocker.patch.object(execution, "build_python_executor", return_value=local)
    instance._bind_skill_sandbox()
    assert instance.resources.workspace_mapping is None
    assert tool.workspace_mapping is None
    assert instance.resources.agent.python_executor is local
    assert instance.resources._sandbox_executors == [local]
