# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""MCP blocking helpers must work with the production process policies."""

import asyncio
import importlib.util
from pathlib import Path
import threading

import pytest

from nexent.core.concurrency import ThreadManager
from nexent.core.concurrency.helpers import run_blocking


@pytest.mark.parametrize("fail", [False, True])
def test_mcp_default_blocking_lane_executes_and_drains(mocker, fail):
    source = Path(__file__).resolve().parents[3] / "backend/mcp/thread_management.py"
    spec = importlib.util.spec_from_file_location("mcp_policy_under_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manager = ThreadManager("mcp-regression", module.mcp_thread_manager._policies)
    mocker.patch("nexent.core.concurrency.helpers.get_current_thread_manager", return_value=None)
    mocker.patch("nexent.core.concurrency.helpers.get_default_thread_manager", return_value=manager)
    manager.start()
    workers = []

    def operation():
        workers.append(threading.current_thread().name)
        if fail:
            raise ValueError("controlled retrieval failure")
        return ["candidate"]

    try:
        if fail:
            with pytest.raises(ValueError, match="controlled retrieval failure"):
                asyncio.run(run_blocking("nl2agent-retrieval", operation, owner="test"))
        else:
            assert asyncio.run(run_blocking("nl2agent-retrieval", operation, owner="test")) == ["candidate"]
        assert len(workers) == 1
        assert "model-tool-io" in workers[0]
        lane = next(row for row in manager.snapshot().lanes if row.name == "model-tool-io")
        assert lane.capacity == 22
        assert lane.active_count == lane.running_count == lane.queued_count == 0
        assert lane.available_count == lane.capacity
    finally:
        drained = asyncio.run(manager.shutdown(timeout=5))
        assert drained.stuck_execution_ids == ()
        assert manager.snapshot().active_count == 0
