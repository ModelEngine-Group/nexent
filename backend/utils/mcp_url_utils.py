"""Utilities for constructing tenant-scoped MCP URLs."""

from urllib.parse import quote, urljoin

from consts import const


def get_tenant_local_mcp_server(tenant_id: str) -> str:
    """Return the tenant-scoped SSE endpoint for built-in/API-converted tools."""
    if not tenant_id:
        raise ValueError("tenant_id is required for the local MCP endpoint")
    return urljoin(
        const.LOCAL_MCP_SERVER.rstrip("/") + "/",
        f"mcp/{quote(str(tenant_id), safe='')}/sse",
    )
