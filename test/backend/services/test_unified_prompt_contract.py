# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Canonical prompt naming and compatibility at Agent boundaries."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from management.services.agent.creation import build_nl2agent_system_prompt
from contracts.agent import AgentImportRequest, AgentInfoRequest, ExportAndImportAgentInfo
from management.utils.orm import as_dict, filter_property
from management.db.agent.models import AgentInfo
from infrastructure.agent_prompt import normalize_imported_agent_bundle, normalize_imported_agent_prompt
from management.services.repository.agent.listing import _extract_root_agent_from_snapshot
from nexent.core.utils.observer import MessageObserver
from services import nl2agent_service as service
from tool_collection.mcp import nl2agent_mcp_tools as tools


def test_request_and_tool_accept_only_canonical_prompt():
    key = "prompt"
    text = "  Responsibilities\nConstraints\nTool rules\nExample\n"
    request = AgentInfoRequest.model_validate({key: text})
    patch = tools.AgentDraftFields.model_validate({key: text})
    assert request.model_dump(exclude_unset=True) == {"prompt": text}
    assert patch.model_dump(exclude_unset=True) == {"prompt": text}
    assert patch.model_fields_set == {"prompt"}
    for model in (AgentInfoRequest, tools.AgentDraftFields, ExportAndImportAgentInfo):
        properties = model.model_json_schema()["properties"]
        assert "prompt" in properties
        assert "duty_prompt" not in properties


@pytest.mark.parametrize("fields", [
    {"prompt": None}, {}, {"prompt": 7},
    {"prompt": "New", "duty_prompt": "Old"},
    {"prompt": "New", "constraint_prompt": "Hidden"},
])
def test_tool_rejects_invalid_or_ambiguous_patch(fields):
    with pytest.raises(ValidationError):
        tools.AgentDraftFields.model_validate(fields)


@pytest.mark.parametrize("key", ["duty_prompt", "constraint_prompt", "constraints_prompt", "few_shots_prompt", "few_shot_prompts"])
def test_tool_schema_rejects_unknown_fields(key):
    with pytest.raises(ValidationError):
        tools.AgentDraftFields.model_validate({"prompt": "New", key: "Old"})


@pytest.mark.parametrize("key", ["prompt", "duty_prompt"])
def test_external_imports_keep_complete_content_without_runtime_snapshot_conversion(key):
    fields = {key: "Research", "constraint_prompt": "Use evidence", "few_shots_prompt": "Q -> A"}
    expected = "# Responsibilities\nResearch\n\n# Constraints\nUse evidence\n\n# Examples\nQ -> A"
    normalized = normalize_imported_agent_prompt(fields)
    assert normalized == {"prompt": expected}
    root = _extract_root_agent_from_snapshot({"agent_id": 170, "agent_info": {"170": fields}})
    assert root == fields
    assert "constraint_prompt" in root
    snapshot = {"agent_id": 170, "agent_info": {"170": fields, "child": {key: "Child prompt"}}}
    result = normalize_imported_agent_bundle(snapshot)
    assert result["agent_info"] == {"170": normalized, "child": {"prompt": "Child prompt"}}
    assert snapshot["agent_info"]["170"] is fields
    payload = {"agent_id": 170, "name": "research_assistant", "description": "Research",
               "max_steps": 5, "provide_run_summary": False, "enabled": True,
               "tools": [], "managed_agents": [], **fields}
    exported = AgentImportRequest.model_validate({"agent_info": {"agent_id": 170, "agent_info": {"170": payload}, "mcp_info": []}}).agent_info.agent_info["170"].model_dump()
    assert exported["prompt"] == expected
    assert "duty_prompt" not in exported
    assert fields == {key: "Research", "constraint_prompt": "Use evidence", "few_shots_prompt": "Q -> A"}


def test_orm_serialization_and_filtering_use_canonical_column():
    values = {"prompt": "Complete prompt", "description": "Keep description"}
    agent = AgentInfo(**values)
    assert as_dict(agent)["prompt"] == values["prompt"]
    assert "duty_prompt" not in as_dict(agent)
    assert filter_property(values, AgentInfo) == values
    assert AgentInfo.__table__.c.prompt.name == "prompt"


