# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Configuration MCP authentication, error contracts and draft-save receipts."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from contracts.errors.exceptions import AgentDraftEditError, UnauthorizedError
from tool_collection.mcp import nl2agent_configuration_tools as tools


@pytest.fixture
def context(mocker):
    headers = {tools.NL2AGENT_AGENT_ID_HEADER: "42", tools.NL2AGENT_RUN_ID_HEADER: "run",
               tools.NL2AGENT_CONVERSATION_ID_HEADER: "7", "Authorization": "Bearer test"}
    mocker.patch.object(tools, "get_http_request", return_value=SimpleNamespace(headers=headers))
    mocker.patch.object(tools, "get_current_user_context", return_value=("user", "tenant", "USER"))
    return headers


@pytest.mark.parametrize("role,can_edit", [("USER", False), *[(role, True) for role in tools.CAN_EDIT_ALL_USER_ROLES]])
def test_context_derives_edit_capability_from_authenticated_role(mocker, context, role, can_edit):
    identity = mocker.patch.object(tools, "get_current_user_context", return_value=("user", "tenant", role))
    caller, agent_id, headers = tools._context()
    assert caller.user_id == "user" and caller.authenticated_tenant_id == "tenant"
    assert caller.can_edit_all is can_edit and agent_id == 42 and headers is context
    identity.assert_called_once_with("Bearer test")


@pytest.mark.asyncio
@pytest.mark.parametrize("key,value,code", [
    (tools.NL2AGENT_AGENT_ID_HEADER, "0", "invalid_configuration_context"),
    (tools.NL2AGENT_AGENT_ID_HEADER, "bad", "invalid_configuration"),
    (tools.NL2AGENT_RUN_ID_HEADER, "", "invalid_configuration_context"),
])
async def test_invalid_context_prevents_configuration_read(mocker, context, key, value, code):
    context[key] = value
    read = mocker.patch.object(tools, "read_configuration", new=AsyncMock())
    assert (await tools.read_agent_configuration("model"))["code"] == code
    read.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_returns_scoped_section(mocker, context):
    read = mocker.patch.object(tools, "read_configuration", new=AsyncMock(return_value={"model_ids": [2]}))
    assert await tools.read_agent_configuration("model") == {
        "status": "success", "agent_id": 42, "section": "model", "configuration": {"model_ids": [2]},
    }
    assert read.call_args.args[0].user_id == "user" and read.call_args.args[1:] == (42, "model")


@pytest.mark.asyncio
@pytest.mark.parametrize("error,code,retryable", [
    (AgentDraftEditError("agent_read_only"), "agent_read_only", False),
    (tools.ConfigurationError("configuration_changed"), "configuration_changed", True),
    (ValueError("invalid input"), "invalid_configuration", False),
    (PermissionError("private"), "unauthorized", False),
    (UnauthorizedError("private"), "unauthorized", False),
    (RuntimeError("private server details"), "configuration_operation_failed", True),
])
async def test_read_and_save_return_stable_errors(mocker, context, error, code, retryable):
    mocker.patch.object(tools, "read_configuration", new=AsyncMock(side_effect=error))
    mocker.patch.object(tools, "save_configuration", new=AsyncMock(side_effect=error))
    expected = {"status": "error", "code": code, "retryable": retryable}
    assert await tools.read_agent_configuration("advanced") == expected
    result = await tools.save_agent_configuration("advanced", {"max_steps": 10})
    assert json.loads(result.content[0].text) == expected
    assert not result.meta


@pytest.mark.asyncio
async def test_policy_clarification_blocks_retry_setting_without_write(mocker, context):
    context[tools.NL2AGENT_POLICY_CLARIFICATION_HEADER] = "true"
    save = mocker.patch.object(tools, "save_configuration", new=AsyncMock())
    result = await tools.save_agent_configuration("advanced", {"enable_protocol_repair_retry": True})
    assert json.loads(result.content[0].text)["code"] == "policy_clarification_required"
    save.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("conversation", ["7", None])
async def test_save_receipt_is_bound_to_current_run(mocker, context, conversation):
    if conversation is None:
        context.pop(tools.NL2AGENT_CONVERSATION_ID_HEADER)
    save = mocker.patch.object(tools, "save_configuration", new=AsyncMock(return_value=["max_steps"]))
    result = await tools.save_agent_configuration("advanced", {"max_steps": 12})
    assert json.loads(result.content[0].text) == {
        "status": "success", "agent_id": 42, "section": "advanced", "updated_fields": ["max_steps"],
    }
    receipt = result.meta[tools.NL2AGENT_RECEIPT_KEY]
    assert receipt["event_id"] and receipt["run_id"] == "run"
    assert receipt["conversation_id"] == (conversation or "")
    assert receipt["payload"] == {"event": "agent_draft_fields_saved", "agent_id": 42, "updated_fields": ["max_steps"]}
    assert save.call_args.args[1:] == (42, "advanced", {"max_steps": 12})
