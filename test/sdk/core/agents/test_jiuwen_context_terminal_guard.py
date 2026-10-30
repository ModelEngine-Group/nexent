# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Known resource failure must prevent further native-loop model requests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nexent.consts.mcp_errors import MCPToolTimeoutError
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter


@pytest.mark.asyncio
@pytest.mark.parametrize("has_mcp", [False, True])
async def test_healthy_model_preparation_preserves_messages_and_calls_cm_once(has_mcp):
    adapter = object.__new__(JiuwenAdapter)
    adapter.mcp = SimpleNamespace(terminal_error=None) if has_mcp else None
    prepared = [{"role": "user", "content": "CURRENT"}]
    adapter.context_bridge = SimpleNamespace(
        prepare_messages=AsyncMock(return_value=prepared)
    )
    source, tools = object(), object()
    assert await adapter._prepare_model_messages(source, tools) is prepared
    adapter.context_bridge.prepare_messages.assert_awaited_once_with(source, tools)


@pytest.mark.asyncio
async def test_recorded_mcp_failure_blocks_cm_and_preserves_the_original_error():
    adapter = object.__new__(JiuwenAdapter)
    error = MCPToolTimeoutError("controlled timeout")
    adapter.mcp = SimpleNamespace(terminal_error=error)
    adapter.context_bridge = SimpleNamespace(prepare_messages=AsyncMock())
    with pytest.raises(MCPToolTimeoutError) as captured:
        await adapter._prepare_model_messages([], [])
    assert captured.value is error
    adapter.context_bridge.prepare_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_mcp_failure_during_cm_blocks_the_prepared_request():
    adapter = object.__new__(JiuwenAdapter)
    error = MCPToolTimeoutError("controlled timeout")
    adapter.mcp = SimpleNamespace(terminal_error=None)

    async def prepare(messages, tools):
        adapter.mcp.terminal_error = error
        return [{"role": "user", "content": "prepared but must not send"}]

    adapter.context_bridge = SimpleNamespace(
        prepare_messages=AsyncMock(side_effect=prepare)
    )
    with pytest.raises(MCPToolTimeoutError) as captured:
        await adapter._prepare_model_messages([], [])
    assert captured.value is error
    adapter.context_bridge.prepare_messages.assert_awaited_once()


@pytest.mark.asyncio
async def test_cm_exception_is_preserved_without_retrying_preparation():
    adapter = object.__new__(JiuwenAdapter)
    error = ValueError("controlled CM failure")
    adapter.mcp = None
    adapter.context_bridge = SimpleNamespace(
        prepare_messages=AsyncMock(side_effect=error)
    )
    with pytest.raises(ValueError) as captured:
        await adapter._prepare_model_messages([], [])
    assert captured.value is error
    adapter.context_bridge.prepare_messages.assert_awaited_once()
