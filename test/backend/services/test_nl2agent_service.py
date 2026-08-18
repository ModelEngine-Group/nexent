import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from consts.model import HistoryItem, NL2AgentRunRequest
from services.nl2agent_service import (
    Nl2AgentDraftSaveError,
    build_nl2agent_run_info,
    create_nl2agent_stream,
    save_agent_draft_fields_impl,
    search_installed_mcp_tools_by_query,
)
from tool_collection.mcp.nl2agent_mcp_tools import AgentDraftFields


def _basic_draft_fields(**overrides):
    values = {
        "name": "research_assistant",
        "display_name": "Research Assistant",
        "description": "Collect and summarize reliable information.",
        "business_description": "Research, verify, and summarize findings.",
    }
    values.update(overrides)
    return AgentDraftFields(**values)


def _mock_create_dependencies(mocker, *, existing_agents=None):
    mocker.patch(
        "services.nl2agent_service.tenant_config_manager.get_model_config",
        return_value={
            "model_id": 17,
            "model_type": "llm",
            "connect_status": "available",
        },
    )
    mocker.patch(
        "services.nl2agent_service.query_all_agent_info_by_tenant_id",
        return_value=existing_agents or [],
    )
    mocker.patch(
        "services.agent_service._get_user_group_ids",
        return_value="3,5",
    )


