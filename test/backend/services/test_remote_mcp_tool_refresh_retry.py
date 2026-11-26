# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Retry boundary tests for MCP tool snapshot refresh."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest

from contracts.errors.exceptions import MCPConnectionError
from management.services.mcp import tools as mcp_tools


def _record() -> dict:
    return {
        "mcp_name": "example",
        "mcp_server": "https://srv/mcp",
        "authorization_token": None,
        "custom_headers": None,
        "registry_json": {},
    }


def _mock_refresh_dependencies(mocker):
    mocker.patch.object(mcp_tools, "get_mcp_record_by_id_and_tenant", return_value=_record())
    mocker.patch.object(mcp_tools, "_mcp_protocol_health_check", new=AsyncMock(return_value=["tool1"]))
    mocker.patch.object(mcp_tools, "get_mcp_market_record_by_source_mcp_id", return_value=None)
    update = mocker.patch.object(mcp_tools, "update_mcp_record_registry_json_by_id")
    sleep = mocker.patch.object(mcp_tools.asyncio, "sleep", new=AsyncMock())
    return update, sleep


@pytest.mark.asyncio
async def test_refresh_uses_both_backoffs_before_success(mocker):
    update, sleep = _mock_refresh_dependencies(mocker)
    discovery = mocker.patch(
        "management.services.tool.discovery.get_tool_from_remote_mcp_server",
        new=AsyncMock(side_effect=[
            MCPConnectionError("first terminated session"),
            MCPConnectionError("second terminated session"),
            [SimpleNamespace(name="tool1", description="First tool")],
        ]),
    )

    result = await mcp_tools.refresh_mcp_service_tool_count(tenant_id="tid", user_id="uid", mcp_id=1)

    assert result == ["tool1"]
    assert discovery.await_count == 3
    assert sleep.await_args_list == [call(0.2), call(0.4)]
    update.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_raises_after_final_connection_failure(mocker):
    update, sleep = _mock_refresh_dependencies(mocker)
    discovery = mocker.patch(
        "management.services.tool.discovery.get_tool_from_remote_mcp_server",
        new=AsyncMock(side_effect=MCPConnectionError("persistent terminated session")),
    )

    with pytest.raises(MCPConnectionError, match="persistent terminated session"):
        await mcp_tools.refresh_mcp_service_tool_count(tenant_id="tid", user_id="uid", mcp_id=1)

    assert discovery.await_count == 3
    assert sleep.await_args_list == [call(0.2), call(0.4)]
    update.assert_not_called()
