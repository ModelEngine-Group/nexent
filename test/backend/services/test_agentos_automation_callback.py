# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from contracts.agentos import AgentOperation, AgentRunLookup, AgentRunReference, ManagementOperation, ToolBinding
from infrastructure.agent_tool_config import AUTOMATION_PROPOSAL_TOOL
from infrastructure.agentos_identity import AgentOSIdentityError, ServicePrincipal, sign_call, verify_call
from management.services.automation import agentos_callback
from runtime.agentos.prepared_automation import materialize_automation_tool


ACTOR = ServicePrincipal("actor", "tenant")
REFERENCE = AgentRunReference(conversation_id=42, run_id="a" * 32)


def test_reverse_agentos_token_is_distinct_and_body_bound(monkeypatch):
    from contracts.constants import environment

    monkeypatch.setattr(environment, "JWT_SECRET", "synthetic-agentos-secret-for-callback")
    body = REFERENCE.model_dump_json().encode()
    operation = ManagementOperation.AUTOMATION_PROPOSAL
    reverse = sign_call(operation, body, ACTOR)
    assert verify_call(reverse, operation, body) == ACTOR
    forward = sign_call(AgentOperation.RUN, body, ACTOR)
    with pytest.raises(AgentOSIdentityError):
        verify_call(forward, operation, body)
    with pytest.raises(AgentOSIdentityError):
        verify_call(reverse, AgentOperation.RUN, body)
    with pytest.raises(AgentOSIdentityError):
        verify_call(reverse, operation, body + b" ")


@pytest.mark.asyncio
async def test_callback_confirms_owned_turn_and_uses_its_stored_message(mocker):
    turn = SimpleNamespace(assistant_message_id=None)
    context = agentos_callback.AutomationToolRuntimeContext(
        tenant_id="tenant", user_id="actor", conversation_id=42, agent_id=7, user_message="saved input",
        source_message_id=91,
    )

    async def inline(_name, fn, *args, lane, owner):
        return fn(*args)

    mocker.patch.object(agentos_callback, "run_blocking", side_effect=inline)
    mocker.patch.object(agentos_callback.store, "automation_turn", return_value=turn)
    confirm = mocker.patch.object(agentos_callback.store, "confirm_turn", return_value=turn)
    mocker.patch.object(agentos_callback, "_read_context", return_value=context)
    runtime = SimpleNamespace(inspect_run=AsyncMock(return_value=SimpleNamespace(
        **REFERENCE.model_dump(), status="running", cancellation_requested=False,
    )))
    mocker.patch.object(agentos_callback, "_agentos_client", return_value=runtime)
    create = mocker.patch.object(agentos_callback.agent_loop_automation_tool_adapter, "create_proposal",
                                 return_value={"status": "proposal_ready"})

    assert await agentos_callback.create_automation_proposal(REFERENCE, ACTOR) == {"status": "proposal_ready"}
    runtime.inspect_run.assert_awaited_once_with(AgentRunLookup(**REFERENCE.model_dump()), "actor", "tenant")
    confirm.assert_called_once_with(turn)
    create.assert_awaited_once_with(context, "")


@pytest.mark.asyncio
async def test_unbound_callback_never_reaches_runtime_or_creates_a_proposal(mocker):
    mocker.patch.object(agentos_callback, "run_blocking", return_value=None)
    client = mocker.patch.object(agentos_callback, "_agentos_client")
    create = mocker.patch.object(agentos_callback.agent_loop_automation_tool_adapter, "create_proposal")
    assert await agentos_callback.create_automation_proposal(REFERENCE, ACTOR) is None
    client.assert_not_called()
    create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "cancellation_requested"), [("completed", False), ("running", True)])
async def test_finished_or_cancelled_run_cannot_create_a_proposal(mocker, status, cancellation_requested):
    mocker.patch.object(agentos_callback, "run_blocking", return_value=SimpleNamespace(assistant_message_id=61))
    runtime = SimpleNamespace(inspect_run=AsyncMock(return_value=SimpleNamespace(
        **REFERENCE.model_dump(), status=status, cancellation_requested=cancellation_requested,
    )))
    mocker.patch.object(agentos_callback, "_agentos_client", return_value=runtime)
    create = mocker.patch.object(agentos_callback.agent_loop_automation_tool_adapter, "create_proposal")
    assert await agentos_callback.create_automation_proposal(REFERENCE, ACTOR) is None
    create.assert_not_awaited()


@pytest.mark.parametrize("change", [{"version": "2"}, {"parameters": {"query": "untrusted"}}, {"credential_ref": "key"}])
def test_runtime_rejects_unapproved_tool_parameters(change):
    binding = ToolBinding.model_validate({"tool_id": AUTOMATION_PROPOSAL_TOOL, "version": "1"} | change)
    with pytest.raises(ValueError, match="Unsupported"):
        materialize_automation_tool(SimpleNamespace(tools=[binding]), ACTOR, REFERENCE)


def test_runtime_rejects_proposal_tool_outside_the_public_root():
    binding = ToolBinding(tool_id=AUTOMATION_PROPOSAL_TOOL, version="1")
    with pytest.raises(ValueError, match="Unsupported"):
        materialize_automation_tool(SimpleNamespace(tools=[binding]), ACTOR, None)