def test_create_agent_draft_sets_ordinary_agent_defaults(mocker):
    _mock_create_dependencies(mocker)
    mocker.patch(
        "services.agent_service._check_agent_name_duplicate",
        return_value=False,
    )
    mocker.patch(
        "services.agent_service._check_agent_display_name_duplicate",
        return_value=False,
    )
    create_agent = mocker.patch(
        "services.nl2agent_service.create_agent",
        return_value={"agent_id": 1042},
    )

    result = save_agent_draft_fields_impl(
        agent_id=None,
        fields=_basic_draft_fields(),
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert result == {
        "status": "success",
        "agent_id": 1042,
        "created": True,
        "updated_fields": [
            "name",
            "display_name",
            "description",
            "business_description",
        ],
    }
    create_values = create_agent.call_args.kwargs["agent_info"]
    assert create_values == {
        "name": "research_assistant",
        "display_name": "Research Assistant",
        "description": "Collect and summarize reliable information.",
        "business_description": "Research, verify, and summarize findings.",
        "model_ids": [17],
        "prompt_template_id": 0,
        "prompt_template_name": "system_default",
        "group_ids": "3,5",
        "max_steps": 15,
        "is_main_agent": True,
        "provide_run_summary": False,
        "enabled": True,
    }
    assert create_agent.call_args.kwargs["tenant_id"] == "tenant-a"
    assert create_agent.call_args.kwargs["user_id"] == "user-a"


def test_create_agent_draft_reuses_deterministic_name_suffixes(mocker):
    existing_agents = [{"agent_id": 1, "name": "research_assistant"}]
    _mock_create_dependencies(mocker, existing_agents=existing_agents)
    mocker.patch(
        "services.agent_service._check_agent_name_duplicate",
        return_value=True,
    )
    mocker.patch(
        "services.agent_service._check_agent_display_name_duplicate",
        return_value=True,
    )
    generate_name = mocker.patch(
        "services.agent_service._generate_unique_agent_name_with_suffix",
        return_value="research_assistant_1",
    )
    generate_display_name = mocker.patch(
        "services.agent_service._generate_unique_display_name_with_suffix",
        return_value="Research Assistant_1",
    )
    create_agent = mocker.patch(
        "services.nl2agent_service.create_agent",
        return_value={"agent_id": 12},
    )

    save_agent_draft_fields_impl(
        None,
        _basic_draft_fields(),
        "tenant-a",
        "user-a",
    )

    values = create_agent.call_args.kwargs["agent_info"]
    assert values["name"] == "research_assistant_1"
    assert values["display_name"] == "Research Assistant_1"
    generate_name.assert_called_once()
    generate_display_name.assert_called_once()


def test_update_agent_draft_changes_only_explicit_fields_and_allows_empty_list(
    mocker,
):
    mocker.patch(
        "services.nl2agent_service.query_agent_records_for_nl2agent",
        return_value=[
            {
                "agent_id": 22,
                "tenant_id": "tenant-a",
                "version_no": 0,
                "delete_flag": "N",
                "created_by": "user-a",
            }
        ],
    )
    mocker.patch(
        "services.nl2agent_service.get_user_role_by_tenant",
        return_value="MEMBER",
    )
    update_fields = mocker.patch(
        "services.nl2agent_service.update_agent_draft_fields",
        return_value=1,
    )

    result = save_agent_draft_fields_impl(
        agent_id=22,
        fields=AgentDraftFields(
            duty_prompt="Updated duty",
            example_questions=[],
        ),
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert result["created"] is False
    assert result["updated_fields"] == ["duty_prompt", "example_questions"]
    update_fields.assert_called_once_with(
        agent_id=22,
        tenant_id="tenant-a",
        fields={"duty_prompt": "Updated duty", "example_questions": []},
    )


@pytest.mark.parametrize(
    ("records", "role", "expected_code"),
    [
        ([], "MEMBER", "agent_not_found"),
        (
            [
                {
                    "agent_id": 22,
                    "tenant_id": "tenant-a",
                    "version_no": 1,
                    "delete_flag": "N",
                }
            ],
            "MEMBER",
            "agent_not_draft",
        ),
        (
            [
                {
                    "agent_id": 22,
                    "tenant_id": "tenant-a",
                    "version_no": 0,
                    "delete_flag": "Y",
                }
            ],
            "MEMBER",
            "agent_deleted",
        ),
        (
            [
                {
                    "agent_id": 22,
                    "tenant_id": "tenant-a",
                    "version_no": 0,
                    "delete_flag": "N",
                    "created_by": "another-user",
                    "ingroup_permission": "READ_ONLY",
                }
            ],
            "MEMBER",
            "agent_read_only",
        ),
    ],
)
def test_update_agent_draft_rejects_invalid_identity_or_permission(
    mocker,
    records,
    role,
    expected_code,
):
    mocker.patch(
        "services.nl2agent_service.query_agent_records_for_nl2agent",
        return_value=records,
    )
    mocker.patch(
        "services.nl2agent_service.get_user_role_by_tenant",
        return_value=role,
    )
    update_fields = mocker.patch(
        "services.nl2agent_service.update_agent_draft_fields"
    )

    with pytest.raises(Nl2AgentDraftSaveError) as exc_info:
        save_agent_draft_fields_impl(
            22,
            AgentDraftFields(description="Updated"),
            "tenant-a",
            "user-a",
        )

    assert exc_info.value.code == expected_code
    update_fields.assert_not_called()


def test_create_agent_draft_requires_valid_default_model_and_basic_fields(mocker):
    mocker.patch(
        "services.nl2agent_service.tenant_config_manager.get_model_config",
        return_value={},
    )

    with pytest.raises(Nl2AgentDraftSaveError) as exc_info:
        save_agent_draft_fields_impl(
            None,
            _basic_draft_fields(),
            "tenant-a",
            "user-a",
        )
    assert exc_info.value.code == "default_model_missing"

    mocker.patch(
        "services.nl2agent_service.tenant_config_manager.get_model_config",
        return_value={
            "model_id": 17,
            "model_type": "llm",
            "connect_status": "not_detected",
        },
    )
    with pytest.raises(Nl2AgentDraftSaveError) as exc_info:
        save_agent_draft_fields_impl(
            None,
            _basic_draft_fields(),
            "tenant-a",
            "user-a",
        )
    assert exc_info.value.code == "default_model_missing"

    with pytest.raises(Nl2AgentDraftSaveError) as exc_info:
        save_agent_draft_fields_impl(
            None,
            AgentDraftFields(name="only_a_name"),
            "tenant-a",
            "user-a",
        )
    assert exc_info.value.code == "basic_fields_required"


@pytest.mark.parametrize("operation", ["create", "update"])
def test_agent_draft_database_failures_are_stable_and_retryable(mocker, operation):
    if operation == "create":
        _mock_create_dependencies(mocker)
        mocker.patch(
            "services.agent_service._check_agent_name_duplicate",
            return_value=False,
        )
        mocker.patch(
            "services.agent_service._check_agent_display_name_duplicate",
            return_value=False,
        )
        mocker.patch(
            "services.nl2agent_service.create_agent",
            side_effect=RuntimeError("private database details"),
        )
        agent_id = None
        fields = _basic_draft_fields()
    else:
        mocker.patch(
            "services.nl2agent_service.query_agent_records_for_nl2agent",
            return_value=[
                {
                    "agent_id": 22,
                    "tenant_id": "tenant-a",
                    "version_no": 0,
                    "delete_flag": "N",
                    "created_by": "user-a",
                }
            ],
        )
        mocker.patch(
            "services.nl2agent_service.get_user_role_by_tenant",
            return_value="MEMBER",
        )
        mocker.patch(
            "services.nl2agent_service.update_agent_draft_fields",
            side_effect=RuntimeError("private database details"),
        )
        agent_id = 22
        fields = AgentDraftFields(description="Updated")

    with pytest.raises(Nl2AgentDraftSaveError) as exc_info:
        save_agent_draft_fields_impl(
            agent_id,
            fields,
            "tenant-a",
            "user-a",
        )

    assert exc_info.value.code == "draft_save_failed"
    assert exc_info.value.retryable is True


def test_agent_draft_update_rejects_unexpected_row_count(mocker):
    mocker.patch(
        "services.nl2agent_service.query_agent_records_for_nl2agent",
        return_value=[
            {
                "agent_id": 22,
                "tenant_id": "tenant-a",
                "version_no": 0,
                "delete_flag": "N",
                "created_by": "user-a",
            }
        ],
    )
    mocker.patch(
        "services.nl2agent_service.get_user_role_by_tenant",
        return_value="MEMBER",
    )
    mocker.patch(
        "services.nl2agent_service.update_agent_draft_fields",
        return_value=0,
    )

    with pytest.raises(Nl2AgentDraftSaveError) as exc_info:
        save_agent_draft_fields_impl(
            22,
            AgentDraftFields(description="Updated"),
            "tenant-a",
            "user-a",
        )

    assert exc_info.value.code == "draft_save_failed"
    assert exc_info.value.retryable is True


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"description": None},
        {"unexpected": "field"},
    ],
)
def test_agent_draft_fields_reject_empty_null_and_extra_patches(fields):
    with pytest.raises(ValidationError):
        AgentDraftFields.model_validate(fields)


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
                "inputs": '{"city":"string"}',
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
    assert result[0].inputs == {"city": "string"}
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


