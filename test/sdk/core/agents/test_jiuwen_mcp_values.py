# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Native MCP formatting must preserve valid JSON values before wire dispatch."""

from contextlib import nullcontext
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest
from openjiuwen.core.common.exception.errors import ExecutionError
from openjiuwen.core.foundation.tool.mcp.base import McpToolCard

from nexent.core.agents.cores.jiuwen.mcp import _ObservedMCPTool


def make_tool():
    client = Mock(call_tool=AsyncMock(return_value="accepted"))
    card = McpToolCard(name="preserve", server_name="fixture", input_params={
        "type": "object", "properties": {"payload": {}, "count": {"type": "integer"}},
        "required": ["payload", "count"], "additionalProperties": False,
    })
    observed = Mock(return_value=nullcontext())
    emitted = Mock()
    return _ObservedMCPTool(client, card, observed, emitted), client, observed, emitted


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [[], {}, None, False, 0, "", {
    "config": [], "empty_object": {}, "explicit_null": None,
    "nested": [[], {}, None, {"value": None}, False, 0, ""],
}])
async def test_native_mcp_preserves_empty_and_explicit_null_values(value):
    tool, client, observe, emit = make_tool()
    arguments = {"payload": deepcopy(value), "count": 2}
    original = deepcopy(arguments)
    result = await tool.invoke(arguments)
    client.call_tool.assert_awaited_once_with(tool_name="preserve", arguments=original)
    observe.assert_called_once_with("preserve", original)
    emit.assert_called_once_with(result)
    assert arguments == original


@pytest.mark.asyncio
async def test_caller_cannot_restore_lossy_value_cleanup():
    tool, client, _, _ = make_tool()
    await tool.invoke({"payload": {"config": [], "value": None}, "count": 2}, skip_none_value=True)
    assert client.call_tool.await_args.kwargs["arguments"]["payload"] == {"config": [], "value": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [
    {"count": 2}, {"payload": [], "count": "not-an-integer"},
    {"payload": {}, "count": None}, {"payload": {}, "count": 2, "unknown": True},
])
async def test_invalid_schema_inputs_fail_before_client_dispatch(arguments):
    tool, client, _, emit = make_tool()
    with pytest.raises(ExecutionError, match="validate data with schema failed"):
        await tool.invoke(arguments)
    client.call_tool.assert_not_awaited()
    emit.assert_not_called()
