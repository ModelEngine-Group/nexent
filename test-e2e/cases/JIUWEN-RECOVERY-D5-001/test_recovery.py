# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded recovery through the actual Runner, model transport and tool dispatcher."""

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "sdk"), str(ROOT / "test-e2e/infra/automation")]
import jiuwen_bridge_runtime as bridge

pytestmark = [pytest.mark.case_id("JIUWEN-RECOVERY-D5-001"), pytest.mark.stage("D5")]


@asynccontextmanager
async def provider(scenario, protocol):
    state = {"requests": [], "server_errors": [], "tool_calls": [], "first_fragment_no_tool": True}

    async def handle(reader, writer):
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            size = next(
                int(line.split(b":", 1)[1])
                for line in header.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            )
            body = json.loads(await reader.readexactly(size))
            state["requests"].append(body)
            index, effects = len(state["requests"]), len(state["tool_calls"])
            invalid = scenario == "argument_step_limit" or scenario == "argument_turn_limit" and index % 2 == 1
            invalid = invalid or scenario == "arguments_after_tool" and index == 2
            invalid = invalid or scenario == "arguments_once" and index == 1
            response_fault = scenario in {"empty", "reasoning", "length", "response_limit"} and (
                index == 1 or scenario == "response_limit" and index == 2
            )
            content, calls, finish, reasoning = "RECOVERED_FINAL", [], "stop", None
            if invalid:
                calls = [
                    {
                        "id": "invalid-" + str(index),
                        "type": "function",
                        "function": {"name": "add", "arguments": '{"a":"wrong","b":3}'},
                    }
                ]
                content, finish = "", "tool_calls"
            elif scenario in {"nested_once", "nested_limit", "invalid_python", "empty_code"} and (
                index == 1 or scenario == "nested_limit"
            ):
                content = (
                    "<code>a=</code>"
                    if scenario == "invalid_python"
                    else "<code></code>"
                    if scenario == "empty_code"
                    else "<code><code>print(1)</code></code>"
                )
            elif response_fault:
                content = "PARTIAL" if scenario == "length" else ""
                reasoning = "Explicit reasoning" if scenario == "reasoning" else None
                finish = "length" if scenario == "length" else "stop"
            elif effects == 0 or scenario == "argument_turn_limit":
                if protocol == "native":
                    calls = [
                        {
                            "id": "valid-" + str(index),
                            "type": "function",
                            "function": {"name": "add", "arguments": '{"a":2,"b":3}'},
                        }
                    ]
                    content, finish = "", "tool_calls"
                else:
                    content = "<code>print(add(a=2,b=3))</code>"
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n")
            delta = {"content": content}
            if calls:
                delta["tool_calls"] = [{**call, "index": i} for i, call in enumerate(calls)]
            if reasoning:
                delta["reasoning_content"] = reasoning
            for value, end in ((delta, None), ({}, finish)):
                frame = {
                    "id": "recovery",
                    "object": "chat.completion.chunk",
                    "model": body["model"],
                    "choices": [{"index": 0, "delta": value, "finish_reason": end}],
                }
                writer.write(("data: " + json.dumps(frame) + "\n\n").encode())
                await writer.drain()
            writer.write(b"data: [DONE]\n\n")
            await writer.drain()
        except Exception as error:
            state["server_errors"].append(type(error).__name__)
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    async with server:
        yield "http://127.0.0.1:" + str(server.sockets[0].getsockname()[1]), state


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    bridge.stop_infrastructure()


@pytest.mark.parametrize(
    "scenario,protocol,requests,effects,corrections,status",
    [
        ("arguments_once", "native", 3, 1, 1, "completed"),
        ("arguments_after_tool", "native", 3, 1, 1, "completed"),
        ("argument_step_limit", "native", 2, 0, 1, "failed"),
        ("argument_turn_limit", "native", 7, 3, 3, "failed"),
        ("empty", "native", 3, 1, 1, "completed"),
        ("reasoning", "native", 3, 1, 1, "completed"),
        ("length", "native", 3, 1, 1, "completed"),
        ("response_limit", "native", 2, 0, 1, "failed"),
        ("nested_once", "text", 3, 1, 1, "completed"),
        ("nested_limit", "text", 2, 0, 1, "failed"),
        ("invalid_python", "text", 3, 1, 1, "completed"),
        ("empty_code", "text", 3, 1, 1, "completed"),
        ("empty", "text", 3, 1, 1, "completed"),
        ("length", "text", 3, 1, 1, "completed"),
    ],
)
def test_bounded_recovery_without_effect_replay(
    monkeypatch, scenario, protocol, requests, effects, corrections, status
):
    monkeypatch.setattr(bridge, "provider", provider)
    original = bridge.AgentConfig

    def config(**kwargs):
        return original(**{**kwargs, "max_steps": 12})

    monkeypatch.setattr(bridge, "AgentConfig", config)
    info, state, events = asyncio.run(bridge.run_worker(monkeypatch, protocol, scenario))
    assert info.attempt_outcome == status
    assert len(state["requests"]) == requests
    assert len(state["tool_calls"]) == effects
    recovery = [
        json.loads(e["content"]) for e in events if e["type"] == "other" and '"logical_recovery"' in e["content"]
    ]
    assert len(recovery) == corrections
    assert all(r["argument_corrections"] <= 3 and r["response_corrections"] <= 1 for r in recovery)
    assert len([e for e in events if e["type"] == "run_terminal"]) == 1
    assert info.run_result.status == status
    if status == "completed":
        assert info.run_result.final_content == "RECOVERED_FINAL" and info.run_result.error is None
    else:
        assert not info.run_result.final_content
    if scenario == "arguments_after_tool":
        assert "tool" in [m["role"] for m in state["requests"][-1]["messages"]]
    recovered, fresh, _ = asyncio.run(bridge.run_worker(monkeypatch, protocol, "normal"))
    assert recovered.attempt_outcome == "completed" and fresh["tool_calls"] == [(2, 3)]


@pytest.mark.parametrize("fault", ["cancel", "deadline"])
def test_recovery_respects_remaining_run_budget(monkeypatch, fault):
    import time

    from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter

    monkeypatch.setattr(bridge, "provider", provider)
    original = JiuwenAdapter._create_model

    def create(adapter):
        model = original(adapter)
        notify = model.on_recovery

        def stop(details):
            notify(details)
            if fault == "cancel":
                adapter.run_info.stop_event.set()
                model.scope.cancel()
            else:
                model.deadline = time.monotonic() - 1

        model.on_recovery = stop
        return model

    monkeypatch.setattr(JiuwenAdapter, "_create_model", create)
    info, state, events = asyncio.run(bridge.run_worker(monkeypatch, "native", "empty"))
    assert len(state["requests"]) == 1 and state["tool_calls"] == []
    assert info.attempt_outcome == ("stopped" if fault == "cancel" else "failed")
    assert not info.run_result.final_content
    if fault == "deadline":
        assert info.run_result.error.category == "MODEL_RUN_DEADLINE"
    monkeypatch.setattr(JiuwenAdapter, "_create_model", original)
    healthy, fresh, _ = asyncio.run(bridge.run_worker(monkeypatch, "native", "normal"))
    assert healthy.attempt_outcome == "completed" and fresh["tool_calls"] == [(2, 3)]
