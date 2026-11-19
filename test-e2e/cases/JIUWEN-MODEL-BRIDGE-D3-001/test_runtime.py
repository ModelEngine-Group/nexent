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
            "add", "ask_user", "nexent_execute_python",
        ]
        assert any(item.get("tool_call_id") == "provider-call-1" and item["content"] == "5"
                   for item in state["requests"][1]["messages"])
    else:
        assert "historical_tool_result" in observations
        assert any('"logs": "5' in str(item) for item in state["requests"][1]["messages"])


@pytest.mark.parametrize("protocol", ["native", "text", "unknown"])
@pytest.mark.parametrize("scenario", ["clarify", "clarify_bad", "clarify_mixed"])
def test_terminal_clarification_runtime(monkeypatch, protocol, scenario):
    """Exercise the real Jiuwen loop, complete response gate and next-run boundary."""
    def missing(info):
        info.query = "I need a reading; required birth details are missing."
        info.agent_config.instructions = "Ask the user when essential birth data is missing."

    info, state, output = asyncio.run(run_worker(monkeypatch, protocol, scenario, configure_run=missing))
    cards = [event for event in output if event.get("type") == "human_interaction"]
    assert not state["tool_calls"]
    assert not info.stop_event.is_set()
    if scenario == "clarify":
        assert info.attempt_outcome == "completed", output[-1:]
        assert info.run_result.end_reason == "awaiting_input"
        assert len(state["requests"]) == 1
        assert len(cards) == 1
        payload = json.loads(cards[0]["content"]) if isinstance(cards[0]["content"], str) else cards[0]["content"]
        assert payload["schema_version"] == 1 and payload["questions"][0]["id"] == "birth"
        assert not any(event.get("type") in {"tool", "error", "final_answer"} for event in output)
        assert any(event.get("type") == "step_observation" for event in output)

        def answered(next_info):
            next_info.query = "My birth date is 1999-08-26, 06:50, male. Use these supplied details."
            from nexent.core.agents.contracts.run import AgentHistory

            next_info.history = [AgentHistory(role="user", content=info.query),
                                 AgentHistory(role="assistant", content="Please provide your birth date")]

        following, state2, output2 = asyncio.run(run_worker(
            monkeypatch, protocol, "clarify_answered", configure_run=answered))
        assert following.attempt_outcome == "completed" and following.run_result.end_reason == "runner_answer"
        assert len(state2["requests"]) == 1 and not state2["tool_calls"]
        assert not any(event.get("type") == "human_interaction" for event in output2)
        assert following.run_result.final_content == "ANSWER_USING_SUPPLIED_BIRTH_DATE"
        assert "1999-08-26" in json.dumps(state2["requests"][0]["messages"])
    else:
        assert info.attempt_outcome == "failed", output[-1:]
        assert not cards
        assert len(state["requests"]) <= 4
