# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify Runtime resource release when lifespan collaborators fail."""

import os
import sys
from types import ModuleType
from unittest.mock import AsyncMock, Mock

import pytest

from nexent.core.agents.sandbox.execution import SandboxPoolManager
from nexent.core.concurrency import ManagerState


@pytest.fixture
def resources(monkeypatch):
    if os.name == "nt":
        # File locking belongs to the writer. This fixture exercises shutdown orchestration.
        monkeypatch.setitem(sys.modules, "fcntl", ModuleType("fcntl"))
    from runtime.api import application

    manager = Mock(state=ManagerState.CREATED, run=AsyncMock(), shutdown=AsyncMock())
    processor = Mock()
    sandbox = Mock()
    streams = AsyncMock(return_value=[])
    stop_configuration = AsyncMock()
    clear_default = Mock()
    monkeypatch.setattr(application, "local_trajectory_processor", processor)
    monkeypatch.setattr(SandboxPoolManager, "_instance", sandbox)
    monkeypatch.setattr(application, "runtime_thread_manager", manager)
    monkeypatch.setattr(application, "runtime_state_service", Mock())
    monkeypatch.setattr(application, "recover_runtime_state", AsyncMock())
    monkeypatch.setattr(application, "watch_executions", AsyncMock())
    monkeypatch.setattr(application, "start_system_configuration", AsyncMock())
    monkeypatch.setattr(application, "stop_system_configuration", stop_configuration)
    monkeypatch.setattr(application, "shutdown_agent_stream_tasks", streams)
    monkeypatch.setattr(application, "set_default_thread_manager", Mock())
    monkeypatch.setattr(application, "clear_default_thread_manager", clear_default)
    return application, manager, processor, sandbox, streams, stop_configuration, clear_default


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "start", "streams", "sandbox", "configuration", "writer_stop"])
async def test_trajectory_lifespan_always_releases_runtime_manager(resources, failure):
    application, manager, processor, sandbox, streams, stop_configuration, clear_default = resources
    fail_at = {
        "start": processor.start,
        "streams": streams,
        "sandbox": sandbox.shutdown,
        "configuration": stop_configuration,
        "writer_stop": processor.shutdown,
    }

    async def run(_lane, _spec, function):
        if function is processor.shutdown:
            return function()

    manager.run.side_effect = run
    if failure:
        fail_at[failure].side_effect = RuntimeError(f"controlled {failure} failure")
        with pytest.raises(RuntimeError, match=f"controlled {failure} failure"):
            async with application.runtime_lifespan(None):
                pass
    else:
        async with application.runtime_lifespan(None):
            processor.start.assert_called_once()

    manager.start.assert_called_once()
    streams.assert_awaited_once()
    sandbox.shutdown.assert_called_once()
    processor.request_stop.assert_called_once()
    processor.shutdown.assert_called_once()
    stop_configuration.assert_awaited_once()
    manager.shutdown.assert_awaited_once()
    clear_default.assert_called_once_with(manager)
