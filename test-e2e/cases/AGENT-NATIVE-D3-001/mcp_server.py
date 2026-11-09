# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Case-owned external MCP fixture, using the actual standard stdio protocol."""

from mcp.server.fastmcp import FastMCP

server = FastMCP("native-runtime-contract")


@server.tool()
def nexent_echo(text: str) -> str:
    """Echo an acceptance marker over the MCP protocol."""
    return "MCP_OBSERVED:" + text


if __name__ == "__main__":
    server.run(transport="stdio")
