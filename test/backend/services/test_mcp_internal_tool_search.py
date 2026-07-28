import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP
from mcp.types import Tool

import services.nl2agent_service as nl2agent_service
import services.tool_configuration_service as tool_configuration_service
import tool_collection.mcp.local_mcp_service as local_mcp_service_module
from services.tool_configuration_service import get_tool_from_remote_mcp_server
from tool_collection.mcp.local_mcp_service import (
    LOCAL_MCP_TOOL_NAME_OVERRIDES,
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    local_mcp_service,
    search_installed_mcp_tools,
)


@pytest.mark.asyncio
async def test_mcp_search_is_tenant_scoped_sorted_and_safe(mocker):
    mocker.patch.object(
        local_mcp_service_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer tenant-token"}),
    )
    get_current_user_id = mocker.patch.object(
        local_mcp_service_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    query_all_tools = mocker.patch.object(
        nl2agent_service,
        "query_all_tools",
        return_value=[
            {
                "tool_id": 12,
                "name": "secondary_weather",
                "origin_name": "secondary-weather",
                "description": "Secondary weather forecast search",
                "source": "mcp",
                "usage": "weather-server-b",
                "labels": ["weather"],
                "is_available": True,
                "params": {"token": "must-not-leak"},
            },
            {
                "tool_id": 7,
                "name": "primary_weather",
                "origin_name": "primary-weather",
                "description": "Primary weather forecast search",
                "source": "mcp",
                "usage": "weather-server-a",
                "labels": ["weather", "forecast"],
                "is_available": True,
                "request_headers": {"Authorization": "must-not-leak"},
            },
            {
                "tool_id": 8,
                "name": "disabled_weather",
                "description": "Weather forecast search",
                "source": "mcp",
                "usage": "weather-server-a",
                "is_available": False,
            },
            {
                "tool_id": 9,
                "name": "local_weather",
                "description": "Weather forecast search",
                "source": "local",
                "usage": "local",
                "is_available": True,
            },
        ],
    )

    def score_by_document(_query, document):
        return 95 if "primary_weather" in document else 75

    mocker.patch.object(
        nl2agent_service.fuzz,
        "WRatio",
        side_effect=score_by_document,
    )
    mocker.patch.object(
        nl2agent_service.fuzz,
        "token_set_ratio",
        side_effect=score_by_document,
    )

    result = json.loads(
        await search_installed_mcp_tools.fn(
            [" Weather ", "forecast", "WEATHER"]
        )
    )

    get_current_user_id.assert_called_once_with("Bearer tenant-token")
    query_all_tools.assert_called_once_with(tenant_id="tenant-a")
    assert {
        call.args[0]
        for call in nl2agent_service.fuzz.WRatio.call_args_list
    } == {"weather forecast"}
    assert {
        call.args[0]
        for call in nl2agent_service.fuzz.token_set_ratio.call_args_list
    } == {"weather forecast"}
    assert result["status"] == "success"
    assert result["recommendation_count"] == 2
    assert set(result) == {"status", "recommendation_count", "recommendations"}
    assert [item["tool_id"] for item in result["recommendations"]] == [7, 12]
    assert result["recommendations"][0] == {
        "tool_id": 7,
        "name": "primary_weather",
        "origin_name": "primary-weather",
        "description": "Primary weather forecast search",
        "source": "mcp",
        "usage": "weather-server-a",
        "labels": ["weather", "forecast"],
        "score": 0.95,
    }
    safe_fields = {
        "tool_id",
        "name",
        "origin_name",
        "description",
        "source",
        "usage",
        "labels",
        "score",
    }
    assert all(set(item) == safe_fields for item in result["recommendations"])
    assert "must-not-leak" not in json.dumps(result)


@pytest.mark.asyncio
async def test_mcp_search_returns_sanitized_contract_errors(mocker):
    for keywords in ([], ["   "]):
        invalid_result = json.loads(
            await search_installed_mcp_tools.fn(keywords)
        )
        assert invalid_result == {
            "status": "error",
            "code": "invalid_keywords",
            "retryable": True,
        }

    mocker.patch.object(
        local_mcp_service_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer private-token"}),
    )
    mocker.patch.object(
        local_mcp_service_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch.object(
        nl2agent_service,
        "search_installed_mcp_tools_by_query",
        side_effect=RuntimeError("private database details"),
    )

    result_text = await search_installed_mcp_tools.fn(["private", "weather"])

    assert json.loads(result_text) == {
        "status": "error",
        "code": "tool_search_failed",
        "retryable": True,
    }
    assert "private-token" not in result_text
    assert "private database details" not in result_text


@pytest.mark.asyncio
async def test_mcp_search_registration_has_stable_name_schema_and_marker():
    parent = FastMCP("test-parent")
    parent.mount(
        local_mcp_service,
        local_mcp_service.name,
        tool_names=LOCAL_MCP_TOOL_NAME_OVERRIDES,
    )
    mounted_tools = await parent.get_tools()
    tool = mounted_tools[SEARCH_INSTALLED_MCP_TOOLS_NAME]

    assert LOCAL_MCP_TOOL_NAME_OVERRIDES == {
        SEARCH_INSTALLED_MCP_TOOLS_NAME: SEARCH_INSTALLED_MCP_TOOLS_NAME
    }
    assert f"local_{SEARCH_INSTALLED_MCP_TOOLS_NAME}" not in mounted_tools
    assert tool.name == SEARCH_INSTALLED_MCP_TOOLS_NAME
    assert set(tool.parameters["properties"]) == {"keywords"}
    assert tool.parameters["properties"]["keywords"]["type"] == "array"
    assert tool.parameters["properties"]["keywords"]["items"]["type"] == "string"
    assert tool.parameters["required"] == ["keywords"]
    assert tool.meta["nexent_internal"] is True
    assert "print(result)" in tool.description


@pytest.mark.asyncio
async def test_mcp_search_empty_result_returns_business_payload(mocker):
    mocker.patch.object(
        local_mcp_service_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer tenant-token"}),
    )
    mocker.patch.object(
        local_mcp_service_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch.object(
        nl2agent_service,
        "search_installed_mcp_tools_by_query",
        return_value=[],
    )

    result = json.loads(await search_installed_mcp_tools.fn(["weather"]))

    assert result == {
        "status": "success",
        "recommendation_count": 0,
        "recommendations": [],
    }


@pytest.mark.asyncio
async def test_public_mcp_scanner_skips_internal_tools(mocker):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.list_tools.return_value = [
        Tool(
            name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
            description="Internal search",
            inputSchema={"type": "object", "properties": {}},
            _meta={"nexent_internal": True},
        ),
        Tool(
            name="public_weather",
            description="Public weather tool",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]
    client_class = mocker.patch.object(
        tool_configuration_service,
        "Client",
        return_value=client,
    )
    transport = mocker.patch.object(
        tool_configuration_service,
        "_create_mcp_transport",
        return_value=object(),
    )

    result = await get_tool_from_remote_mcp_server(
        "outer-apis",
        "http://mcp.example/sse",
    )

    transport.assert_called_once_with("http://mcp.example/sse", None, None)
    client_class.assert_called_once()
    assert [tool.name for tool in result] == ["public_weather"]
