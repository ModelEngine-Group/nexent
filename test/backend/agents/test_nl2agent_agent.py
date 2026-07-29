import ast
import json
import re

import pytest

from agents.nl2agent_agent import (
    GeneratedAgentDraft,
    InstalledMcpToolRecommendation,
    build_nl2agent_system_prompt,
    create_nl2agent_agent_config,
)


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


def test_create_nl2agent_agent_config_has_only_runtime_tools():
    config = create_nl2agent_agent_config("zh")

    assert config.name == "__nl2agent_runtime__"
    assert config.model_name == "main_model"
    assert config.max_steps == 5
    assert config.enable_planning is False
    assert [tool.name for tool in config.tools] == [
        "search_installed_mcp_tools",
        "nl2a_wrapper",
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
    assert "持久化由产品流程完成" in config.instructions
