# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserve local MCP result receipts across the canonical SDK configuration boundary."""

import pytest

from nexent.core.agents.resources.mcp import _normalize_mcp_config


def test_normalization_preserves_callable_result_receipt():
    def receipt(name, metadata):
        return name, metadata

    normalized = _normalize_mcp_config({"url": "http://local/mcp", "on_tool_result": receipt})
    assert normalized["on_tool_result"] is receipt
    assert normalized["transport"] == "streamable-http"


@pytest.mark.parametrize("receipt", [None, "callback", False])
def test_normalization_does_not_forward_noncallable_receipts(receipt):
    normalized = _normalize_mcp_config({"url": "http://local/mcp", "on_tool_result": receipt})
    assert "on_tool_result" not in normalized
