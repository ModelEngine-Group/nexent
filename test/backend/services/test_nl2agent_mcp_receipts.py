# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Legacy MCP outputs publish only server-generated receipts for the current run."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastmcp.tools.tool import ToolResult

from tool_collection.mcp import nl2agent_mcp_service as service


@pytest.mark.asyncio
@pytest.mark.parametrize("card", [True, False])
async def test_legacy_output_is_split_into_content_and_trusted_metadata(mocker, card):
    headers = {service.NL2AGENT_RUN_ID_HEADER: "run", service.NL2AGENT_CONVERSATION_ID_HEADER: "7"}
    mocker.patch.object(service, "get_http_request", return_value=SimpleNamespace(headers=headers))
    raw = '<nl2a>\n{"card_id":"card"}\n</nl2a>\nVisible' if card else 'Visible\n<nl2a_state>{"card_id":"card"}</nl2a_state>'
    tool = AsyncMock(return_value=raw)
    result = await service._attach_receipt(tool, card=card)("arg", named=True)
    tool.assert_awaited_once_with("arg", named=True)
    assert result.content[0].text == "Visible"
    receipt = result.meta[service.NL2AGENT_RECEIPT_KEY]
    assert receipt["payload"] == {"card_id": "card"} and receipt["event_id"]
    assert receipt["run_id"] == "run" and receipt["conversation_id"] == "7"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["native", "no_request", "no_run", "no_marker", "no_card_marker"])
async def test_unmarked_or_native_outputs_are_preserved(mocker, case):
    raw = ToolResult(content="native") if case == "native" else "plain output"
    request = mocker.patch.object(service, "get_http_request", return_value=SimpleNamespace(headers={
        service.NL2AGENT_RUN_ID_HEADER: "run",
    }))
    if case == "no_request":
        request.side_effect = RuntimeError("outside HTTP context")
    elif case == "no_run":
        request.return_value.headers = {}
    result = await service._attach_receipt(AsyncMock(return_value=raw), card=case == "no_card_marker")()
    assert result is raw
    if case == "native":
        request.assert_not_called()
