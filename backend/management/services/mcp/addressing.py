# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Utilities for constructing tenant-scoped MCP URLs."""

from urllib.parse import quote, urljoin

import consts.const as const


def get_tenant_local_mcp_server(tenant_id: str) -> str:
    """Return the tenant-scoped SSE endpoint for built-in/API-converted tools."""
    if not tenant_id:
        raise ValueError("tenant_id is required for the local MCP endpoint")
    return urljoin(
        const.LOCAL_MCP_SERVER.rstrip("/") + "/",
        f"mcp/{quote(str(tenant_id), safe='')}/sse",
    )
