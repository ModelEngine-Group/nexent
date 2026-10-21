# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tests for tenant-scoped local MCP endpoint construction."""

import consts.const as const
from management.services.mcp.addressing import get_tenant_local_mcp_server


def test_get_tenant_local_mcp_server_quotes_tenant_path(monkeypatch):
    monkeypatch.setattr(const, "LOCAL_MCP_SERVER", "http://mcp-service:5011")

    assert get_tenant_local_mcp_server("tenant/a") == (
        "http://mcp-service:5011/mcp/tenant%2Fa/sse"
    )