def test_search_skips_unsearchable_tools_and_sanitizes_malformed_inputs(mocker):
    mocker.patch(
        "services.nl2agent_service.query_all_tools",
        return_value=[
            {
                "tool_id": 1,
                "name": "",
                "description": "",
                "source": "mcp",
                "is_available": True,
            },
            {
                "tool_id": 2,
                "name": "weather_lookup",
                "description": "  Current\n weather  ",
                "source": "mcp",
                "usage": "weather-server",
                "labels": "weather",
                "inputs": "not a schema",
                "is_available": True,
            },
            {
                "tool_id": 3,
                "name": "weather_alerts",
                "description": "Weather alerts",
                "source": "mcp",
                "usage": "weather-server",
                "labels": ["weather", None],
                "inputs": '["not", "an", "object"]',
                "is_available": True,
            },
            {
                "tool_id": 4,
                "name": "weather_options",
                "description": "Weather query options",
                "source": "mcp",
                "usage": "weather-server",
                "labels": [],
                "inputs": {"conditions": (" rainy ", " sunny ")},
                "is_available": True,
            },
        ],
    )
    mocker.patch("services.nl2agent_service.fuzz.WRatio", return_value=90)
    mocker.patch("services.nl2agent_service.fuzz.token_set_ratio", return_value=90)

    result = search_installed_mcp_tools_by_query(
        "tenant-a",
        "weather",
        limit=3,
    )

    assert [item.tool_id for item in result] == [2, 3, 4]
    assert result[0].description == "Current weather"
    assert result[0].labels == []
    assert result[0].inputs == {}
    assert result[1].labels == ["weather"]
    assert result[1].inputs == {}
    assert result[2].inputs == {"conditions": ["rainy", "sunny"]}
    assert search_installed_mcp_tools_by_query(
        "tenant-a",
        None,
        limit=-1,
    ) == []


