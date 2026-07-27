import json

import pytest
from smolagents import Tool

from agents.nl2agent_agent import (
    GeneratedAgentDraft,
    InstalledMcpToolRecommendation,
    build_nl2agent_system_prompt,
    build_search_installed_mcp_tools,
    create_nl2agent_agent_config,
)


def _draft_payload() -> dict:
    return {
        "name": "weather_assistant",
        "display_name": "Weather Assistant",
        "description": "Search weather forecasts for users",
        "duty_prompt": "Find and summarize the requested forecast",
        "constraint_prompt": "Do not invent weather data",
        "few_shots_prompt": None,
    }


@pytest.mark.parametrize(
    ("language", "expected"),
    [("zh", "## 角色"), ("en", "## Role")],
)
def test_build_nl2agent_system_prompt_is_runtime_specific(language, expected):
    prompt = build_nl2agent_system_prompt(
        language,
        tool_name="runtime_search",
        max_results=3,
    )

    assert expected in prompt
    assert "runtime_search" in prompt
    assert "3" in prompt
    assert "few_shots_prompt" in prompt


def test_runtime_tool_returns_structured_json():
    calls = []

    def search_fn(tenant_id, draft, limit):
        calls.append((tenant_id, draft, limit))
        return [
            InstalledMcpToolRecommendation(
                tool_id=7,
                name="weather_search",
                description="Search weather forecasts",
                usage="weather-server",
                labels=["weather"],
                score=0.9123,
            )
        ]

    tool = build_search_installed_mcp_tools("tenant-a", "en", search_fn)
    result = json.loads(tool.invoke({"draft": _draft_payload()}))

    assert result["status"] == "success"
    assert result["recommendation_count"] == 1
    assert result["recommendations"][0]["tool_id"] == 7
    assert calls[0][0] == "tenant-a"
    assert isinstance(calls[0][1], GeneratedAgentDraft)
    assert calls[0][2] == 5


def test_runtime_tool_returns_structured_validation_error():
    tool = build_search_installed_mcp_tools(
        "tenant-a",
        "en",
        lambda *_args: [],
    )

    result = json.loads(tool.invoke({"draft": {"name": "incomplete"}}))

    assert result == {
        "status": "error",
        "code": "invalid_draft",
        "retryable": True,
    }


def test_runtime_tool_returns_structured_search_error():
    def failing_search(*_args):
        raise RuntimeError("database details must remain private")

    tool = build_search_installed_mcp_tools("tenant-a", "en", failing_search)
    result_text = tool.invoke({"draft": _draft_payload()})
    result = json.loads(result_text)

    assert result["code"] == "tool_search_failed"
    assert "database details" not in result_text


def test_runtime_tool_is_convertible_by_current_smolagents():
    langchain_tool = build_search_installed_mcp_tools(
        "tenant-a",
        "en",
        lambda *_args: [],
    )

    wrapped_tool = Tool.from_langchain(langchain_tool)
    result = json.loads(wrapped_tool(draft=_draft_payload()))

    assert wrapped_tool.name == "search_installed_mcp_tools"
    assert wrapped_tool.inputs["draft"]["type"] == "object"
    assert result["status"] == "success"


def test_create_nl2agent_agent_config_has_only_runtime_tool():
    tool = build_search_installed_mcp_tools(
        "tenant-a",
        "zh",
        lambda *_args: [],
    )

    config = create_nl2agent_agent_config("zh", tool)

    assert config.name == "__nl2agent_runtime__"
    assert config.model_name == "main_model"
    assert config.max_steps == 5
    assert config.enable_planning is False
    assert len(config.tools) == 1
    assert config.tools[0].source == "langchain"
    assert config.tools[0].metadata is tool
    assert "不得创建" in config.instructions
