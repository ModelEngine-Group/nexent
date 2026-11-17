# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real Jiuwen resources through canonical model transport."""
import asyncio
import json
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'sdk'), str(ROOT/'backend'), str(ROOT/'test-e2e/infra/automation')]
from jiuwen_resource_runtime import resource_provider, run_resources
from jiuwen_bridge_runtime import stop_infrastructure
pytestmark = [pytest.mark.case_id("JIUWEN-RESOURCES-D3-001"), pytest.mark.stage("D3")]

@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    stop_infrastructure()

@pytest.mark.parametrize("protocol", ["native", "text"])
@pytest.mark.parametrize("scenario", ["normal", "parallel", "docker"])
def test_resource_protocol_roundtrip(monkeypatch, tmp_path, protocol, scenario):
    with resource_provider(tmp_path) as url:
        info, state, output, calls, effects, elapsed = asyncio.run(run_resources(
            monkeypatch, tmp_path, url, protocol, "normal" if scenario == "docker" else scenario,
            docker_sandbox=scenario == "docker"))
    assert info.attempt_outcome == "completed", output[-1:]
    assert calls == [(2,3)] and state["mcp_calls"] == 1
    assert state["user_id"] == "captured-user"
    assert state["payload"] == {
        "config": [], "empty_object": {}, "explicit_null": None,
        "nested": [[], {}, None, {"value": None}, False, 0, ""],
    }
    assert effects == ("" if scenario == "parallel" else "x")
    assert state["model_calls"] == (2 if scenario == "parallel" else
                                    6 if scenario == "docker" and protocol == "native" else 5)
    assert state["saw_skill"]
    assert all(bool(body.get("tools")) == (protocol == "native") for body in state["requests"])
    body = json.dumps(state["requests"])
    assert "SECRET_SKILL" not in body and "fixture-only" not in body
    assert "forbidden_tool" not in state["tools"]
    assert "native_result_20" in str(output)
    assert sum(event.get("type") == "final_answer" for event in output) == 1
    if protocol == "native":
        multiply = next(tool for tool in state["requests"][0]["tools"] if tool["function"]["name"] == "multiply")
        assert "user_id" not in multiply["function"]["parameters"]["properties"]
        assert ("fixture_parallel_executor" if scenario == "parallel" else "fixture_multiply") in body
    else:
        assert "historical_tool_result" in body and "Tool execution error" not in body
