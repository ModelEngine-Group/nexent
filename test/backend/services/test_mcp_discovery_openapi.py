# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""OpenAPI services are scanned through the tenant MCP, never their REST address."""

from unittest.mock import AsyncMock, Mock

import pytest

from management.services.tool import discovery


@pytest.fixture
def scanner(monkeypatch):
    records = Mock(return_value=[])
    scan = AsyncMock(return_value=[])
    monkeypatch.setattr(discovery, "get_mcp_records_by_tenant", records)
    monkeypatch.setattr(discovery, "get_tool_from_remote_mcp_server", scan)
    monkeypatch.setattr(discovery, "get_tenant_local_mcp_server", lambda _: "http://local/mcp/tenant/sse")
    return records, scan


@pytest.mark.asyncio
async def test_openapi_rest_endpoint_is_skipped_and_local_tools_retained(scanner):
    records, scan = scanner
    records.return_value = [{
        "mcp_name": "weather_api", "mcp_server": "https://weather.example.test",
        "enabled": True, "status": True, "config_json": {"openapi": "3.0.3", "paths": {}},
    }]
    scan.return_value = ["converted-weather-tool"]

    assert await discovery.get_all_mcp_tools("tenant") == ["converted-weather-tool"]
    scan.assert_awaited_once_with(
        mcp_server_name="outer-apis", remote_mcp_server="http://local/mcp/tenant/sse", tenant_id="tenant",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [None, {}, {"other": "configuration"}])
async def test_normal_mcp_scan_and_credentials_are_preserved(scanner, config):
    records, scan = scanner
    records.return_value = [{
        "mcp_name": "remote", "mcp_server": "https://remote.example.test/mcp", "enabled": True,
        "status": True, "config_json": config, "authorization_token": "private-token",
        "custom_headers": {"X-Key": "private-key"},
    }]
    scan.side_effect = [["remote-tool"], ["local-tool"]]

    assert await discovery.get_all_mcp_tools("tenant") == ["remote-tool", "local-tool"]
    assert scan.await_args_list[0].kwargs == {
        "mcp_server_name": "remote", "remote_mcp_server": "https://remote.example.test/mcp",
        "tenant_id": "tenant", "authorization_token": "private-token", "custom_headers": {"X-Key": "private-key"},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,status", [(False, True), (True, False), (False, False)])
async def test_disabled_or_unhealthy_mcp_is_not_connected(scanner, enabled, status):
    records, scan = scanner
    records.return_value = [{"mcp_name": "remote", "mcp_server": "https://remote.example.test/mcp",
                             "enabled": enabled, "status": status}]
    await discovery.get_all_mcp_tools("tenant")
    assert scan.await_count == 1
    assert scan.await_args.kwargs["mcp_server_name"] == "outer-apis"


@pytest.mark.asyncio
async def test_failed_remote_identifies_service_and_keeps_local_scan(scanner, caplog):
    records, scan = scanner
    records.return_value = [{"mcp_name": "remote", "mcp_server": "https://remote.example.test/mcp",
                             "enabled": True, "status": True, "authorization_token": "private-token"}]
    scan.side_effect = [TimeoutError(), ["local-tool"]]

    assert await discovery.get_all_mcp_tools("tenant") == ["local-tool"]
    assert "service=remote" in caplog.text
    assert "TimeoutError" in caplog.text
    assert "private-token" not in caplog.text
