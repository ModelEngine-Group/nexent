"""Deterministic Streamable HTTP MCP server for the isolated daily stack."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from fastmcp import FastMCP


mcp = FastMCP(
    "nexent-daily-controlled-mcp",
    instructions="Deterministic tools used only by the isolated Nexent test suite.",
)
_WIRE_LOCK = Lock()


def _record(tool: str, arguments: dict[str, Any], result: Any = None, error: str = "") -> None:
    configured = os.environ.get("NEXENT_TEST_MCP_WIRE_LOG", "").strip()
    if not configured:
        return
    path = Path(configured)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "arguments": arguments,
        "result": result,
        "error": error,
    }
    with _WIRE_LOCK, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


@mcp.tool
def deterministic_add(left: int, right: int) -> int:
    """Return the exact sum of two integers."""
    result = left + right
    _record("deterministic_add", {"left": left, "right": right}, result)
    return result


@mcp.tool
def add(left: int, right: int) -> int:
    """Compatibility alias for deterministic addition."""
    result = left + right
    _record("add", {"left": left, "right": right}, result)
    return result


@mcp.tool
def echo(value: str) -> str:
    """Return the supplied non-secret test value unchanged."""
    _record("echo", {"value": value}, value)
    return value


@mcp.tool
def get_test_code() -> str:
    """Return the fixed browser/tool-call oracle."""
    result = "NX-92831"
    _record("get_test_code", {}, result)
    return result


@mcp.tool
def require_header(name: str, value: str) -> str:
    """Record a controlled header-shaped value passed by the Nexent tool binding."""
    result = f"HEADER_OK:{name}"
    _record("require_header", {"name": name, "value": value}, result)
    return result


@mcp.tool
def require_metadata(test_run_id: str) -> str:
    """Return a stable marker proving runtime metadata reached the tool arguments."""
    result = f"METADATA_OK:{test_run_id}"
    _record("require_metadata", {"test_run_id": test_run_id}, result)
    return result


@mcp.tool
async def controlled_delay(milliseconds: int = 10) -> str:
    """Wait for a bounded interval and return a stable marker."""
    delay = min(max(milliseconds, 0), 2_000)
    await asyncio.sleep(delay / 1_000)
    result = f"CONTROLLED_DELAY_OK:{delay}"
    _record("controlled_delay", {"milliseconds": milliseconds}, result)
    return result


@mcp.tool
async def sleep(milliseconds: int = 10) -> str:
    """Compatibility delay tool with a bounded two-second maximum."""
    delay = min(max(milliseconds, 0), 2_000)
    await asyncio.sleep(delay / 1_000)
    result = f"SLEEP_OK:{delay}"
    _record("sleep", {"milliseconds": milliseconds}, result)
    return result


@mcp.tool
def always_fail(code: str = "CONTROLLED_FAILURE") -> str:
    """Raise a deterministic error used to verify product error rendering."""
    _record("always_fail", {"code": code}, error=code)
    raise RuntimeError(code)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=19190)
    args = parser.parse_args()
    mcp.run(
        transport="http",
        host=args.host,
        port=args.port,
        path="/mcp",
        stateless_http=True,
        show_banner=False,
    )


if __name__ == "__main__":
    main()
