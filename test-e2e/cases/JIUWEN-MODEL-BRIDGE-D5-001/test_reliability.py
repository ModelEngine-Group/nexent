"""Incomplete responses must not cause execution or hidden stream replay."""

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "sdk"), str(ROOT / "backend"), str(ROOT / "test-e2e/infra/automation")]

from jiuwen_bridge_runtime import run_worker, stop_infrastructure

pytestmark = [pytest.mark.case_id("JIUWEN-MODEL-BRIDGE-D5-001"), pytest.mark.stage("D5")]


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    stop_infrastructure()


@pytest.mark.parametrize("protocol,scenario", [
    ("native", "bad_args"), ("native", "unknown_finish"), ("native", "auth"),
    ("native", "broken_stream"), ("text", "truncated"), ("text", "broken_stream"),
    ("text", "ambiguous"),
])
def test_bridge_incomplete_response_zero_effects(monkeypatch, protocol, scenario):
    info, state, output = asyncio.run(run_worker(monkeypatch, protocol, scenario))
    assert info.attempt_outcome == "failed", output[-1:]
    assert state["tool_calls"] == []
    assert len(state["requests"]) == (2 if scenario == "bad_args" else 1)
    if protocol == "text":
        assert any("<code>" in str(event) for event in output)


@pytest.mark.parametrize("scenario", ["transient", "transient_after_tool"])
def test_bridge_transient_retry_uses_service_only(monkeypatch, scenario):
    info, state, output = asyncio.run(run_worker(monkeypatch, "native", scenario))
    assert info.attempt_outcome == "completed", output[-1:]
    assert len(state["requests"]) == 3
    assert state["tool_calls"] == [(2, 3)]
    assert sum(event.get("type") == "step_count" for event in output) == 2


def test_bridge_cancellation_closes_visible_stream(monkeypatch):
    info, state, output = asyncio.run(run_worker(monkeypatch, "native", "cancel"))
    assert info.attempt_outcome == "stopped", output[-1:]
    assert state["tool_calls"] == []
    assert len(state["requests"]) == 1
    assert state.get("cancel_response_closed") is True
    assert any("PARTIAL" in str(event) for event in output)


def test_bridge_exhaustion_does_not_multiply_attempts(monkeypatch):
    info, state, output = asyncio.run(run_worker(monkeypatch, "native", "unavailable"))
    assert info.attempt_outcome == "failed"
    assert state["tool_calls"] == []
    assert len(state["requests"]) == 3
    assert sum(event.get("type") == "step_count" for event in output) == 1



def test_bridge_identical_usage_is_not_retried(monkeypatch):
    info, state, output = asyncio.run(run_worker(monkeypatch, "native", "duplicate_usage"))
    assert info.attempt_outcome == "completed"
    assert len(state["requests"]) == 2 and state["tool_calls"] == [(2, 3)]
    steps = [event for event in output if event["type"] == "step_observation"]
    assert len(steps) == 2 and all(event["usage"]["total_tokens"] == 5 for event in steps)
