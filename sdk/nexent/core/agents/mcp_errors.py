"""Shared MCP execution error types and classifiers."""

import asyncio
from typing import Set


MCP_TOOL_TIMEOUT_TEXT = "MCP tool request timed out after"


class MCPToolTimeoutError(TimeoutError):
    """Signal that an MCP tool request must terminate the current Agent run."""

    _nexent_mcp_timeout = True


def is_mcp_timeout_error(error: BaseException) -> bool:
    """Identify MCP tool timeouts, including errors wrapped by code execution."""
    current: BaseException | None = error
    visited: Set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if getattr(current, "_nexent_mcp_timeout", False):
            return True
        if isinstance(current, (TimeoutError, asyncio.TimeoutError)):
            return True
        message = str(current).lower()
        if MCP_TOOL_TIMEOUT_TEXT.lower() in message:
            return True
        if (
            "timed out while waiting for response to" in message
            and ("clientrequest" in message or "calltoolrequest" in message)
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def propagate_mcp_timeout(error: BaseException) -> MCPToolTimeoutError:
    """Create a non-AgentError timeout that bypasses smolagents retry handling."""
    if isinstance(error, MCPToolTimeoutError):
        return error
    return MCPToolTimeoutError(str(error))