@pytest.mark.asyncio
async def test_build_run_info_is_ephemeral(mocker):
    default_model = {
        "model_factory": "openai",
        "model_name": "gpt-4o",
        "context_window_tokens": 32768,
    }
    capacity_snapshot = {"capacity_fingerprint": "capacity-fingerprint"}
    resolved_capacity_snapshot = MagicMock(context_window_tokens=32768)
    safe_input_budget_snapshot = {
        "soft_input_budget_tokens": 24000,
        "hard_input_budget_tokens": 30000,
    }
    join_query = mocker.patch(
        "services.nl2agent_service.join_minio_file_description_to_query",
        new_callable=AsyncMock,
        return_value="final query",
    )
    mocker.patch(
        "services.nl2agent_service.create_model_config_list",
        new_callable=AsyncMock,
        return_value=[],
    )
    get_model_config = mocker.patch(
        "services.nl2agent_service.tenant_config_manager.get_model_config",
        return_value=default_model,
    )
    resolve_input_budget = mocker.patch(
        "services.nl2agent_service._resolve_input_budget",
        return_value=(32768, capacity_snapshot, resolved_capacity_snapshot),
    )
    resolve_safe_input_budget = mocker.patch(
        "services.nl2agent_service._resolve_safe_input_budget",
        return_value=safe_input_budget_snapshot,
    )
    mocker.patch(
        "services.nl2agent_service.LOCAL_MCP_SERVER",
        "http://local-mcp:5011",
    )
    request = NL2AgentRunRequest(
        query='{"type":"nl2agent_tool_selection","tools":[]}',
        history=[
            HistoryItem(
                role="user",
                content="Build an agent that summarizes weather risks.",
            ),
            HistoryItem(
                role="assistant",
                content="I found matching weather tools.",
            ),
        ],
    )

    run_info = await build_nl2agent_run_info(
        request,
        "tenant-a",
        "en",
        "Bearer tenant-token",
    )

    assert run_info.query == "final query"
    assert run_info.agent_config.name == "__nl2agent_runtime__"
    assert run_info.agent_config.context_manager_config.token_threshold == 24000
    assert (
        run_info.agent_config.context_manager_config.hard_input_budget_tokens
        == 30000
    )
    assert run_info.agent_config.capacity_snapshot == capacity_snapshot
    assert (
        run_info.agent_config.safe_input_budget_snapshot
        == safe_input_budget_snapshot
    )
    assert run_info.capacity_snapshot == capacity_snapshot
    assert run_info.safe_input_budget_snapshot == safe_input_budget_snapshot
    assert run_info.history[0].content == (
        "Build an agent that summarizes weather risks."
    )
    assert len(run_info.context_input.items) == 1
    history_item = run_info.context_input.items[0]
    assert history_item.type.value == "conversation_turn"
    assert history_item.content == {
        "user_message": "Build an agent that summarizes weather risks.",
        "assistant_final_answer": "I found matching weather tools.",
        "attachments": [],
        "user_message_id": -1,
        "assistant_message_id": -2,
    }
    assert history_item.metadata == {"layout_order": 0}
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
    assert run_info.observer.enable_nl2a_wrapper is True
    join_query.assert_awaited_once_with(
        minio_files=None,
        query='{"type":"nl2agent_tool_selection","tools":[]}',
        history=request.history,
    )
    get_model_config.assert_called_once_with(
        key="LLM_ID",
        tenant_id="tenant-a",
    )
    resolve_input_budget.assert_called_once_with(default_model)
    resolve_safe_input_budget.assert_called_once_with(
        capacity_snapshot=resolved_capacity_snapshot,
        tenant_id="tenant-a",
        agent_requested_output_tokens=None,
        request_requested_output_tokens=None,
    )


