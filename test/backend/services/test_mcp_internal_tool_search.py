import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from mcp.types import Tool
from pydantic import ValidationError

import services.nl2agent_service as nl2agent_service
import services.tool_configuration_service as tool_configuration_service
import tool_collection.mcp.nl2agent_mcp_tools as nl2agent_mcp_tools_module
from services.tool_configuration_service import get_tool_from_remote_mcp_server
from tool_collection.mcp.local_mcp_service import (
    LOCAL_MCP_TOOL_NAME_OVERRIDES,
    local_mcp_service,
)
from tool_collection.mcp.nl2agent_mcp_tools import (
    NL2AGENT_AGENT_ID_HEADER,
    NL2AGENT_MCP_TOOL_META,
    NL2A_WRAPPER_DESCRIPTION,
    NL2A_WRAPPER_NAME,
    Nl2aAgentDraftInput,
    Nl2aLocalMcpRecommendationInput,
    RecommendResourcesOutput,
    RECOMMEND_RESOURCES_DESCRIPTION,
    RECOMMEND_RESOURCES_NAME,
    RequirementClarificationQuestion,
    SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION,
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    SEARCH_INSTALLED_RESOURCES_DESCRIPTION,
    SEARCH_INSTALLED_RESOURCES_NAME,
    SAVE_AGENT_DRAFT_FIELDS_DESCRIPTION,
    SAVE_AGENT_DRAFT_FIELDS_NAME,
    nl2a_wrapper,
    recommend_resources,
    save_agent_draft_fields,
    search_installed_mcp_tools,
    search_installed_resources,
)


def _unwrap_nl2a(result: str) -> dict:
    wrapper, marker = result.rsplit("</nl2a>", 1)
    assert marker.strip() == "NL2A payload generated."
    return json.loads(wrapper.split("<nl2a>", 1)[1])


