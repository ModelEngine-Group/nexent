# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read Jiuwen's actual user answer and tool I/O through a fresh Ops service."""

import asyncio
import json
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace

import pytest
from jiuwen_bridge_fixture import provider as tool_provider
from opentelemetry.sdk.trace import TracerProvider
from shared.jiuwen_peer import model_config, provider as delegation_provider
from shared.trajectory_exchange import Catalog, http_app

import nexent.core.tools as tools
from infrastructure.trace.trajectory_processor import LocalTrajectoryProcessor
from infrastructure.trace.trajectory_store import CaptureIdentity, TrajectoryFileStore
from nexent.core.agents.contracts.config import AgentConfig, ToolConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.orchestration.entry import agent_run
from nexent.core.concurrency import LanePolicy, ManagedThreadSpec, ThreadManager
from nexent.core.utils.observer import MessageObserver
from nexent.monitor import (
    AgentRunMetadata, MonitoringConfig, agent_monitoring_context, get_agent_monitoring_context, get_monitoring_manager,
)
from ops.services.trajectory.primitives import ReferenceStore
from ops.services.trajectory.service import TrajectoryService

pytestmark = [pytest.mark.case_id("CHAT-TRAJECTORY-JIUWEN-IO-D3-001"), pytest.mark.stage("D3")]
CONVERSATION = "/trajectory/conversations/123"
IDENTITY = CaptureIdentity("source", "owner", "123", "7")


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with TemporaryDirectory(dir=tmp_path.resolve()) as directory:
        root = Path(directory)
        TrajectoryFileStore.provision(root)
        writer = LocalTrajectoryProcessor(TrajectoryFileStore(root, authorize=lambda _: None),
                                          get_agent_monitoring_context)
        tracer = TracerProvider(shutdown_on_exit=False)
        tracer.add_span_processor(writer)
        manager = get_monitoring_manager()
        monkeypatch.setattr(manager, "_config", MonitoringConfig(
            enable_telemetry=True, provider="local_file", local_span_processor=writer, export_metrics=False,
        ))
        monkeypatch.setattr(manager, "_tracer", tracer.get_tracer("jiuwen-trajectory-io"))
        lanes = ("agent-run", "model-tool-io", "control-io", "mcp-session", "background-service", "sandbox")
        threads = ThreadManager("jiuwen-trajectory-case", {lane: LanePolicy(lane, 4, 8) for lane in lanes})
        threads.start()
        try:
            writer.start(threads, ManagedThreadSpec("trajectory-writer", "case", close_hook=writer.request_stop))
            yield SimpleNamespace(root=root, writer=writer, threads=threads, monkeypatch=monkeypatch)
        finally:
            tracer.shutdown()
            drained = asyncio.run(threads.shutdown(timeout=5))
            assert not drained.stuck_execution_ids
            assert threads.snapshot().active_count == 0
    assert not root.exists()


async def run(archive, url, *, tool=None, delegate=False, cancel_at=None):
    children = [AgentConfig(name="child", agent_core="jiuwen", agent_id=8, description="Delegate task",
                            model_name="child", tools=[], max_steps=3)] if delegate else []
    config = AgentConfig(agent_core="jiuwen", name="root", agent_id=7, description="Solve the request",
                         model_name="root", tools=[tool] if tool else [], worker_agents=children, max_steps=3)
    models = [model_config(url, "source", "root", 7)]
    if delegate:
        models.append(model_config(url, "source", "child", 8))
    info = AgentRunInfo(query="Delegate twice and then answer" if delegate else "Compute 2 plus 3",
                        agent_config=config, model_config_list=models, history=[], observer=MessageObserver(lang="en"),
                        stop_event=Event(), conversation_id=123, user_id="owner", tenant_id="source")
    metadata = AgentRunMetadata(agent_id=7, conversation_id=123, user_id="owner", tenant_id="source")
    output = []

    async def consume():
        with agent_monitoring_context(metadata):
            async for event in agent_run(info, thread_manager=archive.threads):
                output.append(json.loads(event))

    async with asyncio.timeout(30):
        pending = asyncio.create_task(consume())
        try:
            if cancel_at is not None:
                while not cancel_at():
                    assert not pending.done(), "Execution stopped before first model fragment"
                    await asyncio.sleep(0.01)
                info.cancellation_scope.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                if cancel_at is None or not info.stop_event.is_set():
                    raise
            # Cancellation may end the public stream before the worker seals its trace.
            await asyncio.gather(asyncio.wrap_future(info.thread_future), return_exceptions=True)
        finally:
            if not pending.done():
                info.stop_event.set()
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
    return info, output


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


