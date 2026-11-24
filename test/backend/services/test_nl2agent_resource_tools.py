# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""MCP resource entry points validate context, map errors and publish receipts."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from contracts.errors.exceptions import AgentDraftEditError, UnauthorizedError
from management.services.agent.nl2agent import Nl2AgentResourceError
from services.nl2agent_state_service import ResourceScope, ResourceStateError
from tool_collection.mcp import nl2agent_resource_tools as tools


@pytest.fixture
def context(mocker):
    headers = {
        tools.NL2AGENT_AGENT_ID_HEADER: "42", tools.NL2AGENT_RUN_ID_HEADER: "run",
        tools.NL2AGENT_CONVERSATION_ID_HEADER: "7", "Authorization": "Bearer test",
    }
    mocker.patch.object(tools, "get_http_request", return_value=SimpleNamespace(headers=headers))
    identity = mocker.patch.object(tools, "get_current_user_id", return_value=("user", "tenant"))
    authorize = mocker.patch.object(tools, "require_agent_draft_edit")
    return headers, identity, authorize


def test_scope_uses_authenticated_identity_and_checks_draft(context):
    _, identity, authorize = context
    assert tools._scope() == ResourceScope("tenant", "user", 42, "7", "run")
    identity.assert_called_once_with("Bearer test")
    authorize.assert_called_once_with(agent_id=42, tenant_id="tenant", user_id="user")


@pytest.mark.parametrize("key,value", [
    (tools.NL2AGENT_AGENT_ID_HEADER, "bad"), (tools.NL2AGENT_AGENT_ID_HEADER, "0"),
    (tools.NL2AGENT_AGENT_ID_HEADER, "-1"), (tools.NL2AGENT_RUN_ID_HEADER, ""),
    (tools.NL2AGENT_CONVERSATION_ID_HEADER, ""),
])
def test_invalid_scope_fails_before_authorization(context, key, value):
    headers, identity, authorize = context
    headers[key] = value
    with pytest.raises(ResourceStateError, match="invalid_resource_context"):
        tools._scope()
    identity.assert_not_called()
    authorize.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error,code,retryable", [
    (ResourceStateError("resource_state_conflict", retryable=True), "resource_state_conflict", True),
    (Nl2AgentResourceError("resource_evidence_changed", retryable=True), "resource_evidence_changed", True),
    (AgentDraftEditError("agent_read_only"), "agent_read_only", False),
    (PermissionError("private"), "unauthorized", False),
    (UnauthorizedError("private"), "unauthorized", False),
    (RuntimeError("private server details"), "resource_workflow_failed", True),
])
async def test_run_maps_domain_and_unexpected_errors(context, error, code, retryable):
    operation = AsyncMock(side_effect=error)
    scope, result = await tools._run(operation, "argument")
    assert scope is None
    assert result == {"status": "error", "code": code, "retryable": retryable}
    operation.assert_awaited_once_with(ResourceScope("tenant", "user", 42, "7", "run"), "argument")


@pytest.mark.asyncio
async def test_authorization_failure_never_calls_operation(context):
    context[2].side_effect = PermissionError()
    operation = AsyncMock()
    assert (await tools._run(operation))[1]["code"] == "unauthorized"
    operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_discover_passes_validated_inputs_to_flow(mocker, context):
    discover = mocker.patch.object(tools.flow, "discover", new=AsyncMock(return_value={"batch": "next"}))
    assert await tools.discover_requirements([{"query": " Weather ", "search_queries": {
        "zh": "天气", "en": "weather",
    }}], "bind") == {"batch": "next"}
    scope, requirements, purpose, queries = discover.call_args.args
    assert scope.agent_id == 42 and purpose == "bind" and queries is None
    assert requirements[0].query == "Weather" and requirements[0].search_queries.en == "weather"
    await tools.discover_requirements(search_queries={"r1": {"zh": "天气", "en": "weather"}})
    assert discover.call_args.args[1] is None
    assert discover.call_args.args[3]["r1"].zh == "天气"


