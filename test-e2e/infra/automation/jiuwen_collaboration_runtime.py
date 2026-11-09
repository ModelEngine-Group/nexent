# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real model/A2A HTTP fixtures for configured mixed-Core invocations."""

import asyncio
import json
from contextlib import asynccontextmanager, nullcontext
from threading import Event
from unittest.mock import Mock

from jiuwen_bridge_fixture import profile_for
from nexent.core.agents.contracts.config import AgentConfig, ExternalA2AAgentConfig, ModelConfig, ToolConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.cores.smolagents.adapter import SmolagentsAdapter
from nexent.core.agents.orchestration.entry import agent_run
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.core.utils.observer import MessageObserver


@asynccontextmanager
async def collaboration_provider(parent_core, child_core, protocol, remote_protocol, fault):
    state = {"parent": [], "child": [], "remote": [], "closed": False, "errors": [], "handlers": set(), "auth_ok": [], "effects": [], "parent_effects": []}

    async def handle(reader, writer):
        state["handlers"].add(asyncio.current_task())
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            path = headers.split(b" ")[1].decode()
            size = int(next(line.split(b":", 1)[1] for line in headers.split(b"\r\n")
                            if line.lower().startswith(b"content-length:")))
            body = json.loads(await reader.readexactly(size))
            key = "remote" if path.startswith("/remote") else "child" if path.startswith("/child") else "parent"
            state[key].append(body)
            if key in {"parent", "child"}:
                expected = b"authorization: bearer " + (b"parent-only" if key == "parent" else b"child-only")
                state["auth_ok"].append(expected in headers.lower())
            if fault in {"cancel", "timeout"} and key == ("remote" if child_core == "a2a" else "child"):
                await reader.read()
                state["closed"] = True
                return
            if key == "remote":
                payload = {"message": {"role": "agent", "parts": [{"text": "CHILD_DONE"}]}}
                if remote_protocol == "JSONRPC":
                    payload = {"jsonrpc": "2.0", "id": 1, "result": payload}
                encoded = json.dumps(payload).encode()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                             + str(len(encoded)).encode() + b"\r\nConnection: close\r\n\r\n" + encoded)
                await writer.drain()
                return
            core = parent_core if key == "parent" else child_core
            first = len(state[key]) == 1
            call = first and key == "parent"
            if call and core == "jiuwen" and protocol == "native":
                content = ""
                calls = [{"id": "call-child", "type": "function", "function": {
                    "name": "delegate", "arguments": json.dumps({"task": "CHILD_TASK_ONLY"})}}]
            elif call:
                content = '<code>\nvalue = delegate(task="CHILD_TASK_ONLY")\nprint(value)\n</code>'
                calls = []
            elif key == "child" and first:
                if core == "jiuwen" and protocol == "native":
                    content = ""
                    calls = [{"id": "child-effect", "type": "function", "function": {
                        "name": "child_echo", "arguments": "{}"}}]
                else:
                    content = '<code>\nprint(child_echo())\n</code>'
                    calls = []
            else:
                content = "PARENT_DONE" if key == "parent" else "CHILD_DONE"
                if core == "smolagents":
                    content = '<final_answer>' + content + '</final_answer>'
                calls = []
            finish = "tool_calls" if calls else "stop"
            message = {"role": "assistant", "content": content}
            if calls:
                message["tool_calls"] = calls
            value = {"id": "fixture-response", "model": body["model"], "object": "chat.completion",
                     "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                     "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
            if body.get("stream"):
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n")
                delta = dict(message)
                if calls:
                    delta["tool_calls"] = [{"index": i, **item} for i, item in enumerate(calls)]
                chunk = {"id": value["id"], "model": value["model"], "object": "chat.completion.chunk",
                         "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
                writer.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                chunk["choices"] = [{"index": 0, "delta": {}, "finish_reason": finish}]
                chunk["usage"] = value["usage"]
                writer.write(("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode())
            else:
                encoded = json.dumps(value).encode()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                             + str(len(encoded)).encode() + b"\r\nConnection: close\r\n\r\n" + encoded)
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception as exc:  # noqa: BLE001 - Record unexpected fixture errors for terminal assertions.
            state["errors"].append(type(exc).__name__)
        finally:
            writer.close()
            await writer.wait_closed()
            state["handlers"].discard(asyncio.current_task())

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        async with server:
            yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", state
    finally:
        for task in tuple(state["handlers"]):
            task.cancel()
        await asyncio.gather(*state["handlers"], return_exceptions=True)


async def run_collaboration(monkeypatch, parent_core="jiuwen", child_core="jiuwen", protocol="native",
                            remote_protocol="JSONRPC", fault=None):
    monitoring = Mock()
    monitoring.trace_llm_request.side_effect = lambda *args, **kwargs: nullcontext(None)
    monkeypatch.setattr("nexent.core.model_service.service.get_monitoring_manager", lambda: monitoring)
    def forbid(*args, **kwargs):
        raise AssertionError("Native Jiuwen provider client must not be used")
    monkeypatch.setattr("openjiuwen.core.foundation.llm.model.create_model_client", forbid)
    cores, cards = [], []
    for adapter_type in (JiuwenAdapter, SmolagentsAdapter):
        original = adapter_type.run
        def run(adapter, _original=original):
            cores.append((adapter.run_info.agent_config.name, adapter.core_name))
            return _original(adapter)
        monkeypatch.setattr(adapter_type, "run", run)
    original_prepare = JiuwenAdapter.prepare
    def prepare(adapter):
        original_prepare(adapter)
        cards.extend(card.id for card in adapter.native_agent.ability_manager.list())
    monkeypatch.setattr(JiuwenAdapter, "prepare", prepare)
    async with collaboration_provider(parent_core, child_core, protocol, remote_protocol, fault) as (url, state):
        from nexent.core.agents.cores.smolagents import agent as nexent_agent
        import nexent.core.tools as shared_tool_types
        from smolagents import Tool

        class ChildEchoTool(Tool):
            name, description, inputs, output_type = "child_echo", "Child effect", {}, "string"

            def forward(self):
                state["effects"].append("child")
                return "CHILD_EFFECT"

        class ParentOnlyTool(Tool):
            name, description, inputs, output_type = "parent_only", "Parent effect", {}, "string"

            def forward(self):
                state["parent_effects"].append("parent")
                raise AssertionError("Child cannot execute parent resources")

        monkeypatch.setattr(nexent_agent, "ChildEchoTool", ChildEchoTool, raising=False)
        monkeypatch.setattr(shared_tool_types, "ChildEchoTool", ChildEchoTool, raising=False)
        monkeypatch.setattr(nexent_agent, "ParentOnlyTool", ParentOnlyTool, raising=False)
        monkeypatch.setattr(shared_tool_types, "ParentOnlyTool", ParentOnlyTool, raising=False)

        def model(path, temperature, credential, outlet):
            profile = profile_for(url + path, protocol)
            data = profile.model_dump()
            data["outlet_id"] = outlet
            data["connection"]["credential_ref"]["model_id"] = outlet
            data["parameter_rules"].append({
                "key": "temperature", "schema": {"type": "number", "minimum": 0, "maximum": 2},
                "owner": "combination", "allowed_scopes": ["outlet", "conversation"], "required": False,
                "editable": True, "visible": True, "ui_group": "sampling",
                "source": {"ref": "controlled_temperature", "version": 1, "evidence": "Controlled fixture"},
                "api_binding": {"path": "/temperature", "transform_ref": "identity_v1", "transform_version": 1},
            })
            data["parameter_values"]["temperature"] = temperature
            profile = type(profile).model_validate(data)
            return ModelConfig(cite_name="shared", model_name=profile.identity.request_model_id,
                url=profile.connection.base_url, api_key=credential, temperature=temperature, resolved_profile=profile)
        child_model = model("/child", 0.2, "child-only", 8)
        child = AgentConfig(agent_core="jiuwen" if child_core == "a2a" else child_core,
            name="delegate", description="Delegate task", invocation_name="delegate", model_name="shared", tools=[ToolConfig(name="child_echo", class_name="ChildEchoTool",
                source="local", params={})],
            max_steps=3, runtime_model_config=child_model, instructions="CHILD_SYSTEM_ONLY")
        root = AgentConfig(agent_core=parent_core, name="parent", description="Parent", model_name="shared",
                           tools=[ToolConfig(name="parent_only", class_name="ParentOnlyTool", source="local", params={})],
                           instructions="PARENT_SYSTEM_ONLY", max_steps=3,
                           worker_agents=[] if child_core == "a2a" else [child])
        if child_core == "a2a":
            root.external_a2a_agents = [ExternalA2AAgentConfig(agent_id="remote-id", name="delegate",
                url=url + "/remote", protocol_type=remote_protocol, timeout=0.3 if fault == "timeout" else 5)]
        manager = ThreadManager("collaboration-runtime", {
            # Reserve service ownership for both monitoring and the shared Jiuwen loop.
            name: LanePolicy(name=name, max_workers=2 if name == "background-service" or
                             name == "sandbox" and fault != "capacity" else 1, max_queue_size=8)
            for name in ("agent-run", "model-tool-io", "mcp-session", "background-service", "sandbox", "control-io")})
        manager.start()
        info = AgentRunInfo(query="Call the subagent delegate. PARENT_TASK_ONLY", agent_config=root,
            model_config_list=[model("/parent", 0.9, "parent-only", 7)], observer=MessageObserver(lang="en"),
            stop_event=Event(), thread_manager=manager, collaboration_timeout_seconds=0.4 if fault == "capacity" else 5,
            tenant_id="spike-tenant", user_context={"user_id": "trusted"})
        async def cancel():
            while not (state["child"] or state["remote"]):
                await asyncio.sleep(0.01)
            info.stop_event.set()
        canceller = asyncio.create_task(cancel()) if fault == "cancel" else None
        output = []
        cancelled = False
        try:
            async for event in agent_run(info, thread_manager=manager):
                output.append(json.loads(event))
        except asyncio.CancelledError:
            # The public stream stops immediately on user cancellation. Inspect
            # only the real owned observer after the worker has drained below.
            if fault not in {"cancel", "capacity", "timeout"} or not info.stop_event.is_set():
                raise
            cancelled = True
        finally:
            if canceller:
                await canceller
            drained = await manager.shutdown(timeout=5)
            assert not drained.stuck_execution_ids
        if cancelled:
            output.extend(json.loads(event) for event in info.observer.get_cached_message())
        for _ in range(50):
            if not fault or state["closed"]:
                break
            await asyncio.sleep(0.01)
        from openjiuwen.core.runner import Runner
        assert all(Runner.resource_mgr.get_tool(card) is None for card in cards)
        assert manager.snapshot().active_count == 0
        assert not state["errors"]
        return info, state, output, cores
