# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify Runtime resource release when trajectory lifecycle collaborators fail."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nexent.core.concurrency import ManagerState


@pytest.fixture
def runtime_module(monkeypatch):
    manager = Mock(state=ManagerState.CREATED, run=AsyncMock(), shutdown=AsyncMock())
    processor = Mock()
    app = Mock()
    app.get.return_value = lambda function: function
    stubs = {
        "management.utils.app_factory": {"create_app": Mock(return_value=app)},
        "runtime.api.agent.execution": {"agent_runtime_router": Mock()},
        "management.api.automation.agent_automation": {"conversation_automation_router": Mock(), "router": Mock()},
        "runtime.api.evaluation.execution": {"router": Mock()},
        "runtime.api.sandbox": {"router": Mock()},
        "runtime.api.voice.streaming": {"voice_runtime_router": Mock()},
        "management.api.conversation.conversation_management": {"router": Mock()},
        "management.api.conversation.workbench_pins": {"router": Mock()},
        "management.api.conversation.conversation_share": {"router": Mock()},
        "runtime.api.file.upload": {"file_management_runtime_router": Mock()},
        "runtime.api.skill.creation": {"skill_creator_router": Mock()},
        "middleware.exception_handler": {"ExceptionHandlerMiddleware": Mock()},
        "infrastructure.concurrency": {"runtime_thread_manager": manager},
        "management.services.agent.run_state": {"runtime_state_service": Mock()},
        "infrastructure.observability.bootstrap": {"local_trajectory_processor": processor},
        "management.services.agent.execution": {"shutdown_agent_stream_tasks": AsyncMock(return_value=[])},
        "nexent.core.agents.sandbox.execution": {"SandboxPoolManager": SimpleNamespace(_instance=None)},
    }
    for name, attributes in stubs.items():
        monkeypatch.setitem(sys.modules, name, SimpleNamespace(**attributes))
    path = Path(__file__).resolve().parents[3] / "backend/runtime/api/application.py"
    spec = importlib.util.spec_from_file_location("trajectory_lifespan_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.start_agent_automation_scheduler = AsyncMock()
    module.stop_agent_automation_scheduler = AsyncMock()
    module.set_default_thread_manager = Mock()
    module.clear_default_thread_manager = Mock()
    return module, manager, processor


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "start", "scheduler_stop", "writer_stop"])
async def test_trajectory_lifespan_always_releases_runtime_manager(runtime_module, failure):
    module, manager, processor = runtime_module
    if failure == "start":
        processor.start.side_effect = RuntimeError("controlled-start-failure")
    elif failure == "scheduler_stop":
        module.stop_agent_automation_scheduler.side_effect = RuntimeError("controlled-stop-failure")
    elif failure == "writer_stop":
        async def fail_writer_stop(_lane, _spec, function, *_args):
            if function == processor.shutdown:
                raise RuntimeError("controlled-writer-stop-failure")
        manager.run.side_effect = fail_writer_stop

    if failure:
        with pytest.raises(RuntimeError, match="controlled"):
            async with module.runtime_lifespan(None):
                pass
    else:
        async with module.runtime_lifespan(None):
            processor.start.assert_called_once()

    manager.start.assert_called_once()
    processor.request_stop.assert_called_once()
    manager.shutdown.assert_awaited_once()
    module.clear_default_thread_manager.assert_called_once_with(manager)
    assert manager.run.await_args.args[2] == processor.shutdown


@pytest.mark.asyncio
@pytest.mark.parametrize('distributed', [False, True])
@pytest.mark.parametrize('pool_fails', [False, True])
async def test_sandbox_shutdown_preserves_trajectory_finalization_and_existing_errors(
    runtime_module, monkeypatch, distributed, pool_fails,
):
    from runtime import identity

    module, manager, processor = runtime_module
    monkeypatch.setattr(identity, 'uses_distributed_runtime', lambda: distributed)
    pool = Mock()
    sys.modules['nexent.core.agents.sandbox.execution'].SandboxPoolManager._instance = pool
    if pool_fails:
        pool.shutdown.side_effect = RuntimeError('controlled-pool-failure')
    async def run(_lane, spec, function, *args):
        if spec.task_name == 'sandbox-pool-shutdown':
            return function(*args)
    manager.run.side_effect = run
    if pool_fails:
        with pytest.raises(RuntimeError, match='controlled-pool-failure'):
            async with module.runtime_lifespan(None):
                pass
    else:
        async with module.runtime_lifespan(None):
            pass
    pool.shutdown.assert_called_once()
    scheduled = [call.args[1].task_name for call in manager.run.await_args_list]
    assert ('sandbox-pool-shutdown' in scheduled) is distributed
    assert scheduled[-1] == 'trajectory-file-shutdown'
    processor.request_stop.assert_called_once()
    manager.shutdown.assert_awaited_once()
    module.clear_default_thread_manager.assert_called_once_with(manager)
