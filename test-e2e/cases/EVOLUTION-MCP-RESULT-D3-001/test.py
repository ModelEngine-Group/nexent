# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise both managed cores against a real, loopback-only MCP business fixture."""

import asyncio
import json
import socket
import sys
from contextlib import ExitStack
from pathlib import Path
from threading import Thread
from time import monotonic, sleep

import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "sdk"), str(ROOT)]


@pytest.mark.case_id("EVOLUTION-MCP-RESULT-D3-001")
@pytest.mark.stage("D3")
@pytest.mark.parametrize("core", ["smolagents", "jiuwen"])
def test_business_reply(core):
    from contracts.agentos import ReplayToolObservation
    from management.services.evaluation.tool_use import judge_tool_use
    from nexent.core.agents.contracts.config import ToolConfig
    from nexent.core.agents.cores.jiuwen.mcp import JiuwenMCPCollection
    from nexent.core.agents.resources.mcp import ManagedMCPToolCollection
    from nexent.core.agents.resources.replay_tools import ReplayToolRecorder, argument_digest
    from nexent.core.concurrency import LanePolicy, RunCancellationScope, ThreadManager

    service = FastMCP("demo-ledger", stateless_http=True, json_response=True)
    state = {"receipt": ""}
    wire = []

    @service.resource("nexent-eval://fixture/state")
    def ledger() -> str:
        return json.dumps(state)

    @service.tool()
    def post_receipt(reference: str) -> str:
        """Record a synthetic delivery receipt."""
        wire.append(reference)
        state["receipt"] = reference if reference == "GOOD" else reference.lower()
        return "accepted"

    with ExitStack() as cleanup:
        sock = cleanup.enter_context(socket.socket())
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(service.streamable_http_app(), log_level="error"))
        thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        cleanup.callback(thread.join, 6)
        cleanup.callback(setattr, server, "should_exit", True)
        deadline = monotonic() + 8
        while not server.started and thread.is_alive() and monotonic() < deadline:
            sleep(0.02)
        assert server.started
        manager = ThreadManager(
            "result-check", {lane: LanePolicy(lane, 3, 3) for lane in ("mcp-session", "model-tool-io")}
        )
        manager.start()
        cleanup.callback(lambda: asyncio.run(manager.shutdown(timeout=5)))
        name = "post_receipt"
        recorder = ReplayToolRecorder(
            None,
            {name: ["reference"]},
            watch_mcp_replies={name: {"kind": "text", "initial_digest": argument_digest({"receipt": ""})}},
        )
        options = dict(
            manager=manager,
            server_parameters=[{"url": f"http://127.0.0.1:{port}/mcp", "transport": "streamable-http"}],
            tool_timeout_seconds=10,
            close_timeout_seconds=3,
            cancellation_scope=RunCancellationScope(),
        )
        if core == "jiuwen":
            owner = JiuwenMCPCollection(
                **options,
                authorized_tools=[ToolConfig(name=name, class_name=name, source="mcp")],
                observe=lambda *_: None,
                replay_recorder=recorder,
            )
        else:
            owner = ManagedMCPToolCollection(**options)
        cleanup.enter_context(owner)
        tool = owner.tools[0]
        if core == "smolagents":
            recorder.bind(tool, name, mapping_input=True)
        for reference in ("BAD", "GOOD"):
            state["receipt"] = ""
            args = {"reference": reference}
            if core == "smolagents":
                assert tool.forward(**args) == "accepted"
            else:
                assert "accepted" in str(asyncio.run(tool.invoke(args)))
            receipt = recorder.receipt()
            observation = ReplayToolObservation.model_validate({**receipt, "calls": receipt["calls"][-1:]})
            expected = {
                "kind": "text",
                "value": "accepted",
                "fixture": {"initial": {"receipt": ""}, "final": {"receipt": reference}},
            }
            rule = {
                "name": name,
                "arguments": args,
                "min_calls": 1,
                "max_calls": 1,
                "expected_mcp_reply": expected,
            }
            grade = judge_tool_use({"rules": [rule]}, observation)
            assert grade["status"] == ("pass" if reference == "GOOD" else "fail"), grade
            (evidence,) = grade["mcp_evidence"]
            assert evidence["remote"] == name and evidence["input_matches"] and evidence["reply_matches"]
            assert evidence["state_matches"] == (reference == "GOOD")
            assert reference not in json.dumps(receipt)
            expected["fixture"]["initial"] = {"receipt": "other"}
            assert judge_tool_use({"rules": [rule]}, observation)["reason"] == "unverified_mcp_fixture"
        # The ledger still contains GOOD. A further call must stop before sending a write.
        try:
            if core == "smolagents":
                tool.forward(reference="UNSENT")
            else:
                asyncio.run(tool.invoke({"reference": "UNSENT"}))
        except Exception:
            pass
        assert recorder.receipt()["calls"][-1]["mcp_fixture_unready"]
        assert wire == ["BAD", "GOOD"] and state["receipt"] == "GOOD"
