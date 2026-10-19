# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Single-prompt persistence and NL2Agent boundary regressions."""

import json

import pytest
from pydantic import ValidationError

from tool_collection.mcp import nl2agent_mcp_tools as tools
from utils.agent_prompt import normalize_agent_prompt_fields


@pytest.mark.parametrize("fields", [
    {"constraint_prompt": ""},
    {"few_shots_prompt": "old example"},
    {"greeting_message": "Hello", "example_questions": ["Question"], "constraint_prompt": "", "few_shots_prompt": ""},
    {"example_questions": "Question one\nQuestion two"},
])
@pytest.mark.asyncio
async def test_invalid_model_payload_never_reaches_authorization_or_storage(mocker, fields):
    authorize = mocker.patch.object(tools, "get_http_request")
    mocker.patch.object(tools, "_resolve_agent_context_id", return_value=157)
    result, _ = json.JSONDecoder().raw_decode(await tools.save_agent_draft_fields(agent_id=157, fields=fields))
    assert result["status"] == "error"
    assert result["code"] == "invalid_agent_fields"
    authorize.assert_not_called()


def test_tool_schema_accepts_only_complete_prompt_and_array_questions():
    properties = tools.AgentDraftFields.model_json_schema()["properties"]
    assert "constraint_prompt" not in properties
    assert "few_shots_prompt" not in properties
    fields = tools.AgentDraftFields(duty_prompt="Complete prompt", example_questions=["Q1", "Q2"])
    assert fields.model_dump(exclude_unset=True) == {"duty_prompt": "Complete prompt", "example_questions": ["Q1", "Q2"]}
    with pytest.raises(ValidationError):
        tools.AgentDraftFields(example_questions=[{"question": "Q"}])


@pytest.mark.parametrize("fields,current,expected", [
    ({"duty_prompt": "职责", "constraint_prompt": "规则", "few_shots_prompt": "示例"}, None,
     "# Responsibilities\n职责\n\n# Constraints\n规则\n\n# Examples\n示例"),
    ({"constraint_prompt": "规则"}, "Existing prompt", "# Responsibilities\nExisting prompt\n\n# Constraints\n规则"),
    ({"few_shots_prompt": "  <code>\n    call()\n  </code>"}, None,
     "# Examples\n  <code>\n    call()\n  </code>"),
    ({"duty_prompt": " exact\n  code ", "constraint_prompt": " \n", "few_shots_prompt": None}, None, " exact\n  code "),
    ({"duty_prompt": ""}, "Old prompt", ""),
])
def test_legacy_writes_preserve_order_content_and_single_field_idempotency(fields, current, expected):
    original = dict(fields)
    result = normalize_agent_prompt_fields(fields, current)
    assert result["duty_prompt"] == expected
    assert result["constraint_prompt"] == result["few_shots_prompt"] == ""
    assert normalize_agent_prompt_fields(result) == result
    assert fields == original


def test_unrelated_partial_edit_does_not_reset_the_prompt():
    fields = {"description": "New description", "example_questions": []}
    assert normalize_agent_prompt_fields(fields, "Existing prompt") == fields


def test_import_model_consolidates_old_bundle_once():
    from consts.model import ExportAndImportAgentInfo

    model = ExportAndImportAgentInfo(
        agent_id=1, name="test", description="Description", max_steps=5,
        provide_run_summary=False, enabled=True, tools=[], managed_agents=[],
        duty_prompt="Purpose", constraint_prompt="Rule", few_shots_prompt="Example",
    )
    assert model.duty_prompt == "# Responsibilities\nPurpose\n\n# Constraints\nRule\n\n# Examples\nExample"
    assert model.constraint_prompt == model.few_shots_prompt == ""
    assert ExportAndImportAgentInfo.model_validate(model.model_dump()).duty_prompt == model.duty_prompt


@pytest.mark.asyncio
async def test_verified_draft_context_exposes_only_the_unified_prompt(mocker):
    from services import nl2agent_service

    mocker.patch.object(nl2agent_service, "_load_verified_nl2agent_state", return_value=({
        "duty_prompt": "Complete prompt",
        "constraint_prompt": "LEGACY_RULE_POISON",
        "few_shots_prompt": "LEGACY_EXAMPLE_POISON",
        "greeting_message": "Hello",
    }, []))
    context = await nl2agent_service._build_verified_bound_resources_context(
        agent_id=157, tenant_id="tenant-a", user_id="user-a",
    )
    text = context.content["text"]
    assert "Complete prompt" in text
    assert "constraint_prompt" not in text
    assert "few_shots_prompt" not in text
    assert "LEGACY" not in text
