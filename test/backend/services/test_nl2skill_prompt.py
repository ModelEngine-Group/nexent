# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regressions for localized skill-creator system context and output instructions."""

from unittest.mock import MagicMock

import pytest
from smolagents import CodeAgent

import services.nl2skill_service as nl2skill_service
from agents.nl2skill_agent import create_nl2skill_agent_config
from consts.model import NL2SkillRunRequest
from management.services.skill.prompt import get_nl2skill_prompt_template
from nexent.core.agents.context import ContextManager, ContextManagerConfig


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("targeted", [False, True])
def test_skill_creator_uses_only_localized_system_context(mocker, language, targeted):
    draft = {
        "name": "report-builder", "description": "Create reports", "tags": [],
        "content": "Keep {{ customer_name }} and {% if enabled %} literally.",
    }
    prompt = get_nl2skill_prompt_template(
        language, existing_skill=draft, user_request="Update the report",
        target_files=["scripts/report.py"] if targeted else [],
    )["system_prompt"]
    config = create_nl2skill_agent_config(prompt, "selected-model")
    default_resources = mocker.patch(
        "smolagents.agents.importlib.resources.files",
        side_effect=AssertionError("Default CodeAgent prompt must not be loaded"),
    )
    agent = CodeAgent(
        tools=[], model=MagicMock(), prompt_templates=config.prompt_templates,
        instructions=config.instructions,
    )
    manager = ContextManager(config=ContextManagerConfig(), max_steps=config.max_steps)
    context = manager.prepare_run_context(
        memory=agent.memory, fallback_system_prompt=agent.system_prompt, items=config.context_items,
    )
    system_texts = [
        part["text"] for message in context.item_messages if message["role"] == "system"
        for part in message["content"]
    ]

    assert system_texts == [prompt]
    assert config.instructions is None
    assert agent.system_prompt == ""
    assert "{{ customer_name }}" in system_texts[0]
    assert "{% if enabled %}" in system_texts[0]
    assert "You are an expert assistant who can solve any task using code blobs" not in system_texts[0]
    default_resources.assert_not_called()


@pytest.mark.parametrize("prompt", ["", " \n\t"])
def test_skill_creator_rejects_empty_system_prompt(prompt):
    with pytest.raises(ValueError, match="system prompt must not be empty"):
        create_nl2skill_agent_config(prompt, "model")


@pytest.mark.parametrize("language", ["zh", "en"])
def test_skill_creator_output_contract_keeps_targeted_and_full_updates_separate(language):
    full = get_nl2skill_prompt_template(language, user_request="Create a report skill")
    targeted = get_nl2skill_prompt_template(
        language, user_request="Update the script", target_files=["scripts/report.py"],
    )

    for prompts in (full, targeted):
        assert "<final_answer>" in prompts["system_prompt"]
        assert "</final_answer>" in prompts["system_prompt"]
        assert "<summary>" in prompts["system_prompt"]
        assert "<summary>" in prompts["user_prompt"]
        assert "the Agent must use Chinese format" not in prompts["system_prompt"]

    full_example = "### 单文件场景" if language == "zh" else "### Single-File Scenario"
    assert full_example in full["system_prompt"]
    assert full_example not in targeted["system_prompt"]
    assert '<file path="scripts/report.py">' in targeted["system_prompt"]
    only_skill = "只输出 `<skill>` 块" if language == "zh" else "output only the `<skill>` block"
    assert only_skill not in full["user_prompt"]


@pytest.mark.parametrize("language", ["zh", "en"])
def test_skill_creator_language_guidance_respects_requested_artifact_language(language):
    prompt = get_nl2skill_prompt_template(language)["system_prompt"]
    expected = (
        "用户明确指定产物语言时" if language == "zh"
        else "If the user explicitly requests an artifact language"
    )
    assert expected in prompt


def test_skill_creator_context_and_templates_are_request_scoped():
    first = create_nl2skill_agent_config("first system", "first model")
    second = create_nl2skill_agent_config("second system", "second model")
    first.prompt_templates["final_answer"]["pre_messages"] = "changed"
    first.context_items[0].content["text"] = "changed"

    assert second.prompt_templates["final_answer"]["pre_messages"] == ""
    assert second.context_items[0].content["text"] == "second system"


@pytest.mark.asyncio
@pytest.mark.parametrize(("language", "expected_language"), [("zh", "zh"), ("en", "en"), ("unknown", "zh")])
async def test_skill_run_info_keeps_selected_language_system_prompt(mocker, language, expected_language):
    mocker.patch.object(
        nl2skill_service, "create_model_config_list",
        return_value=[{"cite_name": "main_model", "model_name": "primary", "url": "https://model.test/v1"}],
    )
    mocker.patch.object(
        nl2skill_service, "_resolve_model_for_nl2skill", return_value=("main_model", "primary", {}),
    )
    query = "Create a report skill"
    result = await nl2skill_service.build_nl2skill_run_info(
        NL2SkillRunRequest(query=query), "tenant", language,
    )
    expected = get_nl2skill_prompt_template(expected_language, user_request=query)

    assert result.observer.lang == expected_language
    assert result.query == expected["user_prompt"]
    assert result.agent_config.context_items[0].content["text"] == expected["system_prompt"]