@contextmanager
def snapshot(archive, expected_status):
    assert archive.writer.force_flush(5000)
    reader = TrajectoryFileStore(archive.root, authorize=lambda _: None)
    execution, = reader.manifest(IDENTITY)["runs"]
    assert execution["capture_state"] == "ready"
    assert execution["business_status"] == expected_status
    service = TrajectoryService(reader, Catalog(), ReferenceStore())
    with http_app(archive.monkeypatch, SimpleNamespace(service=service)) as http:
        client = http.client
        client.headers["Authorization"] = "admin"
        result = data(client.get(CONVERSATION + "/snapshot", params={"trajectory_id": execution["trajectory_id"]}))
        yield client, result["nodes"]


def body(client, node, slot):
    reference = node[slot]
    assert reference["availability"] == "available", (node["name"], slot, reference)
    full = data(client.get(CONVERSATION + "/contents/" + reference["content_id"]))["text"]
    assert reference["complete"] and reference["text"] == full
    return full


def final_answer(info, events):
    assert info.attempt_outcome == "completed"
    answer, = [event["content"] for event in events
               if event["type"] == "final_answer" and not event.get("invocation_id")]
    assert answer == info.run_result.final_content
    return answer


def test_jiuwen_root_and_local_tool(archive, monkeypatch):
    calls = []

    class AddTool:
        name, description = "add", "Add two integers"
        inputs = {"a": {"type": "integer"}, "b": {"type": "integer"}}

        def forward(self, a, b):
            calls.append((a, b))
            return a + b

    monkeypatch.setattr(tools, "TrajectoryAddTool", AddTool, raising=False)
    tool = ToolConfig(name="add", class_name="TrajectoryAddTool", source="local", params={})

    async def execute():
        async with tool_provider("echo_history", "native") as (base, state):
            info, events = await run(archive, base, tool=tool)
        assert not state["server_errors"]
        assert len(state["requests"]) == 2 and calls == [(2, 3)]
        return final_answer(info, events)

    answer = asyncio.run(execute())
    assert answer == "SPIKE_FINAL_RESULT_5"
    with snapshot(archive, "completed") as (client, nodes):
        root, = [node for node in nodes if node["parent_id"] is None]
        add, = [node for node in nodes if node["kind"] == "tool"]
        assert add["name"] == "add" and add["parent_id"] == root["id"]
        assert json.loads(body(client, add, "input")) == {"a": 2, "b": 3}
        assert body(client, add, "output") == "5"
        assert body(client, root, "output") == answer


def test_jiuwen_delegated_tool_bodies(archive):
    with delegation_provider("normal", child_answer=lambda request: "reply-" + request["messages"][-1]["content"]) as peer:
        base, requests, _, _ = peer
        info, events = asyncio.run(run(archive, base, delegate=True))
        assert Counter(item["role"] for item in requests) == {"root": 2, "child": 2}
    answer = final_answer(info, events)
    assert answer == "root-ready"
    with snapshot(archive, "completed") as (client, nodes):
        root, = [node for node in nodes if node["parent_id"] is None]
        assert body(client, root, "output") == answer
        tools = [node for node in nodes if node["kind"] == "tool"]
        assert len(tools) == 2
        tasks = set()
        for tool in tools:
            assert tool["parent_id"] == root["id"] and tool["name"] == "child"
            child, = [n for n in nodes if n["kind"] == "agent" and n["parent_id"] == tool["id"]]
            task = body(client, child, "input")
            assert json.loads(body(client, tool, "input")) == {"task": task}
            assert body(client, tool, "output") == body(client, child, "output") == "reply-" + task
            tasks.add(task)
        assert tasks == {"task-1", "task-2"}


@pytest.mark.parametrize(("mode", "outcome", "status"), [("auth", "failed", "failed"),
                                                         ("cancel", "stopped", "cancelled")])
def test_jiuwen_no_final_answer(archive, mode, outcome, status):
    async def execute():
        async with tool_provider(mode, "native") as (base, state):
            cancel_at = (lambda: state["first_fragment_no_tool"]) if mode == "cancel" else None
            info, _ = await run(archive, base, cancel_at=cancel_at)
            assert info.attempt_outcome == outcome
            assert len(state["requests"]) == 1 and not state["server_errors"]
            if mode == "cancel":
                async with asyncio.timeout(3):
                    while not state.get("cancel_response_closed"):
                        await asyncio.sleep(0.01)

    asyncio.run(execute())
    with snapshot(archive, status) as (_, nodes):
        root, = [node for node in nodes if node["parent_id"] is None]
        assert root["output"]["text"] is None and root["output"]["content_id"] is None
