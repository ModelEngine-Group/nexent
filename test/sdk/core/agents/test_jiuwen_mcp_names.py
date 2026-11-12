# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Registered MCP names resolve without changing wire names or guessing collisions."""

from unittest.mock import AsyncMock, Mock

import pytest
from nexent.core.agents.contracts.config import ToolConfig
from nexent.core.agents.cores.jiuwen import mcp
from nexent.core.concurrency import RunCancellationScope
from openjiuwen.core.foundation.tool.mcp.base import McpToolCard


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,saved", [
    ("get-current-date", "get_current_date"), ("get-current-date", "get-current-date"),
    ("tools.date", "toolsdate"), ("123date", "_123date"), ("class", "class_"), ("date", "date"),
])
async def test_registered_name_maps_to_original_wire_and_saved_public_alias(monkeypatch, raw, saved):
    client = Mock(connect=AsyncMock(return_value=True), disconnect=AsyncMock(), list_tools=AsyncMock(return_value=[
        McpToolCard(name=raw, server_name="fixture", input_params={"type": "object", "properties": {}})]))
    monkeypatch.setattr(mcp, "_ConfiguredNativeClient", Mock(return_value=client))
    proxies = []
    original = mcp._ManagedNativeClient

    def track(*args, **kwargs):
        proxy = original(*args, **kwargs)
        proxies.append(proxy)
        return proxy

    monkeypatch.setattr(mcp, "_ManagedNativeClient", track)
    owner = mcp.JiuwenMCPCollection(manager=Mock(), cancellation_scope=RunCancellationScope(),
        server_parameters=["http://fixture/mcp"], tool_timeout_seconds=1, close_timeout_seconds=1,
        authorized_tools=[ToolConfig(name="public_date", class_name=saved, source="mcp")], observe=Mock())
    owner._close_requested.set()
    await owner._run_async_session()
    assert owner.tools[0].card.name == "public_date"
    assert len(proxies) == 1 and proxies[0].remote_name == raw
    client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("names,saved", [
    (["get-date", "get_date"], "get_date"),
    (["get.date", "getdate"], "getdate"),
    (["get-date", "get-date"], "get-date"),
    (["allowed"], "not_authorized"),
])
async def test_missing_or_ambiguous_authorized_names_fail_before_dispatch(monkeypatch, names, saved):
    client = Mock(connect=AsyncMock(return_value=True), disconnect=AsyncMock(), list_tools=AsyncMock(return_value=[
        McpToolCard(name=name, server_name="fixture", input_params={"type": "object", "properties": {}})
        for name in names]))
    monkeypatch.setattr(mcp, "_ConfiguredNativeClient", Mock(return_value=client))
    dispatch = Mock()
    monkeypatch.setattr(mcp, "_ManagedNativeClient", dispatch)
    owner = mcp.JiuwenMCPCollection(manager=Mock(), cancellation_scope=RunCancellationScope(),
        server_parameters=["http://fixture/mcp"], tool_timeout_seconds=1, close_timeout_seconds=1,
        authorized_tools=[ToolConfig(name=saved, class_name=saved, source="mcp")], observe=Mock())
    owner._close_requested.set()
    with pytest.raises(ValueError, match="missing or ambiguous"):
        await owner._run_async_session()
    dispatch.assert_not_called()
    client.disconnect.assert_awaited_once()
