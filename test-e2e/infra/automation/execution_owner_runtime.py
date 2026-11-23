# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Run the real CodeAgent reader against an authorized PostgreSQL history snapshot."""

import asyncio
import json
import threading
from contextlib import nullcontext
from unittest.mock import Mock

from jiuwen_bridge_fixture import profile_for
from nexent.core.agents.context import ContextManagerConfig
from nexent.core.agents.context.authorized_input import build_authorized_context_input
from nexent.core.agents.context.execution_history import ExecutionHistory
from nexent.core.agents.contracts.config import AgentConfig, ModelConfig, ToolConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
from nexent.core.agents.orchestration.entry import agent_run
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.core.tools.read_execution_output_tool import ReadExecutionOutputTool
from nexent.core.utils.observer import MessageObserver


async def run_historical_reader(
    monkeypatch, historical, reference, expected, *, seed=False, protocol="native"
):
    state = {
        "requests": [],
        "reads": [],
        "errors": [],
        "owners": [],
        "business_calls": 0,
        "read_attempts": [],
    }
    forward = ReadExecutionOutputTool.forward
    run = CoreAgent.run

    def read(tool, output_ref, offset=0, max_chars=4000):
        state["read_attempts"].append(output_ref)
        result = forward(tool, output_ref, offset, max_chars)
        state["reads"].append((output_ref, json.loads(result)))
        return result

    def start(core, *args, **kwargs):
        result = run(core, *args, **kwargs)
        state["owners"].append(
            (
                core._execution_owner,
                core.tools["read_execution_output"].owner,
            )
        )
        return result

    monkeypatch.setattr(ReadExecutionOutputTool, "forward", read)
    monkeypatch.setattr(CoreAgent, "run", start)
    monitoring = Mock()
    monitoring.trace_llm_request.side_effect = lambda *args, **kwargs: nullcontext(None)
    monkeypatch.setattr(
        "nexent.core.model_service.service.get_monitoring_manager", lambda: monitoring
    )

    async def handle(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            size = int(
                next(
                    line.split(b":", 1)[1]
                    for line in headers.split(b"\r\n")
                    if line.lower().startswith(b"content-length:")
                )
            )
            body = json.loads(await reader.readexactly(size))
            state["requests"].append(body)
            if seed and len(state["requests"]) == 1:
                content = "<code>print(owner_source())</code>"
            elif seed:
                assert state["business_calls"] == 1
                content = "<final_answer>SEED_SAVED</final_answer>"
            elif len(state["requests"]) == 1:
                # The provider must select a reference already advertised by the server,
                # not inject an arbitrary database ID through the user instruction.
                assert reference in json.dumps(body["messages"])
                content = (
                    "<code>result = read_execution_output(output_ref="
                    + repr(reference)
                    + ")\nprint(result)</code>"
                )
            else:
                assert state["reads"] == [
                    (
                        reference,
                        {"text": expected, "next_offset": len(expected), "eof": True},
                    )
                ]
                assert "original row" in json.dumps(body["messages"])
                assert "next_offset" in json.dumps(body["messages"])
                content = "<final_answer>AUTHORIZED_ORIGINAL_READ</final_answer>"
            value = {
                "id": "reader-response",
                "model": body["model"],
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            }
            if body.get("stream"):
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n"
                )
                chunk = {
                    **value,
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "delta": value["choices"][0]["message"],
                            "finish_reason": None,
                        }
                    ],
                }
                chunk.pop("usage")
                writer.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                chunk.update(
                    usage=value["usage"],
                    choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}],
                )
                writer.write(
                    ("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode()
                )
            else:
                payload = json.dumps(value).encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                    + str(len(payload)).encode()
                    + b"\r\nConnection: close\r\n\r\n"
                    + payload
                )
            await writer.drain()
        except Exception as error:
            state["errors"].append(repr(error))
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    manager = ThreadManager(
        "execution-owner-proof",
        {
            name: LanePolicy(name=name, max_workers=2, max_queue_size=8)
            for name in (
                "agent-run",
                "model-tool-io",
                "mcp-session",
                "control-io",
                "sandbox",
                "background-service",
            )
        },
    )
    manager.start()
    try:
        url = "http://127.0.0.1:" + str(server.sockets[0].getsockname()[1])
        profile = profile_for(url, protocol)
        from smolagents import Tool
        import nexent.core.tools as tool_types
        from nexent.core.agents.cores.smolagents import agent as smol_tools

        class OwnerSourceTool(Tool):
            name, description, inputs, output_type = (
                "owner_source",
                "Get the original source",
                {},
                "string",
            )

            def forward(self):
                state["business_calls"] += 1
                return json.dumps(
                    [{"id": i, "value": "original row"} for i in range(5)]
                )

        monkeypatch.setattr(
            tool_types, "OwnerSourceTool", OwnerSourceTool, raising=False
        )
        monkeypatch.setattr(
            smol_tools, "OwnerSourceTool", OwnerSourceTool, raising=False
        )
        observer = MessageObserver(lang="en")
        observer.execution_history = ExecutionHistory()
        info = AgentRunInfo(
            query="Read the authorized original already advertised in history exactly once.",
            observer=observer,
            stop_event=threading.Event(),
            thread_manager=manager,
            tenant_id="spike-tenant",
            model_config_list=[
                ModelConfig(
                    cite_name="fixture",
                    model_name=profile.identity.request_model_id,
                    url=profile.connection.base_url,
                    api_key="fixture-only",
                    resolved_profile=profile,
                )
            ],
            agent_config=AgentConfig(
                agent_core="smolagents",
                name="historical_reader",
                description="Reader proof",
                model_name="fixture",
                context_manager_config=ContextManagerConfig(
                    context_window_tokens=200000, effective_input_limit_tokens=200000
                ),
                max_steps=3,
                tools=(
                    [
                        ToolConfig(
                            name="owner_source",
                            class_name="OwnerSourceTool",
                            source="local",
                            params={},
                        )
                    ]
                    if seed
                    else []
                ),
                instructions="Use the read_execution_output tool.",
            ),
        )
        info.context_input = build_authorized_context_input(info, historical)
        output = [
            json.loads(event) async for event in agent_run(info, thread_manager=manager)
        ]
        assert info.attempt_outcome == "completed", (output[-2:], state["errors"])
        expected_final = "SEED_SAVED" if seed else "AUTHORIZED_ORIGINAL_READ"
        assert expected_final == "".join(
            event.get("content", "")
            for event in output
            if event.get("type") == "final_answer"
        )
        assert len(state["requests"]) == 2 and len(state["reads"]) == (0 if seed else 1)
        assert state["read_attempts"] == ([] if seed else [reference])
        assert not state["errors"]
        assert len(state["owners"]) == 1
        if not seed:
            assert len(set(state["owners"][0])) == 1
        return info, output, state
    finally:
        drained = await manager.shutdown(timeout=5)
        server.close()
        await server.wait_closed()
        assert not drained.stuck_execution_ids and manager.snapshot().active_count == 0
