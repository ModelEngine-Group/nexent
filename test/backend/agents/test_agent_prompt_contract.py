# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Single-prompt persistence and NL2Agent boundary regressions."""

import json

import pytest
from pydantic import ValidationError

from tool_collection.mcp import nl2agent_mcp_tools as tools
from infrastructure.agent_prompt import normalize_imported_agent_prompt


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
    fields = tools.AgentDraftFields(prompt="Complete prompt", example_questions=["Q1", "Q2"])
    assert fields.model_dump(exclude_unset=True) == {"prompt": "Complete prompt", "example_questions": ["Q1", "Q2"]}
    with pytest.raises(ValidationError):
        tools.AgentDraftFields(example_questions=[{"question": "Q"}])


@pytest.mark.parametrize("fields,expected", [
    ({"prompt": "职责", "constraint_prompt": "规则", "few_shots_prompt": "示例"},
     "# Responsibilities\n职责\n\n# Constraints\n规则\n\n# Examples\n示例"),
    ({"constraint_prompt": "规则"}, "# Constraints\n规则"),
    ({"few_shots_prompt": "  <code>\n    call()\n  </code>"},
     "# Examples\n  <code>\n    call()\n  </code>"),
    ({"prompt": " exact\n  code ", "constraint_prompt": " \n", "few_shots_prompt": None}, " exact\n  code "),
    ({"prompt": ""}, ""),
    ({"prompt": None, "constraint_prompt": None, "few_shots_prompt": None}, None),
])
def test_import_conversion_preserves_content_and_consumes_old_sections_once(fields, expected):
    original = dict(fields)
    result = normalize_imported_agent_prompt(fields)
    assert result.get("prompt") == expected
    assert "constraint_prompt" not in result
    assert "few_shots_prompt" not in result
    assert normalize_imported_agent_prompt(result) == result
    assert fields == original


def test_current_request_and_export_schemas_expose_only_the_unified_prompt():
    from contracts.agent import AgentInfoRequest, ExportAndImportAgentInfo

    for model in (AgentInfoRequest, ExportAndImportAgentInfo):
        properties = model.model_json_schema()["properties"]
        assert "prompt" in properties
        assert "constraint_prompt" not in properties
        assert "few_shots_prompt" not in properties


def test_external_import_consolidates_old_bundle_once_and_exports_only_prompt():
    from contracts.agent import AgentImportRequest, ExportAndImportAgentInfo

    fields = dict(
        agent_id=1, name="test", description="Description", max_steps=5,
        provide_run_summary=False, enabled=True, tools=[], managed_agents=[],
        prompt="Purpose", constraint_prompt="Rule", few_shots_prompt="Example",
    )
    model = AgentImportRequest(agent_info={"agent_id": 1, "agent_info": {"1": fields}, "mcp_info": []}).agent_info.agent_info["1"]
    assert model.prompt == "# Responsibilities\nPurpose\n\n# Constraints\nRule\n\n# Examples\nExample"
    exported = model.model_dump()
    assert "constraint_prompt" not in exported
    assert "few_shots_prompt" not in exported
    assert not hasattr(model, "constraint_prompt")
    assert not hasattr(model, "few_shots_prompt")
    assert ExportAndImportAgentInfo.model_validate(exported).prompt == model.prompt


@pytest.mark.asyncio
async def test_verified_draft_context_exposes_only_the_unified_prompt(mocker):
    from services import nl2agent_service

    mocker.patch.object(nl2agent_service, "_load_verified_nl2agent_state", return_value=({
        "prompt": "Complete prompt",
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


@pytest.mark.parametrize("field", ["prompt", "constraint_prompt", "few_shots_prompt"])
@pytest.mark.parametrize("value", [[], {"text": "wrong type"}, 7])
def test_import_rejects_invalid_prompt_types_with_validation_error(field, value):
    from contracts.agent import AgentImportRequest, ExportAndImportAgentInfo

    data = dict(agent_id=1, name="test", description="Description", max_steps=5,
                provide_run_summary=False, enabled=True, tools=[], managed_agents=[],
                constraint_prompt="Rule")
    data[field] = value
    with pytest.raises(ValidationError, match=field):
        AgentImportRequest(agent_info={"agent_id": 1, "agent_info": {"1": data}, "mcp_info": []})
