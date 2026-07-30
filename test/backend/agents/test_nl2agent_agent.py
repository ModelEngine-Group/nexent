import ast
import json
import re

import pytest
from jinja2 import UndefinedError
from pydantic import ValidationError

from agents.nl2agent_agent import (
    build_nl2agent_system_prompt,
    create_nl2agent_agent_config,
)
from tool_collection.mcp.local_mcp_service import local_mcp_service
from tool_collection.mcp.nl2agent_mcp_tools import (
    GeneratedAgentDraft,
    InstalledMcpToolRecommendation,
    NL2A_WRAPPER_NAME,
    Nl2aAgentDraftInput,
    Nl2aFewShotToolCall,
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    build_nl2a_wrapper,
)


def _few_shot_examples(tool_name="weather_forecast"):
    return [
        {
            "user_input": question,
            "steps": [
                {
                    "reasoning": f"Look up the forecast for {city}.",
                    "tool_calls": [
                        {
                            "name": tool_name,
                            "arguments": {"city": city},
                        }
                    ],
                    "observation": f"{city} will be dry and mild.",
                }
            ],
            "final_reasoning": "The forecast is sufficient to answer.",
            "final_answer": f"{city} will be dry and mild.",
        }
        for question, city in [
            ("Will it rain in Paris?", "Paris"),
            ("What is the weather in Rome?", "Rome"),
        ]
    ]


def _agent_draft_input(**overrides):
    payload = {
        "subtype": "agent_draft",
        "language": "en",
        "name": "weather_assistant",
        "display_name": "WeatherAssistant",
        "description": "You can get weather guidance.",
        "duty_prompt": "Answer weather questions.",
        "constraint_prompt": "1. Use the selected weather tool.",
        "greeting_message": "Hello, I can help with weather.",
        "example_questions": [
            "Will it rain in Paris?",
            "What is the weather in Rome?",
            "Is it suitable for hiking?",
        ],
        "selected_tool_names": ["weather_forecast"],
        "few_shot_examples": _few_shot_examples(),
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    (
        "language",
        "expected",
        "json_rule",
        "retry_rule",
        "selection_rule",
        "few_shot_rule",
        "thought_label",
    ),
    [
        (
            "zh",
            "### 核心职责",
            "MCP 工具返回 JSON 文本",
            "中文关键词搜索成功但没有候选结果时",
            "只有处理当前",
            "选择工具时生成恰好 2",
            "思考：",
        ),
        (
            "en",
            "### Core Responsibilities",
            "MCP tool returns JSON text",
            "successful Chinese-keyword search returns no candidates",
            "only while processing the current",
            "selected tool set produces exactly 2",
            "Think:",
        ),
    ],
)
def test_build_nl2agent_system_prompt_is_runtime_specific(
    language,
    expected,
    json_rule,
    retry_rule,
    selection_rule,
    few_shot_rule,
    thought_label,
):
    prompt = build_nl2agent_system_prompt(
        language,
        tool_name="runtime_search",
        wrapper_name="runtime_wrapper",
        max_results=3,
    )

    assert expected in prompt
    assert "runtime_search" in prompt
    assert "runtime_wrapper" in prompt
    assert "3" in prompt
    assert "keywords" in prompt
    assert "nl2agent_tool_selection" in prompt
    assert "few_shot_examples" in prompt
    assert "greeting_message" in prompt
    assert "example_questions" in prompt
    assert thought_label in prompt
    assert json_rule in prompt
    assert retry_rule in prompt
    assert selection_rule in prompt
    assert few_shot_rule in prompt
    assert "_assistant" in prompt
    assert "30" in prompt
    assert "exactly 2" in prompt or "恰好 2" in prompt
    assert "second person" in prompt or "第二人称" in prompt
    assert "Observation" in prompt
    assert "final_answer" in prompt
    assert "<code>" in prompt
    assert "</code>" in prompt
    assert "<nl2a>" not in prompt
    assert "</nl2a>" not in prompt
    assert "final_answer(" not in prompt
    assert 'subtype="local_mcp_recommendation"' in prompt
    assert 'subtype="agent_draft"' in prompt
    assert 'result = json.loads(runtime_search(keywords=[' in prompt
    assert "wrapped = runtime_wrapper(" in prompt
    assert "search_result=result" in prompt
    assert "import json" in prompt
    assert "few_shots_prompt" not in prompt
    code_blocks = re.findall(r"<code>\n(.*?)\n</code>", prompt, re.DOTALL)
    assert len(code_blocks) == 3
    for code_block in code_blocks:
        ast.parse(code_block)
    assert code_blocks[-1].count('{"user_input":') == 2
    assert "```" not in prompt


