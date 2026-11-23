# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real Runner/HTTP collaboration with contended registration and parallel roots."""

import asyncio
import json
from collections import Counter, defaultdict
from contextlib import nullcontext
from pathlib import Path
from threading import Barrier, Event, Lock
from unittest.mock import Mock
from uuid import uuid4

from jiuwen_bridge_fixture import profile_for
from nexent.core.agents.contracts.config import AgentConfig, ModelConfig, ToolConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.orchestration.entry import agent_run
from nexent.core.agents.sandbox.config import SandboxConfig, SandboxLevel, SandboxScope
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager
from nexent.core.utils.observer import MessageObserver


async def run_parallel_roots(monkeypatch, protocol, *, cancel_one=False, sandbox_workspace=None, sandbox_timeout=False,
                             sandbox_ready=None):
    import nexent.core.tools as tools
    from openjiuwen.core.runner import Runner

    state = {"requests": defaultdict(list), "effects": [], "loops": [], "errors": [], "handlers": set(),
             "overlapping_child_batches": [], "overlapping_read_batches": []}
    use_sandbox = sandbox_workspace is not None
    sandbox_barrier = f"/tmp/nexent-python-proof-{uuid4().hex}"
    uploads = {}
    state["uploads"] = uploads
    helper = ToolConfig(name="parallel_executor", class_name="ParallelExecutorTool", source="local", params={})

    class FixtureStorage:
        default_bucket = "fixture"

        def upload_file(self, source, key):
            uploads[key] = Path(source).read_text(encoding="utf-8")
            return True, key

    storage = FixtureStorage()
    child_batches = {}
    read_batches = {}
    read_batch_lock = Lock()
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
        name, description = ("read_file" if protocol == "native" else "echo"), "Return one read-only fixture value"
        inputs = {"label": {"type": "string"}}

        def forward(self, label):
            if protocol == "native":
                key = label.rsplit(":", 1)[0]
                with read_batch_lock:
                    barrier = read_batches.setdefault(key, Barrier(2, timeout=3))
                if barrier.wait() == 0:
                    state["overlapping_read_batches"].append(key)
            state["effects"].append(label)
            return label

    class_name = "ReadFileTool" if protocol == "native" else "ParallelChildEcho"
    monkeypatch.setattr(tools, class_name, Echo, raising=False)

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
            if cancel_one and not use_sandbox and route.startswith("child0"):
                await reader.read()
                return
            if protocol == "native" and first and route.startswith("child"):
                root = route[5]
                key = (root, len(state["requests"][route]))
                arrived, all_arrived = child_batches.setdefault(key, (set(), asyncio.Event()))
                arrived.add(route)
                if len(arrived) == 3:
                    state["overlapping_child_batches"].append(key)
                    all_arrived.set()
                # Serial dispatch cannot advance any of these requests.
                await asyncio.wait_for(all_arrived.wait(), timeout=45 if use_sandbox else 4)
            if first and route.startswith("root"):
                root = route[-1]
                args = {"tasks": [{"tool_name": f"child_{root}_{letter}",
                                   "arguments": {"task": f"Task {root}:{letter}"}, "result_key": letter}
                                  for letter in "ABC"], "max_workers": 3, "timeout": 10}
                name = "parallel_executor"
            elif first:
                root, letter = route[5], route[-1]
                name, args = Echo.name, {"label": f"{root}:{letter}"}
                if use_sandbox:
                    name = "nexent_execute_python"
                    args = {"code": (
                        "import time\nfrom pathlib import Path\n"
                        "started = time.monotonic()\n"
                        f"Path('same.txt').write_text({letter!r}, encoding='utf-8')\n"
                        f"barrier = Path({sandbox_barrier!r})\n"
                        "barrier.mkdir(exist_ok=True)\n"
                        f"(barrier / {letter!r}).touch()\n"
                        "while len(list(barrier.iterdir())) < 3:\n"
                        "    if time.monotonic() - started > 18:\n"
                        "        raise RuntimeError('Native Python children did not overlap')\n"
                        "    time.sleep(0.05)\n"
                        + ("time.sleep(45)\n" if cancel_one or (sandbox_timeout and letter == "A") else "")
                        + f"print('SANDBOX_INTERVAL {letter}', started, time.monotonic())\n"
                    )}
            else:
                name, args = None, None
            calls, text = [], f"DONE_{route}"
            if name and protocol == "native":
                text = ""
                actions = [(task["tool_name"], task["arguments"]) for task in args["tasks"]] if (
                    name == "parallel_executor"
                ) else [(name, args)] if use_sandbox else [
                    (name, {"label": f"{args['label']}:{side}"}) for side in ("L", "R")
                ]
                calls = [{"id": f"call-{route}-{len(state['requests'][route])}-{i}", "type": "function",
                          "function": {"name": tool_name, "arguments": json.dumps(arguments)}}
                         for i, (tool_name, arguments) in enumerate(actions)]
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
                              ("model-tool-io", 24), ("sandbox", 16), ("mcp-session", 2)]
    })
    manager.start()
    outputs, infos = [], []
    try:
        async with server:
            for batch in range(1 if cancel_one or use_sandbox else 2):
                current = []
                for root in range(1 if use_sandbox else 3):
                    models, children = [], []
                    workspace = sandbox_workspace / f"root{root}" if use_sandbox else None
                    uploader = ToolConfig(name="upload_to_s3", class_name="UploadToS3Tool", source="builtin",
                                          params={"workspace_path": str(workspace)},
                                          metadata={"run_id": f"root{root}", "minio_client": storage})
                    for route in [f"root{root}", *(f"child{root}{letter}" for letter in "ABC")]:
                        profile = profile_for(url + "/" + route, protocol)
                        models.append(ModelConfig(cite_name=route, model_name=profile.identity.request_model_id,
                                                  url=profile.connection.base_url, api_key="fixture-only",
                                                  resolved_profile=profile))
                    for letter in "ABC":
                        children.append(AgentConfig(name=f"child_{root}_{letter}", description="Owned child",
                            agent_core="jiuwen", model_name=f"child{root}{letter}", max_steps=3,
                            tools=[helper, uploader] if use_sandbox else [
                                helper, ToolConfig(name=Echo.name, class_name=class_name, source="local", params={}),
                            ]))
                    config = AgentConfig(name=f"root{root}", description="Parallel fixture", model_name=f"root{root}",
                        agent_core="jiuwen", max_steps=3, worker_agents=children,
                        tools=[helper, uploader] if use_sandbox else [helper])
                    current.append(AgentRunInfo(query=f"Run batch {batch}", agent_config=config,
                        model_config_list=models, observer=MessageObserver(lang="en"), stop_event=Event(),
                        thread_manager=manager, tenant_id="spike-tenant", user_id="fixture",
                        collaboration_timeout_seconds=25 if sandbox_timeout else 60 if use_sandbox else 10,
                        workspace_path=str(workspace) if use_sandbox else None,
                        workspace_run_id=workspace.name if use_sandbox else None,
                        sandbox_config=SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM,
                            docker_image="nexent/nexent-sandbox-full:latest", failure_policy="error")
                        if use_sandbox else None))
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
                    try:
                        if use_sandbox:
                            async with asyncio.timeout(45):
                                while not await manager.run(
                                    "background-service", ManagedTaskSpec(task_name="probe-kernel-barrier", owner=__name__),
                                    sandbox_ready, sandbox_barrier,
                                ):
                                    await asyncio.sleep(0.2)
                        else:
                            while not any(state["requests"][f"child0{letter}"] for letter in "ABC"):
                                await asyncio.sleep(0.01)
                    finally:
                        current[0].stop_event.set()

                canceller = asyncio.create_task(cancel_root()) if cancel_one else None
                try:
                    outputs.extend(await asyncio.gather(*(consume(info) for info in current)))
                finally:
                    if canceller is not None:
                        await canceller
                        if use_sandbox:
                            # A cancelled stream detaches before its run worker finishes owned cleanup.
                            await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(current[0].thread_future)), 15)
    finally:
        drained = await manager.shutdown(timeout=8)
        for task in tuple(state["handlers"]):
            task.cancel()
        await asyncio.gather(*state["handlers"], return_exceptions=True)
        assert not drained.stuck_execution_ids
        assert manager.snapshot().active_count == 0
    assert len(set(state["loops"])) == 1
    assert not state["errors"]
    if use_sandbox:
        return infos, outputs, state
    labels = [f"{root}:{letter}" for root in range(1 if cancel_one else 0, 3) for letter in "ABC"]
    if protocol == "native":
        labels = [f"{label}:{side}" for label in labels for side in ("L", "R")]
    expected = Counter({label: 1 if cancel_one else 2 for label in labels})
    assert Counter(state["effects"]) == expected
    return infos, outputs, state
