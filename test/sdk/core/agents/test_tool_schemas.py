# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""DB-cached MCP schema parsing for lazy tool construction."""

import pytest
from nexent.core.agents.contracts.config import ToolConfig
from nexent.core.agents.resources.tool_schemas import parse_mcp_tool_inputs


def _config(inputs):
    return ToolConfig(class_name="lookup", name="lookup", source="mcp", inputs=inputs)


def test_parses_standard_json_cache():
    properties = parse_mcp_tool_inputs(_config('{"a": {"type": "string"}, "b": {"type": "integer"}}'))
    assert properties == {"a": {"type": "string"}, "b": {"type": "integer"}}


def test_parses_legacy_python_repr_cache():
    # Rows written before the JSON migration store a Python dict repr.
    properties = parse_mcp_tool_inputs(_config("{'a': {'type': 'string', 'description': 'see tool description'}}"))
    assert properties == {"a": {"type": "string", "description": "see tool description"}}


@pytest.mark.parametrize("inputs", [None, "", "   ", "not-a-dict", "[1, 2]"])
def test_unreadable_cache_fails_construction_with_refresh_hint(inputs):
    with pytest.raises(ValueError, match="refresh the MCP tool list"):
        parse_mcp_tool_inputs(_config(inputs))
