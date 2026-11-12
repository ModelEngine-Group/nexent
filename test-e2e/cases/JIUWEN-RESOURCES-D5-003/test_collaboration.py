# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import runpy
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'sdk'), str(ROOT/'backend'), str(ROOT/'test-e2e/infra/automation')]
from jiuwen_collaboration_runtime import run_collaboration
from jiuwen_bridge_runtime import stop_infrastructure
from jiuwen_parallel_runtime import run_parallel_roots

@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    stop_infrastructure()

import time
pytestmark = [pytest.mark.case_id("JIUWEN-RESOURCES-D5-003"), pytest.mark.stage("D5")]

@pytest.mark.parametrize("child,fault,protocol", [
    ("jiuwen", "cancel", "native"), ("jiuwen", "cancel", "text"),
    ("a2a", "cancel", "native"), ("a2a", "cancel", "text"),
    ("jiuwen", "capacity", "text"),
    ("a2a", "timeout", "native"), ("a2a", "timeout", "text"),
])
def test_nested_stop_and_recovery(monkeypatch, child, fault, protocol):
    start = time.monotonic()
    with monkeypatch.context() as patch:
        info, state, output, cores = asyncio.run(run_collaboration(patch, child_core=child, protocol=protocol, fault=fault))
    assert time.monotonic() - start < 10
    if fault != "capacity":
        assert state["closed"]
    assert state["effects"] == [] and state["parent_effects"] == []
    assert len(state["child"] if child == "jiuwen" else state["remote"]) == 1
    assert sum(event.get("type") == "subagent_start" for event in output) == 1
    assert sum(event.get("type") == "subagent_end" for event in output) == 1
    if fault in {"cancel", "capacity"}:
        assert info.attempt_outcome == "stopped"
        assert len(state["parent"]) == 1
    else:
        assert "Error:" in str(output)
    with monkeypatch.context() as patch:
        recovered, state, output, cores = asyncio.run(run_collaboration(patch, child_core=child, protocol=protocol))
    assert recovered.attempt_outcome == "completed" and "CHILD_DONE" in str(output)
    assert len(state["child"] if child == "jiuwen" else state["remote"]) == (2 if child == "jiuwen" else 1)


def test_cancelled_root_does_not_stop_parallel_root_sessions(monkeypatch):
    infos, outputs, state = asyncio.run(run_parallel_roots(monkeypatch, "native", cancel_one=True))
    assert infos[0].attempt_outcome == "stopped"
    for info, events in zip(infos[1:], outputs[1:]):
        assert info.attempt_outcome == "completed"
        children = [event for event in events if event.get("type") == "run_terminal" and event.get("invocation_id")]
        assert len(children) == 3 and all(event["status"] == "completed" for event in children)
    assert not [effect for effect in state["effects"] if effect.startswith("0:")]
@pytest.mark.parametrize("setting", ["RUNTIME_AGENT_COLLABORATION_TIMEOUT_SECONDS", "DEFAULT_TOOL_CALL_TIMEOUT"])
def test_configured_outer_deadline_closes_stalled_a2a_and_recovers(monkeypatch, caplog, setting):
    with monkeypatch.context() as patch:
        patch.setenv("RUNTIME_AGENT_COLLABORATION_TIMEOUT_SECONDS", "5")
        patch.setenv("DEFAULT_TOOL_CALL_TIMEOUT", "5")
        patch.setenv(setting, "0.1")
        settings = runpy.run_module("contracts.constants.environment")
        timeouts = {
            "collaboration_timeout_seconds": settings["RUNTIME_AGENT_COLLABORATION_TIMEOUT_SECONDS"],
            "tool_call_timeout_seconds": settings["DEFAULT_TOOL_CALL_TIMEOUT"],
        }
        started = time.monotonic()
        _, state, events, _ = asyncio.run(run_collaboration(
            patch, child_core="a2a", fault="timeout", run_timeouts=timeouts,
        ))
    assert time.monotonic() - started < 5
    assert state["closed"] and len(state["remote"]) == 1
    assert not state["effects"] and not state["parent_effects"]
    assert "CHILD_DONE" not in str(events)
    # Prove the configured outer boundary fired, rather than the 0.3-second A2A fallback.
    if setting == "RUNTIME_AGENT_COLLABORATION_TIMEOUT_SECONDS":
        assert "event=agent_collaboration_timeout" in caplog.text
        assert "timeout_seconds=0.100" in caplog.text
    else:
        assert "Tool 'delegate' timed out after 0.1s" in caplog.text
    with monkeypatch.context() as patch:
        recovered, state, events, _ = asyncio.run(run_collaboration(patch, child_core="a2a"))
    assert recovered.attempt_outcome == "completed"
    assert "CHILD_DONE" in str(events) and len(state["remote"]) == 1
