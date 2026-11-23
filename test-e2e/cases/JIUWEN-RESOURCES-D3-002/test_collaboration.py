# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import runpy
import json
import re
import socket
import sys
from pathlib import Path
from uuid import uuid4
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


@pytest.mark.parametrize("parent,child,protocol", [
    ("jiuwen", "jiuwen", "native"), ("jiuwen", "jiuwen", "text"),
    ("jiuwen", "smolagents", "native"), ("jiuwen", "smolagents", "text"),
    ("smolagents", "jiuwen", "native"), ("smolagents", "jiuwen", "text"),
    ("smolagents", "smolagents", "native"),
])
def test_only_root_clarifies_after_child_returns_missing_information(monkeypatch, parent, child, protocol):
    from nexent.core.agents.prompt.clarification import child_information_policy

    info, state, output, cores = asyncio.run(run_collaboration(
        monkeypatch, parent, child, protocol, "JSONRPC", fault="missing_information"))
    assert info.attempt_outcome == "completed", output[-2:]
    assert ("delegate", child) in cores and ("parent", parent) in cores
    assert len(state["parent"]) == 2 and len(state["child"]) == 1
    assert not state["effects"] and not state["parent_effects"]
    child_request = state["child"][0]
    assert child_information_policy("en") in json.dumps(child_request)
    assert "ask_user(" not in json.dumps(child_request)
    assert all(tool.get("function", {}).get("name") != "ask_user" for tool in child_request.get("tools", []))
    assert "MISSING_INPUT: birth date" in json.dumps(state["parent"][1])
    forms = [event for event in output if event["type"] == "human_interaction"]
    assert len(forms) == 1 and not forms[0].get("invocation_id")
    form = forms[0]["content"]
    form = json.loads(form) if isinstance(form, str) else form
    assert form["questions"][0]["id"] == "birth"
    assert not any(event["type"] == "error" for event in output)
    assert sum(event["type"] == "subagent_start" for event in output) == 1
    assert sum(event["type"] == "subagent_end" for event in output) == 1

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
        if protocol == "native":
            _assert_native_parallel_output(info, events)
    assert all(len(requests) == 4 for requests in state["requests"].values())
    if protocol == "native":
        assert len(state["overlapping_child_batches"]) == 6
        assert len(state["overlapping_read_batches"]) == 18
        for route, requests in state["requests"].items():
            for request in requests:
                names = {tool["function"]["name"] for tool in request.get("tools", [])}
                assert "parallel_executor" not in names
                if route.startswith("child"):
                    assert names == {"read_file"}
            if route.startswith("root"):
                for request_no in (1, 3):
                    messages = requests[request_no]["messages"]
                    ids = {f"call-{route}-{request_no}-{index}" for index in range(3)}
                    assert {message["tool_call_id"] for message in messages if message["role"] == "tool"} == ids


def _assert_native_parallel_output(info, events, *, tool_count=9):
    from management.services.agent.stream import AssistantMessageProjection, finalize_buffered_unit_fragments
    from management.services.conversation.nexent_output import NexentOutputAdapter, normalize_nexent_history
    from management.services.conversation.runtime_output import project_runtime_history

    output = NexentOutputAdapter()
    storage = AssistantMessageProjection(persist_units=True)
    live = []
    for event in events:
        live.extend(output.push(event))
        storage.project(json.dumps(event))
    live.extend(output.close("completed"))

    finalize_buffered_unit_fragments(storage.units)
    answer, units, invalid = project_runtime_history(info.run_result.final_content, storage.units)
    restored, status = normalize_nexent_history([
        {"type": unit["unit_type"], "content": unit["unit_content"], "unit_index": unit["unit_index"],
         "tool_call_id": unit["tool_call_id"], "invocation_id": unit["invocation_id"]}
        for unit in units
    ], "completed")
    assert not invalid and status == "completed"
    assert answer == info.run_result.final_content

    def identities(stream, kind):
        return [(event.get("invocation_id"), event.get("tool_call_id")) for event in stream
                if event["type"] == kind and (kind != "execution_logs" or event.get("local_call_id"))]

    for stream in (live, restored):
        calls = identities(stream, "tool")
        results = identities(stream, "execution_logs")
        assert len(calls) == len(set(calls)) == len(results) == tool_count
        assert set(calls) == set(results)
        starts = identities(stream, "subagent_start")
        ends = identities(stream, "subagent_end")
        assert len(starts) == len(ends) == 3
        assert {item[0] for item in starts} == {item[0] for item in ends}
        assert not any(event["type"] in {"error", "model_output", "tool_result", "run_terminal"} for event in stream)
        assert [event["content"] for event in stream
                if event["type"] == "final_answer" and not event.get("invocation_id")] == [answer]

    for kind in ("tool", "execution_logs", "subagent_start", "subagent_end"):
        assert identities(live, kind) == identities(restored, kind)


