# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Registered MCP names resolve without changing wire names or guessing collisions."""

from unittest.mock import AsyncMock, Mock

import pytest
from nexent.consts.mcp_errors import MCPToolNotFoundError
from nexent.core.agents.contracts.config import ToolConfig
from nexent.core.agents.cores.jiuwen import mcp
from nexent.core.concurrency import RunCancellationScope
from openjiuwen.core.foundation.tool.mcp.base import McpToolCard


def _owner(monkeypatch, client, raw, saved):
    """Build a lazy jiuwen collection with a mocked native client."""
    monkeypatch.setattr(mcp, "_ConfiguredNativeClient", Mock(return_value=client))
    proxies = []
    original = mcp._ManagedNativeClient

    def track(*args, **kwargs):
        proxy = original(*args, **kwargs)
        proxies.append(proxy)
        return proxy

    monkeypatch.setattr(mcp, "_ManagedNativeClient", track)
    owner = mcp.JiuwenMCPCollection(manager=Mock(), cancellation_scope=RunCancellationScope(),
        server_parameters=[{"url": "http://fixture/mcp", "transport": "streamable-http", "name": "fixture"}],
        tool_timeout_seconds=1, close_timeout_seconds=1, observe=Mock())
    # Direct-coroutine tests bypass _run_async_session, which owns the stack
    # in production; provide an empty one for the disconnect callback.
    owner._stack = _FakeStack()
    return owner, proxies


class _FakeStack:
    def push_async_callback(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,saved", [
    ("get-current-date", "get_current_date"), ("get-current-date", "get-current-date"),
    ("tools.date", "toolsdate"), ("123date", "_123date"), ("class", "class_"), ("date", "date"),
])
async def test_registered_name_maps_to_original_wire_and_saved_public_alias(monkeypatch, raw, saved):
    client = Mock(connect=AsyncMock(return_value=True), disconnect=AsyncMock(), list_tools=AsyncMock(return_value=[
        McpToolCard(name=raw, server_name="fixture", input_params={"type": "object", "properties": {}})]),
        call_tool=AsyncMock(return_value="wire-result"))
    owner, proxies = _owner(monkeypatch, client, raw, saved)
    tool_config = ToolConfig(name="public_date", class_name=saved, source="mcp", inputs="{}", origin_name=raw)
    tool = owner.create_tool(tool_config)
    assert tool.card.name == "public_date"
    assert len(proxies) == 1 and proxies[0].remote_name == raw

    # The lazy call reaches the server with the raw wire name from origin_name.
    result = await owner._ensure_and_call_coro("fixture", raw, {})
    assert result == "wire-result"
    client.call_tool.assert_awaited_once_with(raw, {})


@pytest.mark.asyncio
@pytest.mark.parametrize("names,saved", [
    (["get-date", "get_date"], "get_date"),
    (["get.date", "getdate"], "getdate"),
    (["get-date", "get-date"], "get-date"),
])
async def test_saved_name_dispatches_to_exact_wire_name(monkeypatch, names, saved):
    """origin_name dispatches by exact wire match; sanitized-name collisions
    are impossible because the DB keeps both names."""
    client = Mock(connect=AsyncMock(return_value=True), disconnect=AsyncMock(), list_tools=AsyncMock(return_value=[
        McpToolCard(name=name, server_name="fixture", input_params={"type": "object", "properties": {}})
        for name in names]),
        call_tool=AsyncMock(return_value="exact"))
    owner, _ = _owner(monkeypatch, client, names[0], saved)
    tool_config = ToolConfig(name=saved, class_name=saved, source="mcp", inputs="{}", origin_name=saved)
    owner.create_tool(tool_config)
    result = await owner._ensure_and_call_coro("fixture", saved, {})
    assert result == "exact"
    client.call_tool.assert_awaited_once_with(saved, {})


@pytest.mark.asyncio
async def test_absent_authorized_name_fails_before_dispatch(monkeypatch):
    """A configured tool missing from the live list fails lazily at first
    call without reaching the server's call_tool."""
    client = Mock(connect=AsyncMock(return_value=True), disconnect=AsyncMock(), list_tools=AsyncMock(return_value=[
        McpToolCard(name="allowed", server_name="fixture", input_params={"type": "object", "properties": {}})]),
        call_tool=AsyncMock(return_value="unused"))
    owner, _ = _owner(monkeypatch, client, "allowed", "not_authorized")
    tool_config = ToolConfig(name="not_authorized", class_name="not_authorized", source="mcp",
                             inputs="{}", origin_name="not_authorized")
    owner.create_tool(tool_config)
    with pytest.raises(MCPToolNotFoundError, match="not_authorized"):
        await owner._ensure_and_call_coro("fixture", "not_authorized", {})
    client.call_tool.assert_not_called()
