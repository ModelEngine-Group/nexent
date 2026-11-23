# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run one approved reproduction or protection task against a maintainer's isolated MCP build."""

import argparse
import asyncio
import json
from pathlib import Path

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from contracts.agentos import ReplayToolObservation
from contracts.tool_repair import ToolReproductionSuite
from management.services.evaluation.tool_use import judge_tool_use
from nexent.core.agents.resources.replay_mcp import call_session_tool, capture_reply
from nexent.core.agents.resources.replay_tools import argument_digest


async def check_session(session, rule, *, include_evidence=False):
    expected = rule.expected_mcp_reply
    call = {
        "name": rule.name,
        "start": 1,
        "end": 2,
        "outcome": "pending",
        "arguments": {key: argument_digest(value) for key, value in rule.arguments.items()},
    }
    probe = {"kind": expected.kind, "initial_digest": argument_digest(expected.fixture.initial)}
    with capture_reply(call, list(rule.arguments), probe):
        try:
            await call_session_tool(session, rule.name, rule.arguments)
            call["outcome"] = "returned"
        except Exception:
            call["outcome"] = "raised"
    observation = ReplayToolObservation(registered=[rule.name], calls=[call], complete=True)
    grade = judge_tool_use({"rules": [rule.model_dump(mode="json")]}, observation)
    return {
        "status": grade["status"],
        **({"observation": grade["mcp_evidence"][0]} if include_evidence and grade.get("mcp_evidence") else {}),
        "reasons": [grade["reason"]] if "reason" in grade else [issue["reason"] for issue in grade["issues"]],
    }


async def run_case(path, label, fixture_url, transport):
    # The suite cannot choose its destination. The service owner supplies a test endpoint.
    with path.open("rb") as source:
        payload = source.read(1024 * 1024 + 1)
    if len(payload) > 1024 * 1024:
        raise ValueError("Oversized test suite")
    suite = ToolReproductionSuite.model_validate_json(payload)
    connect = sse_client if transport == "sse" else streamable_http_client
    async with connect(fixture_url) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            result = await check_session(session, getattr(suite, label))
    return {"suite_digest": argument_digest(suite.model_dump(mode="json")), "case": label, **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("--case", required=True, choices=["failure", "protection"])
    parser.add_argument(
        "--fixture-url", required=True, help="Isolated MCP test service with the approved initial state"
    )
    parser.add_argument("--transport", choices=["streamable-http", "sse"], default="streamable-http")
    options = parser.parse_args()
    try:
        result = asyncio.run(
            asyncio.wait_for(run_case(options.suite, options.case, options.fixture_url, options.transport), 60)
        )
    except Exception as exc:
        print(json.dumps({"status": "missing_evidence", "reason": type(exc).__name__}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return {"pass": 0, "fail": 1, "missing_evidence": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
