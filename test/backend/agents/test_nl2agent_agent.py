import pytest

from agents.nl2agent_agent import (
    build_nl2agent_system_prompt,
    create_nl2agent_agent_config,
)


@pytest.mark.parametrize(
    ("language", "expected", "format_rule", "unclear_example", "clear_example"),
    [
        (
            "zh",
            "## 角色",
            "可执行代码必须使用",
            "### 需求不明确",
            "### 需求明确",
        ),
        (
            "en",
            "## Role",
            "Executable code must use",
            "### Unclear Request",
            "### Clear Request",
        ),
    ],
)
def test_build_nl2agent_system_prompt_is_runtime_specific(
    language, expected, format_rule, unclear_example, clear_example
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
    assert "few_shots_prompt" not in prompt
    assert format_rule in prompt
    assert unclear_example in prompt
    assert clear_example in prompt
    assert "<code>" in prompt
    assert "</code>" in prompt
    assert 'result = runtime_search(keywords=[' in prompt
    assert prompt.count("print(result)") >= 2


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