def test_build_nl2agent_system_prompt_falls_back_to_chinese():
    assert build_nl2agent_system_prompt("fr") == build_nl2agent_system_prompt("zh")


def test_build_nl2agent_system_prompt_rejects_unknown_template_variables(mocker):
    prompt_loader = mocker.patch(
        "agents.nl2agent_agent.get_prompt_template",
        return_value={"system_prompt": "{{ missing_value }}"},
    )

    with pytest.raises(UndefinedError, match="missing_value"):
        build_nl2agent_system_prompt("en")

    prompt_loader.assert_called_once_with("nl2agent", "en")


def test_nl2agent_models_preserve_tool_inputs_and_define_agent_draft():
    recommendation = InstalledMcpToolRecommendation(
        tool_id=10,
        name="weather_forecast",
        origin_name="weather",
        description="Get weather forecasts",
        usage="weather-server",
        labels=["weather"],
        inputs={"city": "string"},
        score=0.9,
    )
    draft = GeneratedAgentDraft(
        name="weather_assistant",
        display_name="Weather Assistant",
        description="Weather help",
        duty_prompt="Answer weather questions.",
        constraint_prompt="Use only selected tools.",
        greeting_message="Hello! I can help with weather questions.",
        example_questions=[
            "Will it rain tomorrow?",
            "What should I wear today?",
            "Is it a good day for hiking?",
        ],
    )

    assert recommendation.inputs == {"city": "string"}
    assert draft.model_dump() == {
        "subtype": "agent_draft",
        "name": "weather_assistant",
        "display_name": "Weather Assistant",
        "description": "Weather help",
        "duty_prompt": "Answer weather questions.",
        "constraint_prompt": "Use only selected tools.",
        "few_shots_prompt": None,
        "greeting_message": "Hello! I can help with weather questions.",
        "example_questions": [
            "Will it rain tomorrow?",
            "What should I wear today?",
            "Is it a good day for hiking?",
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["zh", "en"])
async def test_create_nl2agent_agent_config_has_only_runtime_tools(language):
    config = create_nl2agent_agent_config(language)
    registered_tools = await local_mcp_service.get_tools()

    assert config.name == "__nl2agent_runtime__"
    assert config.model_name == "main_model"
    assert config.max_steps == 5
    assert config.enable_planning is False
    assert [tool.name for tool in config.tools] == [
        SEARCH_INSTALLED_MCP_TOOLS_NAME,
        NL2A_WRAPPER_NAME,
    ]
    assert [tool.description for tool in config.tools] == [
        registered_tools[SEARCH_INSTALLED_MCP_TOOLS_NAME].description,
        registered_tools[NL2A_WRAPPER_NAME].description,
    ]
    assert all(tool.source == "mcp" for tool in config.tools)
    assert all(tool.usage == "outer-apis" for tool in config.tools)
    assert config.tools[0].inputs == '{"keywords": "list[str]"}'
    wrapper_inputs = json.loads(config.tools[1].inputs)
    assert wrapper_inputs["subtype"] == "str"
    assert wrapper_inputs["search_result"] == "dict | None"
    assert wrapper_inputs["language"] == "str | None"
    assert (
        wrapper_inputs["few_shot_examples"]
        == "list[dict] with exactly 2 items | None"
    )
    assert all(tool.metadata is None for tool in config.tools)
    expected_persistence_rule = (
        "Agent persistence is handled by the product flow"
        if language == "en"
        else "持久化由产品流程完成"
    )
    assert expected_persistence_rule in config.instructions


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        ("weather-tool", {"city": "Paris"}, "tool call name"),
        ("weather_forecast", {"city-name": "Paris"}, "tool argument names"),
        ("weather_forecast", {"class": "Paris"}, "tool argument names"),
    ],
)
def test_few_shot_tool_calls_require_executable_python_names(
    name,
    arguments,
    message,
):
    with pytest.raises(ValidationError, match=message):
        Nl2aFewShotToolCall(name=name, arguments=arguments)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"language": "zh", "display_name": "WeatherAssistant"},
            "Chinese display_name must end with",
        ),
        (
            {"selected_tool_names": ["weather_forecast", "weather_forecast"]},
            "selected_tool_names must be unique",
        ),
        (
            {"selected_tool_names": ["weather-tool"]},
            "selected tool names must be valid Python identifiers",
        ),
        (
            {"few_shot_examples": None},
            "few_shot_examples are required",
        ),
        (
            {"constraint_prompt": ""},
            "constraint_prompt is required",
        ),
        (
            {"selected_tool_names": [], "constraint_prompt": ""},
            "few_shot_examples require selected tools",
        ),
        (
            {
                "selected_tool_names": [],
                "constraint_prompt": "Must use a tool.",
                "few_shot_examples": None,
            },
            "constraint_prompt must be empty",
        ),
    ],
)
def test_agent_draft_rejects_invalid_tool_binding_contract(overrides, message):
    with pytest.raises(ValidationError, match=message):
        Nl2aAgentDraftInput(**_agent_draft_input(**overrides))


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            {"subtype": "local_mcp_recommendation"},
            "requires search_result and selected_tool_ids",
        ),
        (
            {
                "subtype": "local_mcp_recommendation",
                "search_result": {
                    "subtype": "local_mcp_recommendation",
                    "status": "error",
                    "code": "tool_search_failed",
                    "retryable": True,
                },
                "selected_tool_ids": [7],
            },
            "must be empty for a search error",
        ),
        (
            {
                "subtype": "local_mcp_recommendation",
                "search_result": {"status": "pending"},
                "selected_tool_ids": [],
            },
            "unsupported status",
        ),
        (
            {"subtype": "agent_draft"},
            "agent_draft requires parameters",
        ),
        (
            {"subtype": "unsupported"},
            "unsupported nl2a subtype",
        ),
    ],
)
def test_wrapper_rejects_invalid_workflow_contracts(arguments, message):
    with pytest.raises(ValueError, match=message):
        build_nl2a_wrapper(**arguments)


def test_wrapper_renders_english_multi_tool_steps_as_executable_few_shots():
    examples = _few_shot_examples()
    examples[0]["steps"][0]["tool_calls"].append(
        {
            "name": "weather_alerts",
            "arguments": {"city": "Paris", "severe_only": True},
        }
    )
    wrapped = build_nl2a_wrapper(
        **_agent_draft_input(
            selected_tool_names=["weather_forecast", "weather_alerts"],
            few_shot_examples=examples,
        )
    )

    serialized = wrapped.split("<nl2a>\n", 1)[1].split("\n</nl2a>", 1)[0]
    payload = json.loads(serialized)
    few_shots = payload["few_shots_prompt"]

    assert 'Task 1: "Will it rain in Paris?"' in few_shots
    assert "result_1_1 = weather_forecast(city='Paris')" in few_shots
    assert (
        "result_1_2 = weather_alerts(city='Paris', severe_only=True)"
        in few_shots
    )
    assert "# System returns Observation: Paris will be dry and mild." in few_shots
    assert few_shots.count("<code>") == 2
