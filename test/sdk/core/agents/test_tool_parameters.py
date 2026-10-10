"""Regression tests for configured MCP call arguments."""

from copy import copy
from types import SimpleNamespace

import pytest

from nexent.core.agents.tool_parameters import apply_mcp_tool_parameters
from nexent.core.agents.tool_user_context import apply_user_context_to_mcp_tool


@pytest.mark.parametrize("style", ["keywords", "mapping", "positional"])
def test_configured_arguments_override_model_arguments(style):
    def add(left=0, right=0):
        if isinstance(left, dict):
            return left["left"] + left["right"]
        return left + right

    tool = SimpleNamespace(forward=add)
    apply_mcp_tool_parameters(tool, {"left": 40})
    if style == "keywords":
        assert tool.forward(left=1, right=2) == 42
    elif style == "mapping":
        assert tool.forward({"left": 1, "right": 2}) == 42
    else:
        assert tool.forward(1, 2) == 42


def test_configured_arguments_are_isolated_and_do_not_replace_identity():
    template = SimpleNamespace(inputs={"left": {}, "user_id": {}}, forward=lambda **kwargs: kwargs)
    configured = {"left": [40], "user_id": "untrusted"}
    first = copy(template)
    first.inputs = dict(template.inputs)
    apply_user_context_to_mcp_tool(first, {"user_id": "owner"})
    apply_mcp_tool_parameters(first, configured)
    configured["left"].append(99)
    result = first.forward(left=1, user_id="model")
    assert result == {"left": [40], "user_id": "owner"}
    result["left"].append(99)
    assert first.forward(left=1)["left"] == [40]
    assert template.forward(left=1) == {"left": 1}
    assert "user_id" in template.inputs


@pytest.mark.asyncio
async def test_async_tool_overrides_and_propagates_failure():
    async def add(left, right):
        if right < 0:
            raise RuntimeError("provider failure")
        return left + right

    tool = SimpleNamespace(forward=add)
    apply_mcp_tool_parameters(tool, {"left": 40})
    assert await tool.forward(left=1, right=2) == 42
    with pytest.raises(RuntimeError, match="provider failure"):
        await tool.forward(left=1, right=-1)


def test_empty_parameters_preserve_callable():
    tool = SimpleNamespace(forward=lambda value: value)
    original = tool.forward
    assert apply_mcp_tool_parameters(tool, {}) is tool
    assert tool.forward is original
