import pytest

from agents.nl2agent_agent import (
    GeneratedAgentDraft,
    GeneratedAgentDraftTool,
    InstalledMcpToolRecommendation,
    build_nl2agent_system_prompt,
    create_nl2agent_agent_config,
)


@pytest.mark.parametrize(
    (
        "language",
        "expected",
        "format_rule",
        "retry_rule",
        "unclear_example",
        "clear_example",
    ),
    [
        (
            "zh",
            "## 角色",
            "可执行代码必须使用",
            "英文关键词",
            "### 需求不明确",
            "### 需求明确",
        ),
        (
            "en",
            "## Role",
            "Executable code must use",
            "English keywords",
            "### Unclear Request",
            "### Clear Request",
        ),
    ],
)
def test_build_nl2agent_system_prompt_is_runtime_specific(
    language,
    expected,
    format_rule,
    retry_rule,
    unclear_example,
    clear_example,
):
    prompt = build_nl2agent_system_prompt(
        language,
        tool_name="runtime_search",
        max_results=3,
    )

    assert expected in prompt
    assert "runtime_search" in prompt
    assert "3" in prompt
    assert "keywords" in prompt
    assert "nl2agent_tool_selection" in prompt
    assert "few_shots_prompt" in prompt
    assert "### Examples" in prompt
    assert "**Example 1**" in prompt
    assert "User Input:" in prompt
    assert "Assistant:" in prompt
    assert "Thought:" in prompt
    assert "Code:" in prompt
    assert "Do not search again" in prompt or "不得再次搜索" in prompt
    assert "valid JSON" in prompt or "合法 JSON" in prompt
    assert format_rule in prompt
    assert retry_rule in prompt
    assert unclear_example in prompt
    assert clear_example in prompt
    assert "<code>" in prompt
    assert "</code>" in prompt
    assert "<nl2a>" in prompt
    assert "</nl2a>" in prompt
    assert 'final_answer("""<nl2a>' in prompt
    assert "recommendation_count" in prompt
    assert 'result = runtime_search(keywords=[' in prompt
    assert prompt.count("print(result)") >= 3


def test_nl2agent_models_preserve_tool_inputs_and_allow_empty_draft_tools():
    recommendation = InstalledMcpToolRecommendation(
        tool_id=10,
        name="weather_forecast",
        origin_name="weather",
        description="Get weather forecasts",
        usage="weather-server",
        labels=["weather"],
        inputs='{"city":"string"}',
        score=0.9,
    )
    draft_tool = GeneratedAgentDraftTool(
        **recommendation.model_dump(exclude={"score"}),
        few_shots_prompt=None,
    )
    draft = GeneratedAgentDraft(
        name="weather_assistant",
        display_name="Weather Assistant",
        description="Weather help",
        duty_prompt="Answer weather questions.",
        constraint_prompt="Use only selected tools.",
        tools=[],
    )

    assert recommendation.inputs == '{"city":"string"}'
    assert draft_tool.inputs == '{"city":"string"}'
    assert draft_tool.few_shots_prompt is None
    assert draft.tools == []


def test_create_nl2agent_agent_config_has_only_runtime_tool():
    config = create_nl2agent_agent_config("zh")

    assert config.name == "__nl2agent_runtime__"
    assert config.model_name == "main_model"
    assert config.max_steps == 5
    assert config.enable_planning is False
    assert len(config.tools) == 1
    assert config.tools[0].source == "mcp"
    assert config.tools[0].usage == "outer-apis"
    assert config.tools[0].inputs == '{"keywords": "list[str]"}'
    assert config.tools[0].metadata is None
    assert "不得创建" in config.instructions