@pytest.mark.asyncio
async def test_mcp_search_is_tenant_scoped_sorted_and_safe(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer tenant-token"}),
    )
    get_current_user_id = mocker.patch.object(
        nl2agent_mcp_tools_module,
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
                "inputs": '{"city":"string"}',
                "is_available": True,
                "params": {"token": "must-not-leak"},
            },
            {
                "tool_id": 7,
                "name": "primary_weather",
                "origin_name": "primary-weather",
                "description": """Primary weather forecast search
                    with hourly rain probability""",
                "source": "mcp",
                "usage": "weather-server-a",
                "labels": ["weather", "forecast"],
                "inputs": (
                    "{'city': {'type': 'string', 'description': "
                    "\"The city name,\\n translated to English when it isn't English.\"}, "
                    "'include_forecast': {'type': 'boolean', 'default': False}}"
                ),
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

    result = await search_installed_mcp_tools(
        [" Weather ", "forecast", "WEATHER"]
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
    assert set(result) == {
        "subtype",
        "status",
        "recommendation_count",
        "recommendations",
    }
    assert result["subtype"] == "local_mcp_recommendation"
    assert [item["tool_id"] for item in result["recommendations"]] == [7, 12]
    assert result["recommendations"][0] == {
        "tool_id": 7,
        "name": "primary_weather",
        "origin_name": "primary-weather",
        "description": (
            "Primary weather forecast search with hourly rain probability"
        ),
        "source": "mcp",
        "usage": "weather-server-a",
        "labels": ["weather", "forecast"],
        "inputs": {
            "city": {
                "type": "string",
                "description": (
                    "The city name, translated to English when it isn't English."
                ),
            },
            "include_forecast": {
                "type": "boolean",
                "default": False,
            },
        },
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
        "inputs",
        "score",
    }
    assert all(set(item) == safe_fields for item in result["recommendations"])
    assert "must-not-leak" not in json.dumps(result)


@pytest.mark.asyncio
async def test_mcp_search_returns_sanitized_contract_errors(mocker):
    for keywords in ([], ["   "]):
        invalid_result = await search_installed_mcp_tools(keywords)
        assert invalid_result == {
            "subtype": "local_mcp_recommendation",
            "status": "error",
            "code": "invalid_keywords",
            "retryable": True,
        }

    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer private-token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch.object(
        nl2agent_service,
        "search_installed_mcp_tools_by_query",
        side_effect=RuntimeError("private database details"),
    )

    result = await search_installed_mcp_tools(["private", "weather"])

    assert result == {
        "subtype": "local_mcp_recommendation",
        "status": "error",
        "code": "tool_search_failed",
        "retryable": True,
    }
    serialized_result = json.dumps(result)
    assert "private-token" not in serialized_result
    assert "private database details" not in serialized_result


@pytest.mark.asyncio
async def test_nl2a_wrapper_filters_real_search_results_and_wraps_errors():
    search_result = {
        "subtype": "local_mcp_recommendation",
        "status": "success",
        "recommendation_count": 2,
        "recommendations": [
            {
                "tool_id": tool_id,
                "name": name,
                "origin_name": None,
                "description": f"Tool {tool_id}",
                "source": "mcp",
                "usage": "weather-server",
                "labels": ["weather"],
                "inputs": {"city": "string"},
                "score": score,
            }
            for tool_id, name, score in [
                (7, "primary_weather", 0.95),
                (12, "secondary_weather", 0.75),
            ]
        ],
    }

    result = await nl2a_wrapper(
        subtype="local_mcp_recommendation",
        search_result=search_result,
        selected_tool_ids=[12],
    )

    assert _unwrap_nl2a(result) == {
        "subtype": "local_mcp_recommendation",
        "status": "success",
        "recommendation_count": 1,
        "recommendations": [search_result["recommendations"][1]],
    }

    with pytest.raises(ValueError, match="not present in search_result"):
        await nl2a_wrapper(
            subtype="local_mcp_recommendation",
            search_result=search_result,
            selected_tool_ids=[999],
        )
    with pytest.raises(ValidationError, match="selected_tool_ids must be unique"):
        Nl2aLocalMcpRecommendationInput(
            subtype="local_mcp_recommendation",
            search_result=search_result,
            selected_tool_ids=[7, 7],
        )

    error_result = await nl2a_wrapper(
        subtype="local_mcp_recommendation",
        search_result={
            "subtype": "local_mcp_recommendation",
            "status": "error",
            "code": "tool_search_failed",
            "retryable": True,
        },
        selected_tool_ids=[],
    )
    assert _unwrap_nl2a(error_result) == {
        "subtype": "local_mcp_recommendation",
        "status": "error",
        "code": "tool_search_failed",
        "retryable": True,
    }


@pytest.mark.asyncio
async def test_nl2a_wrapper_renders_structured_agent_few_shots():
    examples = [
        {
            "user_input": question,
            "steps": [
                {
                    "reasoning": f"Query weather for {city}.",
                    "tool_calls": [
                        {
                            "name": "weather_forecast",
                            "arguments": {"city": city},
                        }
                    ],
                    "observation": f"{city} has mild and dry weather.",
                }
            ],
            "final_reasoning": "The observation answers the question.",
            "final_answer": "The weather is mild and dry.",
        }
        for question, city in [
            ("上海明天会下雨吗？", "上海"),
            ("北京今天适合穿什么？", "北京"),
        ]
    ]
    payload = {
        "subtype": "agent_draft",
        "language": "zh",
        "name": "weather_assistant",
        "display_name": "天气助手",
        "description": "查询天气并提供出行建议。",
        "duty_prompt": "回答天气问题。",
        "constraint_prompt": "使用真实工具结果。",
        "greeting_message": "你好，我可以帮助查询天气。",
        "example_questions": [
            "上海明天会下雨吗？",
            "北京今天适合穿什么？",
            "杭州今天适合徒步吗？",
        ],
        "selected_tool_names": ["weather_forecast"],
        "few_shot_examples": examples,
    }

    result = _unwrap_nl2a(await nl2a_wrapper(**payload))

    assert result["subtype"] == "agent_draft"
    assert result["example_questions"] == [
        "上海明天会下雨吗？",
        "北京今天适合穿什么？",
        "杭州今天适合徒步吗？",
    ]
    assert result["few_shots_prompt"].count("<code>") == 2
    assert "任务1" in result["few_shots_prompt"]
    assert "result_1 = weather_forecast(city='上海')" in result["few_shots_prompt"]
    assert "# 系统返回 Observation: 上海 has mild and dry weather." in result["few_shots_prompt"]
    assert "The weather is mild and dry." in result["few_shots_prompt"]
    assert "selected_tool_names" not in result
    assert "few_shot_examples" not in result

    no_tool_payload = {
        "subtype": "agent_draft",
        "language": "en",
        "name": "writing_assistant",
        "display_name": "WritingAssistant",
        "description": "Helps improve writing.",
        "duty_prompt": "Improve user-provided text.",
        "constraint_prompt": "",
        "greeting_message": "Hello, I can help improve your writing.",
        "example_questions": [
            "Can you improve this paragraph?",
            "Can you make this more concise?",
            "Can you correct the grammar?",
        ],
        "selected_tool_names": [],
        "few_shot_examples": None,
    }
    no_tool_result = _unwrap_nl2a(await nl2a_wrapper(**no_tool_payload))
    assert no_tool_result["constraint_prompt"] == ""
    assert no_tool_result["few_shots_prompt"] is None


def test_agent_draft_wrapper_rejects_missing_or_unknown_few_shot_tools():
    common = {
        "subtype": "agent_draft",
        "language": "en",
        "name": "weather_assistant",
        "display_name": "WeatherAssistant",
        "description": "Weather help.",
        "duty_prompt": "Answer weather questions.",
        "constraint_prompt": "Use real observations.",
        "greeting_message": "Hello, I can help with weather.",
        "example_questions": ["Question one?", "Question two?", "Question three?"],
        "selected_tool_names": ["weather_forecast"],
    }
    with pytest.raises(ValidationError, match="few_shot_examples are required"):
        Nl2aAgentDraftInput(**common)

    invalid_examples = [
        {
            "user_input": f"Question {index}?",
            "steps": [
                {
                    "reasoning": "Use a tool.",
                    "tool_calls": [
                        {"name": "invented_tool", "arguments": {}}
                    ],
                    "observation": "A tool result.",
                }
            ],
            "final_reasoning": "Use the observation.",
            "final_answer": "A concrete answer.",
        }
        for index in range(2)
    ]
    with pytest.raises(ValidationError, match="must use selected tool names"):
        Nl2aAgentDraftInput(**common, few_shot_examples=invalid_examples)


@pytest.mark.parametrize("example_count", [1, 3])
def test_agent_draft_wrapper_requires_exactly_two_few_shot_examples(
    example_count,
):
    examples = [
        {
            "user_input": f"Question {index}?",
            "steps": [
                {
                    "reasoning": "Use the selected tool.",
                    "tool_calls": [
                        {"name": "weather_forecast", "arguments": {}}
                    ],
                    "observation": "A tool result.",
                }
            ],
            "final_reasoning": "Use the observation.",
            "final_answer": "A concrete answer.",
        }
        for index in range(example_count)
    ]

    with pytest.raises(ValidationError):
        Nl2aAgentDraftInput(
            subtype="agent_draft",
            language="en",
            name="weather_assistant",
            display_name="WeatherAssistant",
            description="Weather help.",
            duty_prompt="Answer weather questions.",
            constraint_prompt="Use real observations.",
            greeting_message="Hello, I can help with weather.",
            example_questions=["Question one?", "Question two?", "Question three?"],
            selected_tool_names=["weather_forecast"],
            few_shot_examples=examples,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "weather", "ending with _assistant"),
        ("display_name", "Weather Assistant", "one word ending with Assistant"),
    ],
)
def test_agent_draft_wrapper_enforces_ordinary_agent_name_rules(
    field,
    value,
    message,
):
    payload = {
        "subtype": "agent_draft",
        "language": "en",
        "name": "writing_assistant",
        "display_name": "WritingAssistant",
        "description": "You are a writing assistant.",
        "duty_prompt": "Improve user-provided text.",
        "constraint_prompt": "",
        "greeting_message": "Hello, I can help improve your writing.",
        "example_questions": ["Question one?", "Question two?", "Question three?"],
        "selected_tool_names": [],
        "few_shot_examples": None,
    }
    payload[field] = value

    with pytest.raises(ValidationError, match=message):
        Nl2aAgentDraftInput(**payload)


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
    resource_search_tool = mounted_tools[SEARCH_INSTALLED_RESOURCES_NAME]
    recommend_tool = mounted_tools[RECOMMEND_RESOURCES_NAME]
    wrapper_tool = mounted_tools[NL2A_WRAPPER_NAME]
    save_tool = mounted_tools[SAVE_AGENT_DRAFT_FIELDS_NAME]

    assert LOCAL_MCP_TOOL_NAME_OVERRIDES == {
        SEARCH_INSTALLED_MCP_TOOLS_NAME: SEARCH_INSTALLED_MCP_TOOLS_NAME,
        SEARCH_INSTALLED_RESOURCES_NAME: SEARCH_INSTALLED_RESOURCES_NAME,
        RECOMMEND_RESOURCES_NAME: RECOMMEND_RESOURCES_NAME,
        SAVE_AGENT_DRAFT_FIELDS_NAME: SAVE_AGENT_DRAFT_FIELDS_NAME,
        NL2A_WRAPPER_NAME: NL2A_WRAPPER_NAME,
    }
    assert f"local_{SEARCH_INSTALLED_MCP_TOOLS_NAME}" not in mounted_tools
    assert tool.name == SEARCH_INSTALLED_MCP_TOOLS_NAME
    assert set(tool.parameters["properties"]) == {"keywords"}
    assert tool.parameters["properties"]["keywords"]["type"] == "array"
    assert tool.parameters["properties"]["keywords"]["items"]["type"] == "string"
    assert tool.parameters["required"] == ["keywords"]
    assert tool.meta == NL2AGENT_MCP_TOOL_META
    assert "print(result)" in tool.description
    assert tool.description == SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION
    assert resource_search_tool.description == SEARCH_INSTALLED_RESOURCES_DESCRIPTION
    assert set(resource_search_tool.parameters["properties"]) == {
        "requirements",
        "agent_id",
    }
    assert resource_search_tool.parameters["required"] == ["requirements"]
    assert recommend_tool.description == RECOMMEND_RESOURCES_DESCRIPTION
    assert set(recommend_tool.parameters["properties"]) == {
        "candidates",
        "recommended_refs",
        "agent_id",
    }
    assert recommend_tool.parameters["required"] == [
        "candidates",
        "recommended_refs",
    ]
    assert wrapper_tool.name == NL2A_WRAPPER_NAME
    assert wrapper_tool.description == NL2A_WRAPPER_DESCRIPTION
    assert wrapper_tool.meta == NL2AGENT_MCP_TOOL_META
    assert save_tool.description == SAVE_AGENT_DRAFT_FIELDS_DESCRIPTION
    assert save_tool.parameters["required"] == ["agent_id", "fields"]
    assert set(save_tool.parameters["properties"]) == {"agent_id", "fields"}
    assert wrapper_tool.parameters["required"] == ["subtype"]
    assert set(wrapper_tool.parameters["properties"]) == {
        "subtype",
        "agent_id",
        "resource_result",
        "questions",
        "search_result",
        "selected_tool_ids",
        "language",
        "name",
        "display_name",
        "description",
        "duty_prompt",
        "constraint_prompt",
        "greeting_message",
        "example_questions",
        "selected_tool_names",
        "few_shot_examples",
    }
    assert wrapper_tool.parameters["properties"]["subtype"]["enum"] == [
        "requirement_clarification",
        "installed_resource_binding",
        "local_mcp_recommendation",
        "agent_draft",
    ]
    few_shot_schema = next(
        option
        for option in wrapper_tool.parameters["properties"]["few_shot_examples"][
            "anyOf"
        ]
        if option.get("type") == "array"
    )
    assert few_shot_schema["minItems"] == 2
    assert few_shot_schema["maxItems"] == 2
    assert few_shot_schema["description"] == "Exactly two structured few-shot examples."
    assert wrapper_tool.meta["nexent_internal"] is True


