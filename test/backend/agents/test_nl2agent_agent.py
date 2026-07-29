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
        "format_rule",
        "retry_rule",
        "selection_rule",
        "few_shot_rule",
    ),
    [
        (
            "zh",
            "## 角色",
            "可执行动作使用",
            "翻译为英文并重试一次",
            "结合此前对话",
            "选择了工具时生成 3 到 5",
        ),
        (
            "en",
            "## Role",
            "Executable actions use",
            "once in English",
            "Use the preceding conversation",
            "When tools are selected",
        ),
    ],
)
def test_build_nl2agent_system_prompt_is_runtime_specific(
    language,
    expected,
    format_rule,
    retry_rule,
    selection_rule,
    few_shot_rule,
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
    assert "Think:" in prompt or "思考：" in prompt
    assert "Code:" in prompt or "代码：" in prompt
    assert format_rule in prompt
    assert retry_rule in prompt
    assert selection_rule in prompt
    assert few_shot_rule in prompt
    assert "weather_forecast" in prompt
    assert "<code>" in prompt
    assert "</code>" in prompt
    assert "<nl2a>" not in prompt
    assert "</nl2a>" not in prompt
    assert "final_answer(" not in prompt
    assert '"subtype": "local_mcp_recommendation"' in prompt
    assert '"subtype": "agent_draft"' in prompt
    assert 'result = runtime_search(keywords=[' in prompt
    assert "wrapped = runtime_wrapper(payload={" in prompt
    assert "print(result)" in prompt
    assert "few_shots_prompt" not in prompt


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
    assert config.tools[1].inputs == '{"payload": "Nl2aWrapperPayload"}'
    assert all(tool.metadata is None for tool in config.tools)
    assert "持久化由产品流程完成" in config.instructions
