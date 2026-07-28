import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from consts.model import HistoryItem, NL2AgentRunRequest
from services.nl2agent_service import (
    build_nl2agent_run_info,
    create_nl2agent_stream,
    search_installed_mcp_tools_by_query,
)


def test_search_filters_catalog_and_returns_safe_metadata(mocker):
    query_tools = mocker.patch(
        "services.nl2agent_service.query_all_tools",
        return_value=[
            {
                "tool_id": 8,
                "name": "weather_search",
                "origin_name": "weather",
                "description": "Search weather forecasts",
                "source": "mcp",
                "usage": "weather-server",
                "labels": ["Weather", "Forecast"],
                "is_available": True,
                "params": {"token": "secret"},
            },
            {
                "tool_id": 9,
                "name": "disabled_weather",
                "description": "Search weather forecasts",
                "source": "mcp",
                "usage": "weather-server",
                "is_available": False,
            },
            {
                "tool_id": 10,
                "name": "local_weather",
                "description": "Search weather forecasts",
                "source": "local",
                "is_available": True,
            },
        ],
    )

    result = search_installed_mcp_tools_by_query(
        "tenant-a",
        "weather forecast search",
    )

    query_tools.assert_called_once_with(tenant_id="tenant-a")
    assert len(result) == 1
    assert result[0].tool_id == 8
    assert result[0].source == "mcp"
    assert result[0].labels == ["Weather", "Forecast"]
    assert "params" not in result[0].model_dump()


def test_search_sorts_ties_by_tool_id_and_limits_to_five(mocker):
    mocker.patch(
        "services.nl2agent_service.query_all_tools",
        return_value=[
            {
                "tool_id": tool_id,
                "name": f"tool_{tool_id}",
                "description": "matching tool",
                "source": "mcp",
                "usage": "server",
                "is_available": True,
            }
            for tool_id in [9, 2, 7, 1, 5, 3]
        ],
    )
    mocker.patch("services.nl2agent_service.fuzz.WRatio", return_value=80)
    mocker.patch(
        "services.nl2agent_service.fuzz.token_set_ratio",
        return_value=80,
    )

    result = search_installed_mcp_tools_by_query(
        "tenant-a",
        "weather forecast search",
    )

    assert [item.tool_id for item in result] == [1, 2, 3, 5, 7]
    assert all(item.score == 0.8 for item in result)


def test_search_filters_scores_below_threshold(mocker):
    mocker.patch(
        "services.nl2agent_service.query_all_tools",
        return_value=[
            {
                "tool_id": 1,
                "name": "unrelated",
                "description": "unrelated",
                "source": "mcp",
                "usage": "server",
                "is_available": True,
            }
        ],
    )
    mocker.patch("services.nl2agent_service.fuzz.WRatio", return_value=44.9)
    mocker.patch(
        "services.nl2agent_service.fuzz.token_set_ratio",
        return_value=20,
    )

    assert search_installed_mcp_tools_by_query(
        "tenant-a",
        "weather forecast search",
    ) == []


@pytest.mark.asyncio
async def test_build_run_info_is_ephemeral(mocker):
    mocker.patch(
        "services.nl2agent_service.join_minio_file_description_to_query",
        new_callable=AsyncMock,
        return_value="final query",
    )
    mocker.patch(
        "services.nl2agent_service.create_model_config_list",
        new_callable=AsyncMock,
        return_value=[],
    )
    mocker.patch(
        "services.nl2agent_service.LOCAL_MCP_SERVER",
        "http://local-mcp:5011",
    )
    request = NL2AgentRunRequest(
        query="Build a weather agent",
        history=[HistoryItem(role="user", content="Earlier request")],
    )

    run_info = await build_nl2agent_run_info(
        request,
        "tenant-a",
        "en",
        "Bearer tenant-token",
    )

    assert run_info.query == "final query"
    assert run_info.agent_config.name == "__nl2agent_runtime__"
    assert run_info.history[0].content == "Earlier request"
    assert run_info.mcp_host == [
        {
            "url": "http://local-mcp:5011/sse",
            "transport": "sse",
            "headers": {"Authorization": "Bearer tenant-token"},
        }
    ]
    assert run_info.sandbox_config is None
    assert run_info.redis_client is None
    assert run_info.enable_planning is False


@pytest.mark.asyncio
async def test_create_stream_wraps_sdk_chunks_and_stops_run(mocker):
    run_info = MagicMock()
    run_info.stop_event = MagicMock()
    build_run_info = mocker.patch(
        "services.nl2agent_service.build_nl2agent_run_info",
        new_callable=AsyncMock,
        return_value=run_info,
    )

    async def fake_agent_run(received_run_info):
        assert received_run_info is run_info
        yield json.dumps({"type": "tool", "content": "call"})
        yield json.dumps(
            {
                "type": "nl2a",
                "tool_name": "search_installed_mcp_tools",
                "content": json.dumps(
                    {
                        "status": "success",
                        "recommendation_count": 0,
                        "recommendations": [],
                    }
                ),
            }
        )

    mocker.patch(
        "services.nl2agent_service.agent_run",
        side_effect=fake_agent_run,
    )
    request = NL2AgentRunRequest(query="Build a weather agent")

    stream = await create_nl2agent_stream(
        request,
        "tenant-a",
        "en",
        "Bearer tenant-token",
    )
    chunks = [chunk async for chunk in stream]

    build_run_info.assert_awaited_once_with(
        request=request,
        tenant_id="tenant-a",
        language="en",
        authorization="Bearer tenant-token",
    )
    assert chunks == [
        'data: {"type": "tool", "content": "call"}\n\n',
        (
            'data: {"type": "nl2a", '
            '"tool_name": "search_installed_mcp_tools", '
            '"content": "{\\"status\\": \\"success\\", '
            '\\"recommendation_count\\": 0, \\"recommendations\\": []}"}\n\n'
        ),
    ]
    run_info.stop_event.set.assert_called_once_with()
