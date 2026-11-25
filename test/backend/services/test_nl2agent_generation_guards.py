# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Draft generation cannot bypass outstanding resource or prompt approvals."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services import nl2agent_prompt_service as prompts
from management.services.agent import nl2agent as service
from services.nl2agent_state_service import ResourceStateError
from management.services.agent import nl2agent_tools as tools


@pytest.fixture
def context(mocker):
    headers = {tools.NL2AGENT_AGENT_ID_HEADER: "42", tools.NL2AGENT_RUN_ID_HEADER: "run",
               tools.NL2AGENT_CONVERSATION_ID_HEADER: "7"}
    mocker.patch.object(tools, "get_http_request", return_value=SimpleNamespace(headers=headers))
    mocker.patch.object(tools, "_tool_actor", return_value=("user", "tenant"))
    return headers


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("prompt", "New"), ("greeting_message", "Hello"),
                                         ("example_questions", ["Weather?"])])
async def test_pending_resources_block_generated_fields(mocker, context, field, value):
    context[tools.NL2AGENT_RESOURCE_PENDING_HEADER] = "true"
    save = mocker.patch.object(service, "save_agent_draft_fields_impl")
    propose = mocker.patch.object(prompts, "propose", new=AsyncMock())
    result = await tools.save_agent_draft_fields(42, {field: value})
    assert json.loads(result.split("\n")[0])["code"] == "resource_confirmation_required"
    save.assert_not_called()
    propose.assert_not_awaited()


@pytest.mark.asyncio
async def test_prompt_must_be_saved_separately(mocker, context):
    save = mocker.patch.object(service, "save_agent_draft_fields_impl")
    result = await tools.save_agent_draft_fields(42, {"prompt": "New", "greeting_message": "Hello"})
    assert json.loads(result)["code"] == "save_prompt_separately"
    save.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [tools.NL2AGENT_RUN_ID_HEADER, tools.NL2AGENT_CONVERSATION_ID_HEADER])
async def test_prompt_proposal_requires_both_context_ids(mocker, context, header):
    context.pop(header)
    propose = mocker.patch.object(prompts, "propose", new=AsyncMock())
    assert json.loads(await tools.save_agent_draft_fields(42, {"prompt": "New"}))["code"] == "invalid_prompt_context"
    propose.assert_not_awaited()


@pytest.mark.asyncio
async def test_proposal_errors_keep_retryability_and_hide_private_details(mocker, context):
    mocker.patch.object(prompts, "propose", new=AsyncMock(side_effect=ResourceStateError("prompt_save_failed", retryable=True)))
    assert json.loads(await tools.save_agent_draft_fields(42, {"prompt": "New"})) == {
        "status": "error", "code": "prompt_save_failed", "retryable": True,
    }


@pytest.mark.asyncio
async def test_pending_prompt_blocks_final_fields_and_completion(mocker, context):
    guard = mocker.patch.object(prompts, "require_no_pending", new=AsyncMock(
        side_effect=ResourceStateError("prompt_confirmation_required"),
    ))
    save = mocker.patch.object(service, "save_agent_draft_fields_impl")
    complete = mocker.patch.object(service, "validate_agent_generation_complete_impl", new=AsyncMock())
    for result in (await tools.save_agent_draft_fields(42, {"greeting_message": "Hello"}),
                   await tools.validate_agent_generation_complete()):
        assert json.loads(result)["code"] == "prompt_confirmation_required"
    assert guard.await_count == 2
    assert guard.call_args.args[0].agent_id == 42
    save.assert_not_called()
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_after_resolved_prompt_calls_actual_validation(mocker, context):
    guard = mocker.patch.object(prompts, "require_no_pending", new=AsyncMock())
    complete = mocker.patch.object(service, "validate_agent_generation_complete_impl", new=AsyncMock())
    result = await tools.validate_agent_generation_complete()
    assert json.loads(result.split("\n")[0])["status"] == "success"
    guard.assert_awaited_once()
    complete.assert_awaited_once_with(agent_id=42, tenant_id="tenant", user_id="user")


@pytest.mark.asyncio
async def test_pending_resources_block_completion_before_prompt_read(mocker, context):
    context[tools.NL2AGENT_RESOURCE_PENDING_HEADER] = "true"
    guard = mocker.patch.object(prompts, "require_no_pending", new=AsyncMock())
    assert json.loads(await tools.validate_agent_generation_complete())["code"] == "resource_confirmation_required"
    guard.assert_not_awaited()


@pytest.mark.asyncio
async def test_unauthorized_completion_never_emits_success(mocker, context):
    mocker.patch.object(tools, "_tool_actor", side_effect=PermissionError())
    assert json.loads(await tools.validate_agent_generation_complete())["code"] == "unauthorized"
