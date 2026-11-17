# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from types import SimpleNamespace

import pytest

from contracts.errors.exceptions import AgentDraftEditError
from services import nl2agent_service as service
from tool_collection.mcp import nl2agent_mcp_tools as tools


@pytest.fixture
def authorized_context(mocker):
    headers = {tools.NL2AGENT_AGENT_ID_HEADER: "42", "Authorization": "Bearer fixture"}
    mocker.patch.object(tools, "get_http_request", return_value=SimpleNamespace(headers=headers))
    mocker.patch.object(tools, "get_current_user_id", return_value=("user", "tenant"))
    return headers


def decode_state(result):
    body, marker = result.split("\n")
    return json.loads(body), json.loads(marker.removeprefix("<nl2a_state>").removesuffix("</nl2a_state>"))


@pytest.mark.asyncio
async def test_final_batch_reports_persisted_fields_without_running_completion(mocker, authorized_context):
    fields = ["greeting_message", "example_questions"]
    mocker.patch.object(service, "save_agent_draft_fields_impl", return_value={
        "status": "success", "agent_id": 42, "created": False, "updated_fields": fields,
    })
    check = mocker.patch.object(service, "validate_agent_generation_complete_impl")
    body, state = decode_state(await tools.save_agent_draft_fields(42, {
        "greeting_message": "Hello", "example_questions": ["What can I ask?"],
    }))
    assert body["status"] == "success"
    assert state == {"event": "agent_draft_fields_saved", "agent_id": 42, "updated_fields": fields}
    check.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_check_emits_completion_for_trusted_target_without_saving(mocker, authorized_context):
    check = mocker.patch.object(service, "validate_agent_generation_complete_impl")
    save = mocker.patch.object(service, "save_agent_draft_fields_impl")
    body, state = decode_state(await tools.validate_agent_generation_complete())
    assert body == {"status": "success", "agent_id": 42}
    assert state == {"event": "agent_generation_completed", "agent_id": 42}
    check.assert_awaited_once_with(agent_id=42, tenant_id="tenant", user_id="user")
    save.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [None, "invalid", "0", "-1"])
async def test_explicit_check_rejects_missing_or_invalid_run_target(mocker, authorized_context, target):
    if target is None:
        authorized_context.pop(tools.NL2AGENT_AGENT_ID_HEADER)
    else:
        authorized_context[tools.NL2AGENT_AGENT_ID_HEADER] = target
    check = mocker.patch.object(service, "validate_agent_generation_complete_impl")
    assert json.loads(await tools.validate_agent_generation_complete()) == {
        "status": "error", "code": "agent_context_mismatch", "retryable": False,
    }
    tools.get_current_user_id.assert_not_called()
    check.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("error", "code", "retryable", "failed_fields"), [
    (service.Nl2AgentCompletionError("draft_fields_incomplete", ["description"]),
     "draft_fields_incomplete", False, ["description"]),
    (AgentDraftEditError("agent_not_found"), "agent_not_found", False, None),
    (RuntimeError("private detail"), "generation_validation_failed", True, None),
])
async def test_failed_check_has_no_save_failure_or_completion_event(
    mocker, authorized_context, error, code, retryable, failed_fields,
):
    mocker.patch.object(service, "validate_agent_generation_complete_impl", side_effect=error)
    save = mocker.patch.object(service, "save_agent_draft_fields_impl")
    expected = {"status": "error", "code": code, "retryable": retryable}
    if failed_fields:
        expected["failed_fields"] = failed_fields
    assert json.loads(await tools.validate_agent_generation_complete()) == expected
    save.assert_not_called()
