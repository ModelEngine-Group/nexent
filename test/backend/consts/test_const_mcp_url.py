"""Tests for tenant-scoped local MCP endpoint construction."""

from consts import const
from utils.mcp_url_utils import get_tenant_local_mcp_server


def test_get_tenant_local_mcp_server_quotes_tenant_path(monkeypatch):
    monkeypatch.setattr(const, "LOCAL_MCP_SERVER", "http://mcp-service:5011")

    assert get_tenant_local_mcp_server("tenant/a") == (
        "http://mcp-service:5011/mcp/tenant%2Fa/sse"
    )