@pytest.mark.asyncio
async def test_partial_prompt_save_retains_unrequested_fields_and_uses_canonical_events(mocker):
    original = "# Role\nResearch\n# Constraints\nUse sources\n# Example\nQuestion -> Answer"
    merged = original.replace("Use sources", "Use verified sources")
    draft = {"agent_id": 170, "name": "research_assistant", "prompt": original,
             "description": "Keep description", "greeting_message": "Keep greeting"}
    mocker.patch.object(tools, "get_http_request", return_value=SimpleNamespace(headers={
        "Authorization": "Bearer test", tools.NL2AGENT_AGENT_ID_HEADER: "170",
    }))
    mocker.patch.object(tools, "get_current_user_id", return_value=("owner", "tenant"))
    mocker.patch.object(service, "require_agent_draft_edit", return_value=dict(draft))
    update = mocker.patch.object(service, "update_agent_draft_fields", return_value=1)
    mocker.patch.object(service, "validate_agent_generation_complete_impl", return_value=None)

    raw = await tools.save_agent_draft_fields(170, {"prompt": merged})

    assert update.call_args.kwargs["fields"] == {"prompt": merged}
    assert draft["prompt"] == original
    assert draft["description"] == "Keep description"
    assert "duty_prompt" not in raw
    assert json.loads(raw.split("\n", 1)[0])["updated_fields"] == ["prompt"]


@pytest.mark.asyncio
async def test_verified_context_preserves_complete_prompt(mocker):
    text = "# Role\n  whitespace\n# Rules\nDo not invent\n# Example\nQ -> A\n"
    mocker.patch.object(service, "_load_verified_nl2agent_state", return_value=(
        {"prompt": text, "description": "Keep"}, [],
    ))
    context = await service._build_verified_bound_resources_context(
        agent_id=170, tenant_id="tenant", user_id="owner",
    )
    state = json.loads(context.content["text"].split(": ", 1)[1])
    assert state["draft_fields"]["prompt"] == text
    assert "duty_prompt" not in state["draft_fields"]


@pytest.mark.parametrize("event,field_key", [
    ("agent_draft_fields_saved", "updated_fields"),
    ("prompt_generation_failed", "failed_fields"),
])
@pytest.mark.parametrize("field_name", ["prompt", "duty_prompt", "constraint_prompt", "few_shots_prompt", "constraints_prompt", "few_shot_prompts"])
def test_observer_accepts_only_canonical_state_fields(event, field_key, field_name):
    state = {"event": event, "agent_id": 170, field_key: [field_name]}
    normalized, visible = MessageObserver._extract_nl2a_state(
        "result\n<nl2a_state>" + json.dumps(state) + "</nl2a_state>",
    )
    assert visible == "result"
    if field_name == "prompt":
        assert json.loads(normalized)[field_key] == ["prompt"]
    else:
        assert normalized is None
    state[field_key] = ["prompt", "duty_prompt"]
    assert MessageObserver._extract_nl2a_state(
        "<nl2a_state>" + json.dumps(state) + "</nl2a_state>",
    )[0] is None


def test_failed_tool_result_uses_prompt_in_raw_state():
    raw = tools._serialize_agent_draft_save_result(
        tools.SaveAgentDraftFieldsError(agent_id=170, code="invalid_agent_fields", retryable=False),
        attempted_fields=["prompt"],
    )
    assert "duty_prompt" not in raw
    state, _ = MessageObserver._extract_nl2a_state(raw)
    assert json.loads(state)["failed_fields"] == ["prompt"]


@pytest.mark.parametrize("language", ["zh", "en"])
def test_model_instructions_are_self_contained_and_preserve_partial_edits(language):
    prompt = build_nl2agent_system_prompt(language)
    assert "duty_prompt" not in prompt
    assert "nl2agent_verified_state.draft_fields.prompt" in prompt
    assert "research_assistant" in prompt
    assert "few-shot" in prompt
    expected = (
        ["职责", "约束", "工具使用规则", "合并后的完整", "不得只提交片段"]
        if language == "zh" else
        ["responsibilities", "constraints", "tool-use rules", "entire merged", "never just a replacement fragment"]
    )
    for text in expected:
        assert text in prompt


def test_retired_tool_field_does_not_generate_a_canonical_failure_event():
    raw = tools._serialize_agent_draft_save_result(
        tools.SaveAgentDraftFieldsError(agent_id=170, code="invalid_agent_fields", retryable=False),
        attempted_fields=["duty_prompt"],
    )
    assert "<nl2a_state>" not in raw