@pytest.mark.asyncio
async def test_save_agent_draft_fields_emits_state_only_for_creation(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    save_impl = mocker.patch.object(
        nl2agent_service,
        "save_agent_draft_fields_impl",
        return_value={
            "status": "success",
            "agent_id": 1042,
            "created": True,
            "updated_fields": [
                "name",
                "display_name",
                "description",
                "business_description",
            ],
        },
    )
    fields = {
        "name": "research_assistant",
        "display_name": "Research Assistant",
        "description": "Researches a topic.",
        "business_description": "Research and summarize.",
    }

    created_result = await save_agent_draft_fields(None, fields)

    result_json, state_wrapper = created_result.split("\n", 1)
    assert json.loads(result_json) == {
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
    assert state_wrapper == (
        '<nl2a_state>{"event":"agent_draft_created","agent_id":1042}'
        "</nl2a_state>"
    )
    save_impl.assert_called_once()

    save_impl.return_value = {
        "status": "success",
        "agent_id": 1042,
        "created": False,
        "updated_fields": ["description"],
    }
    updated_result = await save_agent_draft_fields(
        1042,
        {"description": "Updated"},
    )
    assert "nl2a_state" not in updated_result
    assert json.loads(updated_result)["created"] is False


@pytest.mark.asyncio
async def test_save_agent_draft_fields_reuses_trusted_context_across_rounds(mocker):
    request = SimpleNamespace(headers={"Authorization": "Bearer token"})
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=request,
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )

    def save_impl(*, agent_id, fields, tenant_id, user_id):
        return {
            "status": "success",
            "agent_id": 1042,
            "created": agent_id is None,
            "updated_fields": list(fields.model_fields_set),
        }

    save = mocker.patch.object(
        nl2agent_service,
        "save_agent_draft_fields_impl",
        side_effect=save_impl,
    )
    first = await save_agent_draft_fields(
        None,
        {
            "name": "research_assistant",
            "display_name": "Research Assistant",
            "description": "Researches a topic.",
            "business_description": "Research and summarize.",
        },
    )

    request.headers[NL2AGENT_AGENT_ID_HEADER] = "1042"
    second = await save_agent_draft_fields(None, {"description": "Updated"})
    third = await save_agent_draft_fields(None, {"duty_prompt": "Verify sources"})

    assert [call.kwargs["agent_id"] for call in save.call_args_list] == [
        None,
        1042,
        1042,
    ]
    assert sum(result.count("<nl2a_state>") for result in (first, second, third)) == 1
    assert json.loads(second)["created"] is False
    assert json.loads(third)["created"] is False


@pytest.mark.asyncio
async def test_save_agent_draft_fields_rejects_context_mismatch_without_write(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(
            headers={
                "Authorization": "Bearer token",
                NL2AGENT_AGENT_ID_HEADER: "1042",
            }
        ),
    )
    save = mocker.patch.object(
        nl2agent_service,
        "save_agent_draft_fields_impl",
    )

    result = json.loads(
        await save_agent_draft_fields(1043, {"description": "Wrong draft"})
    )

    assert result == {
        "status": "error",
        "agent_id": 1043,
        "created": False,
        "updated_fields": [],
        "code": "agent_context_mismatch",
        "retryable": False,
    }
    save.assert_not_called()


@pytest.mark.asyncio
async def test_clarification_wrapper_fills_agent_id_from_trusted_context(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(
            headers={
                "Authorization": "Bearer token",
                NL2AGENT_AGENT_ID_HEADER: "42",
            }
        ),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    require_edit = mocker.patch(
        "services.agent_draft_permission_service.require_agent_draft_edit"
    )

    wrapped = await nl2a_wrapper(
        subtype="requirement_clarification",
        questions=[
            RequirementClarificationQuestion(
                question_id="scope",
                question_type="text",
                title="What should the Agent cover?",
                required=True,
                options=[],
                allow_other=False,
                other_input_expanded=False,
            )
        ],
    )

    assert _unwrap_nl2a(wrapped)["agent_id"] == 42
    require_edit.assert_called_once_with(
        agent_id=42,
        tenant_id="tenant-a",
        user_id="user-a",
    )


@pytest.mark.asyncio
async def test_resource_tools_reject_invalid_model_echoes_without_service_calls(
    mocker,
):
    search_impl = mocker.patch.object(
        nl2agent_service,
        "search_installed_resources_impl",
    )
    recommend_impl = mocker.patch.object(
        nl2agent_service,
        "recommend_installed_resources_impl",
    )

    search_result = await search_installed_resources([])
    recommend_result = await recommend_resources(
        candidates=[
            {
                "candidate_ref": "tool:7",
                "resource_type": "tool",
                "source": "LOCAL_TOOL",
                "name": "search",
                "requirement_ids": ["lookup"],
                "score": 0.9,
            }
        ],
        recommended_refs=["tool:99"],
    )

    assert search_result["code"] == "invalid_requirements"
    assert search_result["retryable"] is False
    assert recommend_result["code"] == "invalid_candidates"
    assert recommend_result["retryable"] is False
    search_impl.assert_not_called()
    recommend_impl.assert_not_called()


@pytest.mark.asyncio
async def test_resource_tools_return_tenant_scoped_results_and_stable_errors(
    mocker,
):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    get_user = mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    search_output = MagicMock()
    search_output.model_dump.return_value = {
        "status": "success",
        "candidates": [],
        "uncovered_requirement_ids": ["lookup"],
    }
    search_impl = mocker.patch.object(
        nl2agent_service,
        "search_installed_resources_impl",
        new=AsyncMock(return_value=search_output),
    )
    recommend_output = MagicMock()
    recommend_output.model_dump.return_value = {
        "status": "success",
        "resources": [],
    }
    recommend_impl = mocker.patch.object(
        nl2agent_service,
        "recommend_installed_resources_impl",
        new=AsyncMock(return_value=recommend_output),
    )
    requirements = [{"requirement_id": "lookup", "query": "web search"}]
    candidate = {
        "candidate_ref": "tool:7",
        "resource_type": "tool",
        "source": "LOCAL_TOOL",
        "name": "search",
        "requirement_ids": ["lookup"],
        "score": 0.9,
    }

    assert (await search_installed_resources(requirements))["status"] == "success"
    assert (await recommend_resources([candidate], ["tool:7"]))["status"] == "success"
    assert get_user.call_count == 2
    assert search_impl.await_args.kwargs["tenant_id"] == "tenant-a"
    assert recommend_impl.await_args.kwargs["user_id"] == "user-a"

    search_impl.side_effect = PermissionError("private auth details")
    assert (await search_installed_resources(requirements))["code"] == "unauthorized"
    search_impl.side_effect = RuntimeError("private search details")
    search_error = await search_installed_resources(requirements)
    assert search_error["code"] == "resource_search_failed"
    assert "private" not in json.dumps(search_error)

    recommend_impl.side_effect = nl2agent_service.Nl2AgentResourceError(
        "resource_not_visible"
    )
    assert (
        await recommend_resources([candidate], ["tool:7"])
    )["code"] == "resource_not_visible"
    recommend_impl.side_effect = PermissionError("private auth details")
    assert (
        await recommend_resources([candidate], ["tool:7"])
    )["code"] == "unauthorized"
    recommend_impl.side_effect = RuntimeError("private resolution details")
    resolution_error = await recommend_resources([candidate], ["tool:7"])
    assert resolution_error["code"] == "resource_resolution_failed"
    assert "private" not in json.dumps(resolution_error)


@pytest.mark.asyncio
async def test_installed_binding_wrapper_rechecks_agent_and_candidates(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    require_edit = mocker.patch(
        "services.agent_draft_permission_service.require_agent_draft_edit"
    )
    resource_result = {
        "status": "success",
        "resources": [
            {
                "candidate": {
                    "candidate_ref": "tool:7",
                    "resource_type": "tool",
                    "source": "LOCAL_TOOL",
                    "name": "search",
                    "requirement_ids": ["lookup"],
                    "score": 0.9,
                },
                "recommendation": "recommended",
                "form_kind": "TOOL_CONFIG",
                "config": [],
            }
        ],
    }
    verified = RecommendResourcesOutput.model_validate(resource_result)
    recommend_impl = mocker.patch.object(
        nl2agent_service,
        "recommend_installed_resources_impl",
        new=AsyncMock(return_value=verified),
    )

    wrapped = await nl2a_wrapper(
        subtype="installed_resource_binding",
        agent_id=42,
        resource_result=resource_result,
    )

    assert _unwrap_nl2a(wrapped)["resources"][0]["candidate"]["name"] == "search"
    require_edit.assert_called_once_with(
        agent_id=42,
        tenant_id="tenant-a",
        user_id="user-a",
    )
    assert recommend_impl.await_args.kwargs["recommended_refs"] == ["tool:7"]


@pytest.mark.asyncio
async def test_save_agent_draft_fields_returns_stable_non_sensitive_errors(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch.object(
        nl2agent_service,
        "save_agent_draft_fields_impl",
        side_effect=nl2agent_service.Nl2AgentDraftSaveError("agent_read_only"),
    )

    error_result = json.loads(
        await save_agent_draft_fields(1042, {"description": "Updated"})
    )
    assert error_result == {
        "status": "error",
        "agent_id": 1042,
        "created": False,
        "updated_fields": [],
        "code": "agent_read_only",
        "retryable": False,
    }
    assert "database" not in json.dumps(error_result).lower()

    invalid_result = json.loads(
        await save_agent_draft_fields(1042, {"description": None})
    )
    assert invalid_result["code"] == "invalid_agent_fields"
    assert invalid_result["retryable"] is False

    nl2agent_mcp_tools_module.get_current_user_id.side_effect = PermissionError(
        "private authorization details"
    )
    unauthorized_result = json.loads(
        await save_agent_draft_fields(1042, {"description": "Updated"})
    )
    assert unauthorized_result["code"] == "unauthorized"
    assert "private authorization details" not in json.dumps(unauthorized_result)

    nl2agent_mcp_tools_module.get_current_user_id.side_effect = RuntimeError(
        "private database details"
    )
    failed_result = json.loads(
        await save_agent_draft_fields(1042, {"description": "Updated"})
    )
    assert failed_result["code"] == "draft_save_failed"
    assert failed_result["retryable"] is True
    assert "private database details" not in json.dumps(failed_result)


def test_requirement_clarification_rejects_invalid_question_shapes():
    with pytest.raises(ValidationError, match="cannot have options"):
        RequirementClarificationQuestion(
            question_id="details",
            question_type="text",
            title="Add details",
            options=[{"option_id": "unexpected", "label": "Unexpected"}],
        )

    with pytest.raises(ValidationError, match="require options"):
        RequirementClarificationQuestion(
            question_id="output",
            question_type="single_choice",
            title="Choose an output",
        )


@pytest.mark.asyncio
async def test_requirement_clarification_wrapper_requires_questions():
    with pytest.raises(ValueError, match="requires questions"):
        await nl2a_wrapper(subtype="requirement_clarification")


@pytest.mark.asyncio
async def test_local_mcp_service_preserves_existing_demo_tool(capsys):
    registered_tools = await local_mcp_service.get_tools()

    result = await registered_tools["test_tool_name"].fn("sample", 2)

    assert result == "success"
    assert capsys.readouterr().out.splitlines() == [
        "tool is called successfully",
        "sample 2",
    ]


@pytest.mark.asyncio
async def test_mcp_search_empty_result_returns_business_payload(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer tenant-token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch.object(
        nl2agent_service,
        "search_installed_mcp_tools_by_query",
        return_value=[],
    )

    result = await search_installed_mcp_tools(["weather"])

    assert result == {
        "subtype": "local_mcp_recommendation",
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
            name=NL2A_WRAPPER_NAME,
            description="Internal wrapper",
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
