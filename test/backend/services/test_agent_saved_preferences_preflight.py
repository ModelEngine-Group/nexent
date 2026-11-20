# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Existing Agent turns restore saved controls before model selection."""

import pytest
from pydantic import ValidationError

from contracts.agent import AgentRequest
from contracts.agentos import AgentRunReference, CompatibilityConversationRun
from contracts.errors.exceptions import RunModelControlsError
from management.services.agent import runtime_client
from management.services.agent.preparation import evaluation_snapshot, run
from management.services.model import run_controls


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [None, 77])
async def test_saved_controls_precede_model_selection(mocker, explicit):
    request = AgentRequest(agent_id=7, query="fixture", conversation_id=11, model_id=explicit)
    reference = AgentRunReference(conversation_id=11, run_id="a" * 32)
    preferences = {"42": {"temperature": 0, "enable_thinking": False}}
    mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=False)
    ownership = mocker.patch.object(evaluation_snapshot, "get_conversation", return_value={
        "selected_model_id": 42, "model_parameter_preferences": preferences,
    })
    endpoint = mocker.patch.object(run, "create_agent_run_info")
    selection = mocker.patch.object(
        run_controls, "validate_agent_model_selection", side_effect=RunModelControlsError("model_controls_invalid"),
    )

    with pytest.raises(RunModelControlsError):
        await evaluation_snapshot.prepare_conversation_snapshot(request, reference, "owner", "tenant")

    ownership.assert_called_once_with(11, user_id="owner", tenant_id="tenant")
    selection.assert_called_once()
    selected, tenant, _ = selection.call_args.args
    assert tenant == "tenant"
    assert selected.model_id == (42 if explicit is None else explicit)
    assert selected._runtime_model_parameter_preferences == preferences
    assert request.model_id == explicit
    endpoint.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_conversation_rejects_unsaved_preference_drafts_before_dispatch(mocker):
    request = AgentRequest(agent_id=7, query="fixture", conversation_id=11)
    request.model_parameter_preferences["42"] = {"temperature": 0.4}
    command = CompatibilityConversationRun(request=request.model_dump(mode="json"))
    client = mocker.patch.object(runtime_client, "_agentos_client")

    with pytest.raises(ValidationError, match="Save existing conversation parameters"):
        await runtime_client.forward_conversation_run(command, "owner", "tenant")

    client.assert_not_called()
