"""Regression coverage for the managed sandbox host-tool bridge."""

import importlib.util
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from nexent.core.concurrency import LanePolicy, RunCancellationScope, ThreadManager
from nexent.core.concurrency.helpers import get_fallback_thread_manager


_SANDBOX_PATH = Path(__file__).resolve().parents[4] / "sdk" / "nexent" / "core" / "agents" / "sandbox.py"
_SPEC = importlib.util.spec_from_file_location("sandbox_bridge_lifecycle_under_test", _SANDBOX_PATH)
sandbox_module = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = sandbox_module
_SPEC.loader.exec_module(sandbox_module)


@pytest.fixture
def bridge_manager(monkeypatch):
    manager = ThreadManager(
        service_name="bridge-regression",
        lane_policies={
            "sandbox": LanePolicy(name="sandbox", max_workers=2, max_queue_size=0),
        },
    )
    manager.start()
    monkeypatch.setattr(sandbox_module, "_get_sandbox_thread_manager", lambda: manager)
    return manager


def _executor():
    return SimpleNamespace(send_tools=lambda tools: None, cleanup=lambda: None)


def test_sdk_ut_tlm_039_direct_sdk_fallback_lane_capacities():
    policies = get_fallback_thread_manager()._policies
    assert policies["control-io"].max_workers == 16
    assert policies["sandbox"].max_workers == 200
    assert policies["background-service"].max_workers == 12


def test_sdk_ut_tlm_036_cancel_stuck_run_closes_bridge_without_executor_cleanup(bridge_manager):
    scope = RunCancellationScope()
    executor = _executor()
    sandbox_module._install_host_tool_bridge(
        executor, logging.getLogger(__name__), cancellation_scope=scope
    )
    bridge = executor._nexent_tool_bridge

    assert bridge._execution.lane == "sandbox"
    assert bridge._thread.is_alive()
    scope.cancel()

    bridge._thread.join(timeout=1)
    assert not bridge._thread.is_alive()
    assert not bridge_manager.snapshot().executions
    executor.cleanup()


def test_sdk_ut_tlm_037_normal_cleanup_unregisters_bridge_from_run_scope(bridge_manager):
    scope = RunCancellationScope()
    executor = _executor()
    sandbox_module._install_host_tool_bridge(
        executor, logging.getLogger(__name__), cancellation_scope=scope
    )
    bridge = executor._nexent_tool_bridge

    executor.cleanup()
    bridge._thread.join(timeout=1)
    assert not bridge._thread.is_alive()
    assert not scope._closers
    scope.cancel()
    assert not bridge_manager.snapshot().executions


def test_sdk_ut_tlm_040_capacity_rejection_closes_unstarted_listener(monkeypatch):
    closed = []
    server = SimpleNamespace(server_port=12345, server_close=lambda: closed.append(True))

    def reject(*args):
        raise RuntimeError("full")

    manager = SimpleNamespace(register_service=reject)
    monkeypatch.setattr(sandbox_module, "ThreadingHTTPServer", lambda *args: server)
    monkeypatch.setattr(sandbox_module, "_get_sandbox_thread_manager", lambda: manager)

    with pytest.raises(RuntimeError, match="full"):
        sandbox_module._ToolBridge(logging.getLogger(__name__))

    assert closed == [True]