@pytest.mark.asyncio
async def test_build_run_info_falls_back_without_capacity_or_authorization(mocker):
    mocker.patch(
        "services.nl2agent_service.join_minio_file_description_to_query",
        new_callable=AsyncMock,
        return_value="Build a writing assistant",
    )
    model_configs = []
    mocker.patch(
        "services.nl2agent_service.create_model_config_list",
        new_callable=AsyncMock,
        return_value=model_configs,
    )
    mocker.patch(
        "services.nl2agent_service.tenant_config_manager.get_model_config",
        return_value={"model_name": "tenant-default"},
    )
    capacity_snapshot = {"capacity_fingerprint": "legacy-capacity"}
    mocker.patch(
        "services.nl2agent_service._resolve_input_budget",
        return_value=(8192, capacity_snapshot, None),
    )
    mocker.patch(
        "services.nl2agent_service._resolve_safe_input_budget",
        return_value=None,
    )
    mocker.patch(
        "services.nl2agent_service.LOCAL_MCP_SERVER",
        "http://local-mcp:5011/base/",
    )

    run_info = await build_nl2agent_run_info(
        NL2AgentRunRequest(query="Build a writing assistant"),
        tenant_id="tenant-a",
        language="en",
        authorization=None,
    )

    context_config = run_info.agent_config.context_manager_config
    assert context_config.token_threshold == 8192
    assert context_config.context_window_tokens == 8192
    assert context_config.soft_input_budget_tokens == 0
    assert context_config.hard_input_budget_tokens == 0
    assert run_info.model_config_list == model_configs
    assert run_info.history == []
    assert not run_info.context_input.items
    assert run_info.mcp_host == [
        {
            "url": "http://local-mcp:5011/base/sse",
            "transport": "sse",
        }
    ]


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
            '"content": "{\\"status\\": \\"success\\", '
            '\\"recommendation_count\\": 0, \\"recommendations\\": []}"}\n\n'
        ),
    ]
    run_info.stop_event.set.assert_called_once_with()


@pytest.mark.asyncio
async def test_create_stream_hides_runtime_errors_and_stops_run(mocker):
    run_info = MagicMock()
    run_info.stop_event = MagicMock()
    mocker.patch(
        "services.nl2agent_service.build_nl2agent_run_info",
        new_callable=AsyncMock,
        return_value=run_info,
    )

    async def failing_agent_run(_run_info):
        if False:
            yield "unreachable"
        raise RuntimeError("private provider credentials")

    mocker.patch(
        "services.nl2agent_service.agent_run",
        side_effect=failing_agent_run,
    )

    stream = await create_nl2agent_stream(
        NL2AgentRunRequest(query="Build an assistant"),
        "tenant-a",
        "en",
        "Bearer tenant-token",
    )
    chunks = [chunk async for chunk in stream]

    assert len(chunks) == 1
    payload = json.loads(chunks[0].removeprefix("data: ").strip())
    assert payload == {
        "type": "error",
        "content": "NL2Agent execution failed.",
    }
    assert "credentials" not in chunks[0]
    assert "tenant-token" not in chunks[0]
    run_info.stop_event.set.assert_called_once_with()


@pytest.mark.asyncio
async def test_create_stream_propagates_cancellation_and_stops_run(mocker):
    run_info = MagicMock()
    run_info.stop_event = MagicMock()
    mocker.patch(
        "services.nl2agent_service.build_nl2agent_run_info",
        new_callable=AsyncMock,
        return_value=run_info,
    )

    async def cancelled_agent_run(_run_info):
        if False:
            yield "unreachable"
        raise asyncio.CancelledError

    mocker.patch(
        "services.nl2agent_service.agent_run",
        side_effect=cancelled_agent_run,
    )

    stream = await create_nl2agent_stream(
        NL2AgentRunRequest(query="Build an assistant"),
        "tenant-a",
        "en",
        None,
    )
    with pytest.raises(asyncio.CancelledError):
        await anext(stream)

    run_info.stop_event.set.assert_called_once_with()
