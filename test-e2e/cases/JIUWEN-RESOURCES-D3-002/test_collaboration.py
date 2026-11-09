# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import json
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

pytestmark = [pytest.mark.case_id("JIUWEN-RESOURCES-D3-002"), pytest.mark.stage("D3")]

@pytest.mark.parametrize("parent,child,protocol,remote_protocol", [
    ("jiuwen", "jiuwen", "native", "JSONRPC"),
    ("jiuwen", "jiuwen", "text", "JSONRPC"),
    ("jiuwen", "smolagents", "native", "JSONRPC"),
    ("jiuwen", "smolagents", "text", "JSONRPC"),
    ("smolagents", "jiuwen", "native", "JSONRPC"),
    ("jiuwen", "a2a", "native", "JSONRPC"),
    ("jiuwen", "a2a", "text", "HTTP+JSON"),
])
def test_configured_collaboration(monkeypatch, parent, child, protocol, remote_protocol):
    info, state, output, cores = asyncio.run(run_collaboration(monkeypatch, parent, child, protocol, remote_protocol))
    assert info.attempt_outcome == "completed", output[-2:]
    assert len(state["parent"]) == 2
    assert state["parent_effects"] == []
    assert ("parent", parent) in cores
    assert state["auth_ok"] and all(state["auth_ok"])
    assert sum(event.get("type") == "subagent_start" for event in output) == 1
    assert sum(event.get("type") == "subagent_end" for event in output) == 1
    start = next(event for event in output if event.get("type") == "subagent_start")
    end = next(event for event in output if event.get("type") == "subagent_end")
    assert start["invocation_id"] == end["invocation_id"]
    assert "CHILD_DONE" in str(output) and "PARENT_DONE" in str(output)
    if child == "a2a":
        assert len(state["remote"]) == 1 and not state["child"]
        body = state["remote"][0]
        message = body.get("params", body)["message"]
        assert message["metadata"]["user_context"] == {"user_id": "trusted"}
        assert message["parts"] == [{"text": "CHILD_TASK_ONLY"}]
        assert "model" not in str(body) and "history" not in body
    else:
        assert ("delegate", child) in cores
        assert len(state["child"]) == 2 and not state["remote"]
        assert state["effects"] == ["child"]
        body = state["child"][0]
        assert "parent_only" not in str(body)
        assert "child_echo" in str(body)
        assert body["temperature"] == 0.2 and state["parent"][0]["temperature"] == 0.9
        assert "PARENT_SYSTEM_ONLY" not in str(body) and "PARENT_TASK_ONLY" not in str(body)
        assert "CHILD_TASK_ONLY" in str(body)
        assert "parent-only" not in str(body) and "child-only" not in str(body)


@pytest.mark.parametrize("protocol", ["native", "text"])
def test_parallel_roots_and_first_child_attempts_share_a_managed_runner_loop(monkeypatch, protocol):
    infos, outputs, state = asyncio.run(run_parallel_roots(monkeypatch, protocol))
    assert len(infos) == len(outputs) == 6
    for info, events in zip(infos, outputs):
        assert info.attempt_outcome == "completed"
        assert not [event for event in events if event.get("type") == "error"]
        starts = [event for event in events if event.get("type") == "subagent_start"]
        ends = [event for event in events if event.get("type") == "subagent_end"]
        terminals = [event for event in events if event.get("type") == "run_terminal" and event.get("invocation_id")]
        assert len(starts) == len(ends) == len(terminals) == 3
        assert {event["invocation_id"] for event in starts} == {event["invocation_id"] for event in terminals}
        assert all(event["status"] == "completed" for event in terminals)
        assert "bound to a different event loop" not in str(events)
        own = info.agent_config.name[-1]
        assert all(f"child_{own}_" in json.loads(event["content"])["invocation_name"] for event in starts)
    assert all(len(requests) == 4 for requests in state["requests"].values())
