# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Canonical ModelService through the real Nexent Jiuwen worker."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "sdk"), str(ROOT / "backend"), str(ROOT / "test-e2e/infra/automation")]

from jiuwen_bridge_runtime import run_worker, stop_infrastructure

pytestmark = [pytest.mark.case_id("JIUWEN-MODEL-BRIDGE-D3-001"), pytest.mark.stage("D3")]


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    stop_infrastructure()


@pytest.mark.parametrize("protocol,scenario", [
    ("native", "normal"), ("native", "empty_call_id"), ("text", "normal"), ("unknown", "normal")
])
def test_factory_service_protocol_loop(monkeypatch, protocol, scenario):
    info, state, output = asyncio.run(run_worker(monkeypatch, protocol, scenario))
    assert info.attempt_outcome == "completed", output[-1:]
    assert state["tool_calls"] == [(2, 3)]
    assert len(state["requests"]) == 2
    assert "fixture-only" not in json.dumps(state["requests"])
    assert state["first_fragment_no_tool"] is True
    assert all(bool(body.get("tools")) == (protocol == "native") for body in state["requests"])
    assert sum(event.get("type") == "final_answer" for event in output) == 1
    assert any("SPIKE_FINAL_RESULT_5" in str(event) for event in output)
    observations = json.dumps(state["requests"][1]["messages"])
    assert "Tool execution error" not in observations
    if protocol == "native":
        assert [tool["function"]["name"] for tool in state["requests"][0]["tools"]] == [
            "add", "nexent_execute_python",
        ]
        assert any(item.get("tool_call_id") == "provider-call-1" and item["content"] == "5"
                   for item in state["requests"][1]["messages"])
    else:
        assert "historical_tool_result" in observations
        assert any('"logs": "5' in str(item) for item in state["requests"][1]["messages"])
