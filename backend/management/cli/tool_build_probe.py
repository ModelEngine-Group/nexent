# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Trusted sidecar for checking one business rule against a locally isolated MCP build."""

import asyncio
import json
from pathlib import Path

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from contracts.evolution import ToolUseRule
from management.cli.tool_repair_check import check_session
from nexent.core.agents.resources.replay_tools import argument_digest


async def probe(request):
    rule = ToolUseRule.model_validate(request["rule"])
    port = request["port"]
    while True:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.15)
        else:
            writer.close()
            await writer.wait_closed()
            break
    connect = sse_client if request["transport"] == "sse" else streamable_http_client
    url = f"http://127.0.0.1:{port}{request['path']}"
    async with connect(url) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            return await check_session(session, rule, include_evidence=True)


def main():
    request = json.loads(Path("/tmp/nexent-tool-case.json").read_bytes())
    try:
        result = asyncio.run(asyncio.wait_for(probe(request), timeout=40))
    except Exception as exc:
        result = {"status": "missing_evidence", "reasons": [type(exc).__name__]}
    print(
        json.dumps(
            {"nonce": request["nonce"], "rule_digest": argument_digest(request["rule"]), "result": result},
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