@pytest.mark.skipif(sys.platform == "win32", reason="Run the Docker legacy workspace fixture from a Linux worker")
@pytest.mark.parametrize("scenario", ["overlap", "isolated-timeout", "parent-cancellation"])
def test_native_python_children_overlap_with_distinct_system_kernel_leases(monkeypatch, tmp_path, scenario):
    import docker

    from nexent.core.agents.sandbox import execution as sandbox

    pool = sandbox.SandboxPoolManager()
    suffix = uuid4().hex[:12]
    network_name = f"jiuwen-parallel-test-{suffix}"
    monkeypatch.setattr(sandbox, "SANDBOX_CONTAINER_NAME", network_name)
    monkeypatch.setattr(sandbox, "SANDBOX_NETWORK_NAME", network_name)
    monkeypatch.setattr(sandbox.SandboxPoolManager, "_instance", pool)
    acquired = []
    original = sandbox.build_python_executor

    def capture(config, *args, **kwargs):
        lease = original(config, *args, **kwargs)
        acquired.append((config, lease, lease.kernel_id, lease.container.id))
        return lease

    monkeypatch.setattr(sandbox, "build_python_executor", capture)
    client = docker.from_env()
    timeout_child = scenario == "isolated-timeout"
    cancel_parent = scenario == "parent-cancellation"

    def ready(barrier):
        if not acquired:
            return False
        check = "from pathlib import Path; import sys; assert len(list(Path(sys.argv[1]).glob('*'))) == 3"
        return acquired[0][1].container.exec_run(["python", "-c", check, barrier]).exit_code == 0

    try:
        infos, outputs, state = asyncio.run(run_parallel_roots(
            monkeypatch, "native", sandbox_workspace=tmp_path, sandbox_timeout=timeout_child,
            cancel_one=cancel_parent, sandbox_ready=ready,
        ))
        info, events = infos[0], outputs[0]
        assert info.attempt_outcome == ("stopped" if cancel_parent else "completed")
        assert len(acquired) == len({item[2] for item in acquired}) == 4
        assert len({item[3] for item in acquired}) == 1
        assert all(config.network_disabled and config.scope.value == "system" for config, *_ in acquired)
        assert all(lease._closed for _, lease, *_ in acquired)
        assert not pool._executors and not pool._lease_owners
        lease = acquired[0][1]
        kernels = lease._requests.get(f"{lease.base_url}/api/kernels", timeout=5)
        kernels.raise_for_status()
        assert kernels.json() == []
        assert not tmp_path.exists() or not any(tmp_path.iterdir())
        if cancel_parent:
            assert not state["uploads"] and len(state["requests"]["root0"]) == 1
            return

        intervals = {}
        python_calls = {event["local_call_id"] for event in events
                        if event.get("tool_name") == "nexent_execute_python" and event["type"] == "tool"}
        for event in events:
            if (event["type"] == "tool_result" and event.get("local_call_id") in python_calls
                    and not event["is_error"] and event["result"].startswith("{")):
                logs = json.loads(event["result"])["logs"]
                match = re.search(r"SANDBOX_INTERVAL ([ABC]) ([\d.]+) ([\d.]+)", logs)
                assert match, logs
                intervals[match[1]] = float(match[2]), float(match[3])
        expected = {"B", "C"} if timeout_child else {"A", "B", "C"}
        assert set(intervals) == expected
        assert max(start for start, _ in intervals.values()) < min(end for _, end in intervals.values())
        assert len(state["uploads"]) == len(expected) and set(state["uploads"].values()) == expected
        assert all(key.endswith("/outputs/same.txt") for key in state["uploads"])
        returned = [message["content"] for message in state["requests"]["root0"][1]["messages"]
                    if message["role"] == "tool"]
        assert all(any(f"s3://fixture/{key}" in result for result in returned) for key in state["uploads"])
        if timeout_child:
            failed = [event for event in events if event["type"] == "tool_result"
                      and not event.get("invocation_id") and event["is_error"]]
            assert [event["provider_call_id"] for event in failed] == ["call-root0-1-0"]
            assert not info.stop_event.is_set()
        else:
            _assert_native_parallel_output(info, events, tool_count=6)
    finally:
        try:
            pool.shutdown(sandbox.logger)
            try:
                network = client.networks.get(network_name)
            except docker.errors.NotFound:
                pass
            else:
                if sandbox._is_containerized_runtime():
                    network.disconnect(socket.gethostname(), force=True)
                network.remove()
        finally:
            client.close()


@pytest.mark.parametrize("protocol", ["native", "text"])
def test_configured_deadlines_allow_delayed_a2a_completion(monkeypatch, protocol):
    monkeypatch.setenv("RUNTIME_AGENT_COLLABORATION_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("DEFAULT_TOOL_CALL_TIMEOUT", "2.5")
    settings = runpy.run_module("contracts.constants.environment")
    timeouts = {
        "collaboration_timeout_seconds": settings["RUNTIME_AGENT_COLLABORATION_TIMEOUT_SECONDS"],
        "tool_call_timeout_seconds": settings["DEFAULT_TOOL_CALL_TIMEOUT"],
    }
    info, state, events, _ = asyncio.run(run_collaboration(
        monkeypatch, child_core="a2a", protocol=protocol, run_timeouts=timeouts, remote_delay=0.2,
    ))
    assert info.collaboration_timeout_seconds == 1.5
    assert info.tool_call_timeout_seconds == 2.5
    assert info.attempt_outcome == "completed"
    assert "CHILD_DONE" in str(events) and len(state["remote"]) == 1
    assert not state["effects"] and not state["parent_effects"]
