# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Target Agent protocol policy, shared by both NL2Agent creator entries."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.nl2agent_agent import build_nl2agent_system_prompt
from services import nl2agent_service as service
from tool_collection.mcp import nl2agent_mcp_tools as tools

FIELD = "enable_protocol_repair_retry"


@pytest.mark.parametrize("value", [True, False])
def test_explicit_boolean_patch_preserves_false_and_unrelated_fields(mocker, value):
    mocker.patch.object(service, "require_agent_draft_edit", return_value={"name": "test_assistant"})
    update = mocker.patch.object(service, "update_agent_draft_fields", return_value=1)
    result = service.save_agent_draft_fields_impl(42, tools.AgentDraftFields(**{FIELD: value}), "tenant", "user")
    update.assert_called_once_with(agent_id=42, tenant_id="tenant", fields={FIELD: value})
    assert result["updated_fields"] == [FIELD]


@pytest.mark.parametrize("value", [None, "true", "false", "yes", 0, 1, [], {}])
@pytest.mark.asyncio
async def test_invalid_policy_never_authorizes_or_writes(mocker, value):
    auth = mocker.patch.object(tools, "get_current_user_id")
    update = mocker.patch.object(service, "update_agent_draft_fields")
    mocker.patch.object(tools, "_resolve_agent_context_id", return_value=42)
    result = await tools.save_agent_draft_fields(42, {FIELD: value})
    assert json.loads(result)["code"] == "invalid_agent_fields"
    assert "<nl2a_state>" not in result
    auth.assert_not_called()
    update.assert_not_called()


def test_omitted_policy_does_not_reset_existing_setting(mocker):
    mocker.patch.object(service, "require_agent_draft_edit", return_value={FIELD: True})
    update = mocker.patch.object(service, "update_agent_draft_fields", return_value=1)
    service.save_agent_draft_fields_impl(42, tools.AgentDraftFields(description="New purpose"), "tenant", "user")
    assert update.call_args.kwargs["fields"] == {"description": "New purpose"}


@pytest.mark.parametrize("draft,expected", [({}, False), ({FIELD: False}, False), ({FIELD: True}, True)])
@pytest.mark.asyncio
async def test_verified_state_includes_effective_policy(mocker, draft, expected):
    mocker.patch.object(service, "_load_verified_nl2agent_state", new=AsyncMock(return_value=(draft, [])))
    context = await service._build_verified_bound_resources_context(agent_id=42, tenant_id="tenant", user_id="user")
    state = json.loads(context.content["text"].removeprefix("Verified database binding facts: "))
    assert state["draft_fields"][FIELD] is expected


@pytest.fixture
def authorized_tool(mocker):
    mocker.patch.object(tools, "_resolve_agent_context_id", return_value=42)
    mocker.patch.object(tools, "get_http_request", return_value=SimpleNamespace(headers={"Authorization": "Bearer test"}))
    mocker.patch.object(tools, "get_current_user_id", return_value=("user", "tenant"))
    mocker.patch.object(service, "require_agent_draft_edit", return_value={"name": "test_assistant"})


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.asyncio
async def test_policy_tool_emits_save_without_generation_completion(mocker, authorized_tool, value):
    update = mocker.patch.object(service, "update_agent_draft_fields", return_value=1)
    complete = mocker.patch.object(service, "validate_agent_generation_complete_impl", new_callable=AsyncMock)
    result = await tools.save_agent_draft_fields(42, {FIELD: value})
    body, event = result.split("\n", 1)
    assert json.loads(body)["updated_fields"] == [FIELD]
    assert json.loads(event.removeprefix("<nl2a_state>").removesuffix("</nl2a_state>")) == {
        "event": "agent_draft_fields_saved", "agent_id": 42, "updated_fields": [FIELD],
    }
    assert "agent_generation_completed" not in result
    assert "prompt_generation_failed" not in result
    update.assert_called_once_with(agent_id=42, tenant_id="tenant", fields={FIELD: value})
    complete.assert_not_awaited()


@pytest.mark.parametrize("code", ["agent_not_found", "agent_read_only", "agent_context_mismatch"])
@pytest.mark.asyncio
async def test_policy_edit_permission_failures_do_not_write(mocker, authorized_tool, code):
    mocker.patch.object(service, "require_agent_draft_edit", side_effect=service.AgentDraftEditError(code))
    update = mocker.patch.object(service, "update_agent_draft_fields")
    result = await tools.save_agent_draft_fields(42, {FIELD: True})
    assert json.loads(result)["code"] == code
    assert "<nl2a_state>" not in result
    update.assert_not_called()


@pytest.mark.asyncio
async def test_policy_storage_failure_does_not_emit_success(mocker, authorized_tool):
    mocker.patch.object(service, "update_agent_draft_fields", side_effect=RuntimeError("database unavailable"))
    result = await tools.save_agent_draft_fields(42, {FIELD: False})
    assert json.loads(result)["code"] == "draft_save_failed"
    assert json.loads(result)["retryable"] is True
    assert "<nl2a_state>" not in result


@pytest.mark.parametrize("language", ["zh", "en"])
def test_bilingual_policy_prompt_preserves_scope_and_explicit_intent(language):
    prompt = build_nl2agent_system_prompt(language)
    assert FIELD in prompt
    assert "update_execution_policy" in prompt
    assert 'enable_protocol_repair_retry=True' in prompt
    assert 'requirement_clarification' in prompt
    assert ('模型服务请求重试' in prompt or 'model-service request retries' in prompt)
    assert ('保留可信草稿当前值' in prompt or 'preserve its verified draft value' in prompt)
    assert ('四个生成字段之外的其他字段都不能' not in prompt)
    assert ('any other field outside the four generated fields are not editable' not in prompt)


def test_creator_tool_schema_advertises_boolean_policy():
    config = next(tool for tool in tools.create_nl2agent_mcp_tool_configs()
                  if tool.name == tools.SAVE_AGENT_DRAFT_FIELDS_NAME)
    assert json.loads(config.inputs)["fields"][FIELD] == "bool"
    assert FIELD in config.description
