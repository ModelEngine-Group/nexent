# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Default prompt generation remains available after private templates retire."""

import pytest

from contracts import agent as model
from management.db.models import AgentInfo, TableBase
from management.services.agent import naming, prompt
from nexent.core.agents.prompt.meta import compose_agent_generation_user


@pytest.mark.parametrize("language", ["zh", "en"])
def test_default_generation_resources_remain_complete(language):
    resource = prompt.load_default_generation_prompt(language)

    assert {"duty_system_prompt", "constraint_system_prompt", "few_shots_system_prompt", "user_prompt"} <= resource.keys()
    assert all(isinstance(value, str) and value.strip() for value in resource.values())
    assert resource != prompt.load_default_generation_prompt("en" if language == "zh" else "zh")


@pytest.mark.parametrize("language", [None, "", "unknown", "en-US"])
def test_unknown_language_uses_chinese_defaults(language):
    assert prompt.load_default_generation_prompt(language) == prompt.load_default_generation_prompt("zh")


def test_default_generation_keeps_string_fields_without_mutating_resource(mocker):
    raw = {"DUTY_SYSTEM_PROMPT": "Duty", "USER_PROMPT": "Task", "metadata": {"version": 1}}
    load = mocker.patch.object(prompt, "load_generation_template", return_value=raw)

    assert prompt.load_default_generation_prompt("en") == {"duty_system_prompt": "Duty", "user_prompt": "Task"}
    load.assert_called_once_with("en")
    assert raw["DUTY_SYSTEM_PROMPT"] == "Duty"
    assert "duty_system_prompt" not in raw


def test_missing_default_resource_is_reported(mocker):
    mocker.patch.object(prompt, "load_generation_template", side_effect=FileNotFoundError("missing default resource"))

    with pytest.raises(FileNotFoundError, match="missing default resource"):
        prompt.load_default_generation_prompt("zh")


@pytest.mark.parametrize("language", ["zh", "en"])
def test_default_generation_renders_task_and_selected_resources(language):
    rendered = compose_agent_generation_user(
        language, prompt.load_default_generation_prompt(language),
        task_description="Find deployment documentation",
        tools=[{"name": "search_docs", "description": "Search internal documentation", "inputs": {}, "output_type": "string"}],
        worker_agents=[{"name": "writer", "description": "Write the deployment guide"}],
        has_local_knowledge_tool=False, has_aidp_knowledge_tool=False,
        has_selected_resources=True,
    )

    assert "Find deployment documentation" in rendered
    assert "search_docs" in rendered
    assert "writer" in rendered
    assert "{{" not in rendered


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("field", ["name", "display_name"])
def test_naming_renders_default_resources_without_private_lookup(mocker, language, field):
    llm = mocker.patch.object(naming, "call_llm_for_system_prompt", return_value="fresh_name")

    assert naming.regenerate_agent_value(
        field, "old_name", ["old_name"], "Find deployment documentation", 1, "tenant",
        language=language, agents_cache=[],
    ) == "fresh_name"
    request = llm.call_args.kwargs
    assert request["system_prompt"].strip()
    assert "old_name" in request["user_prompt"]
    assert "Find deployment documentation" in request["user_prompt"]


@pytest.mark.parametrize("request_type", [model.AgentRequest, model.AgentInfoRequest, model.GeneratePromptRequest, model.ExportAndImportAgentInfo])
def test_agent_contracts_no_longer_expose_private_template_fields(request_type):
    assert {"prompt_template_id", "prompt_template_name"}.isdisjoint(request_type.model_fields)
    assert {"prompt_template_id", "prompt_template_name"}.isdisjoint(request_type.model_json_schema()["properties"])


def test_legacy_agent_payload_drops_retired_fields():
    request = model.AgentInfoRequest.model_validate({
        "agent_id": 1,
        "name": "Existing Agent",
        "duty_prompt": "Preserve the saved prompt",
        "prompt_template_id": 42,
        "prompt_template_name": "Private template",
    })

    saved = request.model_dump()
    assert saved["duty_prompt"] == "Preserve the saved prompt"
    assert {"prompt_template_id", "prompt_template_name"}.isdisjoint(saved)


def test_agent_orm_does_not_require_private_template_storage():
    assert {"prompt_template_id", "prompt_template_name"}.isdisjoint(AgentInfo.__table__.columns.keys())
    assert "nexent.ag_prompt_template_t" not in TableBase.metadata.tables