@pytest.mark.asyncio
async def test_requirement_limit_rejected_without_dispatch(mocker):
    dispatch = mocker.patch.object(tools, "_run", new=AsyncMock())
    result = await tools.discover_requirements([{"query": "x"}] * (tools.MAX_REQUIREMENTS + 1))
    assert result == {"status": "error", "code": "requirements_limit_exceeded", "retryable": False,
                      "max_requirements": tools.MAX_REQUIREMENTS}
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("batch,checks", [
    ("", [{"requirement_id": "r1", "accepted": []}]), ("b", []),
    ("b", [{"requirement_id": "r1", "accepted": []}] * 5),
    ("b", [{"requirement_id": "r1", "accepted": [], "extra": True}]),
])
async def test_invalid_verification_does_not_call_flow(mocker, batch, checks):
    dispatch = mocker.patch.object(tools, "_run", new=AsyncMock())
    result = await tools.verify_requirements(batch, checks)
    assert json.loads(result.content[0].text)["code"] == "invalid_verification"
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [{"verification_batch_id": "next"}, {"status": "verified"}])
async def test_verify_publishes_card_only_after_final_batch(mocker, context, result):
    verify = mocker.patch.object(tools.flow, "verify", new=AsyncMock(return_value=result))
    show = mocker.patch.object(tools, "show_resource_card", new=AsyncMock(return_value="card"))
    output = await tools.verify_requirements("batch", [{"requirement_id": "r1", "accepted": []}])
    assert verify.call_args.args[1] == "batch"
    assert verify.call_args.args[2][0].requirement_id == "r1"
    if "verification_batch_id" in result:
        assert json.loads(output.content[0].text) == result
        show.assert_not_awaited()
    else:
        assert output == "card"
        show.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("card", [None, {"subtype": "requirement_resources", "card_id": "card"}])
async def test_show_card_attaches_server_receipt_only_when_needed(mocker, context, card):
    mocker.patch.object(tools.flow, "show_card", new=AsyncMock(return_value=card))
    result = await tools.show_resource_card()
    assert json.loads(result.content[0].text) == {"status": "success", "card_required": card is not None}
    if card:
        receipt = result.meta[tools.NL2AGENT_RECEIPT_KEY]
        assert receipt["payload"] == card and receipt["run_id"] == "run"
        assert receipt["conversation_id"] == "7" and receipt["event_id"]
    else:
        assert not result.meta


@pytest.mark.asyncio
async def test_show_and_verify_propagate_authorization_error(mocker, context):
    context[2].side_effect = PermissionError()
    show = mocker.patch.object(tools.flow, "show_card", new=AsyncMock())
    for result in (await tools.show_resource_card(), await tools.verify_requirements(
        "batch", [{"requirement_id": "r1", "accepted": []}],
    )):
        assert json.loads(result.content[0].text)["code"] == "unauthorized"
        assert not result.meta
    show.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("goal,pending", [("prompt", None), ("complete", {"card_id": "pending"})])
async def test_generation_context_refreshes_basis_and_pending_prompt(mocker, context, goal, pending):
    from services import nl2agent_prompt_service as prompts

    read = mocker.patch.object(tools, "read_generation_state", new=AsyncMock(return_value={
        "draft_fields": {"prompt": "Original"}, "bound_resources": [], "binding_revision": "revision",
    }))
    refresh = mocker.patch.object(prompts, "refresh_basis", new=AsyncMock())
    mocker.patch.object(prompts, "read_pending", new=AsyncMock(return_value=pending))
    result = await tools.read_generation_context(goal)
    assert result["status"] == "success" and result["draft_fields"]["prompt"] == "Original"
    assert result.get("pending_prompt") == pending
    read.assert_awaited_once()
    assert {key: read.call_args.kwargs[key] for key in ("agent_id", "tenant_id", "user_id")} == {
        "agent_id": 42, "tenant_id": "tenant", "user_id": "user",
    }
    assert refresh.call_args.kwargs == {"complete_generation": goal == "complete"}


@pytest.mark.asyncio
async def test_unknown_generation_goal_is_rejected(mocker):
    dispatch = mocker.patch.object(tools, "_run", new=AsyncMock())
    assert (await tools.read_generation_context("unknown"))["code"] == "invalid_generation_goal"
    dispatch.assert_not_awaited()
