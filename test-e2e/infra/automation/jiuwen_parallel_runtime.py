# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real Runner/HTTP collaboration with contended registration and parallel roots."""

import asyncio
import json
from collections import Counter, defaultdict
from contextlib import nullcontext
from threading import Event
from unittest.mock import Mock

from jiuwen_bridge_fixture import profile_for
from nexent.core.agents.contracts.config import AgentConfig, ModelConfig, ToolConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.orchestration.entry import agent_run
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.core.utils.observer import MessageObserver


async def run_parallel_roots(monkeypatch, protocol, *, cancel_one=False):
    import nexent.core.tools as tools
    from openjiuwen.core.runner import Runner

    state = {"requests": defaultdict(list), "effects": [], "loops": [], "errors": [], "handlers": set()}
    monitoring = Mock()
    monitoring.trace_llm_request.side_effect = lambda *args, **kwargs: nullcontext(None)
    monkeypatch.setattr("nexent.core.model_service.service.get_monitoring_manager", lambda: monitoring)

    # Only stretch the real lock's scheduling window; registration still uses
    # the actual native framework. Restore its original lock after this Case.
    framework = Runner.callback_framework
    registration = framework.register
    lock = asyncio.Lock()
    monkeypatch.setitem(framework._locks, "registration", lock)

    async def register(*args, **kwargs):
        async with lock:
            await asyncio.sleep(0.002)
        return await registration(*args, **kwargs)

    monkeypatch.setattr(framework, "register", register)
    original_run = JiuwenAdapter._run_async

    async def observe(adapter):
        state["loops"].append(id(asyncio.get_running_loop()))
        return await original_run(adapter)

    monkeypatch.setattr(JiuwenAdapter, "_run_async", observe)

    class Echo:
        name, description = "echo", "Record one authorized child effect"
        inputs = {"label": {"type": "string"}}

        def forward(self, label):
            state["effects"].append(label)
            return label

    monkeypatch.setattr(tools, "ParallelChildEcho", Echo, raising=False)

    async def handle(reader, writer):
        task = asyncio.current_task()
        state["handlers"].add(task)
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            route = headers.split(b" ")[1].decode().split("/")[1]
            size = int(next(line.split(b":", 1)[1] for line in headers.split(b"\r\n")
                            if line.lower().startswith(b"content-length:")))
            body = json.loads(await reader.readexactly(size))
            state["requests"][route].append(body)
            first = len(state["requests"][route]) % 2 == 1
            if cancel_one and route.startswith("child0"):
                await reader.read()
                return
            if first and route.startswith("root"):
                root = route[-1]
                args = {"tasks": [{"tool_name": f"child_{root}_{letter}",
                                   "arguments": {"task": f"Task {root}:{letter}"}, "result_key": letter}
                                  for letter in "ABC"], "max_workers": 3, "timeout": 10}
                name = "parallel_executor"
            elif first:
                root, letter = route[5], route[-1]
                name, args = "echo", {"label": f"{root}:{letter}"}
            else:
                name, args = None, None
            calls, text = [], f"DONE_{route}"
            if name and protocol == "native":
                text = ""
                calls = [{"id": f"call-{route}-{len(state['requests'][route])}", "type": "function",
                          "function": {"name": name, "arguments": json.dumps(args)}}]
            elif name:
                text = f'<code>\nprint({name}(**{args!r}))\n</code>'
            message = {"role": "assistant", "content": text}
            if calls:
                message["tool_calls"] = [{"index": i, **call} for i, call in enumerate(calls)]
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n")
            chunk = {"id": "parallel-fixture", "model": body["model"], "object": "chat.completion.chunk",
                     "choices": [{"index": 0, "delta": message, "finish_reason": None}]}
            writer.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            chunk["choices"] = [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if calls else "stop"}]
            chunk["usage"] = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
            writer.write(("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode())
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception as error:
            state["errors"].append(type(error).__name__)
        finally:
            writer.close()
            await writer.wait_closed()
            state["handlers"].discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    manager = ThreadManager("jiuwen-parallel-case", {
        lane: LanePolicy(name=lane, max_workers=workers, max_queue_size=64)
        for lane, workers in [("agent-run", 3), ("background-service", 4), ("control-io", 32),
                              ("model-tool-io", 12), ("sandbox", 16), ("mcp-session", 2)]
    })
    manager.start()
    outputs, infos = [], []
    try:
        async with server:
            for batch in range(2 if not cancel_one else 1):
                current = []
                for root in range(3):
                    models, children = [], []
                    for route in [f"root{root}", *(f"child{root}{letter}" for letter in "ABC")]:
                        profile = profile_for(url + "/" + route, protocol)
                        models.append(ModelConfig(cite_name=route, model_name=profile.identity.request_model_id,
                                                  url=profile.connection.base_url, api_key="fixture-only",
                                                  resolved_profile=profile))
                    for letter in "ABC":
                        children.append(AgentConfig(name=f"child_{root}_{letter}", description="Owned child",
                            agent_core="jiuwen", model_name=f"child{root}{letter}", max_steps=3,
                            tools=[ToolConfig(name="echo", class_name="ParallelChildEcho", source="local", params={})]))
                    config = AgentConfig(name=f"root{root}", description="Parallel fixture", model_name=f"root{root}",
                        agent_core="jiuwen", max_steps=3, worker_agents=children,
                        tools=[ToolConfig(name="parallel_executor", class_name="ParallelExecutorTool", source="local", params={})])
                    current.append(AgentRunInfo(query=f"Run batch {batch}", agent_config=config,
                        model_config_list=models, observer=MessageObserver(lang="en"), stop_event=Event(),
                        thread_manager=manager, tenant_id="spike-tenant", collaboration_timeout_seconds=10))
                infos.extend(current)

                async def consume(info):
                    observed = []
                    try:
                        async for event in agent_run(info, thread_manager=manager):
                            observed.append(json.loads(event))
                    except asyncio.CancelledError:
                        if not cancel_one or info is not current[0]:
                            raise
                    return observed

                async def cancel_root():
                    while not any(state["requests"][f"child0{letter}"] for letter in "ABC"):
                        await asyncio.sleep(0.01)
                    current[0].stop_event.set()

                canceller = asyncio.create_task(cancel_root()) if cancel_one else None
                try:
                    outputs.extend(await asyncio.gather(*(consume(info) for info in current)))
                finally:
                    if canceller is not None:
                        await canceller
    finally:
        drained = await manager.shutdown(timeout=8)
        for task in tuple(state["handlers"]):
            task.cancel()
        await asyncio.gather(*state["handlers"], return_exceptions=True)
        assert not drained.stuck_execution_ids
        assert manager.snapshot().active_count == 0
    assert len(set(state["loops"])) == 1
    assert not state["errors"]
    expected = Counter({f"{root}:{letter}": (1 if cancel_one else 2)
                        for root in range(1 if cancel_one else 0, 3) for letter in "ABC"})
    assert Counter(state["effects"]) == expected
    return infos, outputs, state
