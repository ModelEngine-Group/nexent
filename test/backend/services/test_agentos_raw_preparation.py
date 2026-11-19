# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Check debug request preparation and the Management-to-AgentOS boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.responses import StreamingResponse

from contracts.agent import AgentRequest
from contracts.agentos import CompatibilityConversationRun, PreparedEvaluationRun
from contracts.errors.exceptions import ValidationError
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent import authorization, runtime_client
from management.services.agent.preparation import evaluation_snapshot, run
from management.services.model import run_controls

ACTOR = ServicePrincipal("user", "tenant")


@pytest.fixture
def preparation(mocker):
    snapshot = PreparedEvaluationRun.model_validate({
        "mode": "nexent", "input": {"query": "prefixed"},
        "resource": {"agent_id": 7, "version_no": 0, "name": "draft", "description": "test",
                     "prompt_templates": {"system_prompt": "Answer"}, "tools": []},
        "models": {"llm": {"model_id": 11, "alias": "llm", "revision": "v1"}},
    })
    authorize = mocker.patch.object(authorization, "authorize_debug_version", return_value={"agent_id": 7})
    model_controls = mocker.patch.object(run_controls, "preflight_turn_controls")
    compile_run = mocker.patch.object(run, "create_agent_run_info", new=AsyncMock(return_value=snapshot))
    client = SimpleNamespace(run_ephemeral=AsyncMock(
        return_value=StreamingResponse(iter([]), headers={"Connection": "keep-alive"}),
    ))
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)
    return SimpleNamespace(
        authorize=authorize, model_controls=model_controls, compile=compile_run, client=client,
    )


@pytest.mark.asyncio
async def test_debug_compiles_authorized_draft_with_request_controls(preparation, mocker):
    policy = mocker.patch(
        "management.db.agent.repository.search_agent_info_by_agent_id",
        return_value={"allow_chat_metadata": True},
    )
    prefix = mocker.patch.object(evaluation_snapshot, "prepend_current_time", return_value="prefixed")
    request = AgentRequest(
        query="hello", agent_id=7, is_debug=True, conversation_id=42, model_id=11, enable_plan=True,
        model_parameter_preferences={"11": {"temperature": 0.3, "reasoning_effort": "high"}},
        requested_output_tokens=1024, tool_params={"agents": {"root": {"tools": {"search": {"top_k": 5}}}}},
        metadata={"tag": "original"},
    )
    result = await evaluation_snapshot.prepare_debug_snapshot(
        request, ACTOR.user_id, ACTOR.tenant_id, language="zh", timezone=None,
    )
    assert len(result.payload.run_id) == 32 and result.payload.debug is True
    assert result.payload.runtime_metadata == {"tag": "original"}
    assert result.payload.resource.version_no == 0
    values = preparation.compile.await_args.kwargs
    assert values["query"] == "prefixed" and values["language"] == "zh"
    assert (values["override_model_id"], values["override_version_no"]) == (11, 0)
    assert values["requested_output_tokens"] == 1024
    assert values["model_parameter_preferences"] == request.model_parameter_preferences
    assert values["tool_params"] == request.tool_params
    assert values["allow_memory_search"] is False and values["export_debug_planning"] is True
    assert values["enable_automation_tool"] is False
    prefix.assert_called_once_with("hello", None, language="zh")
    preparation.authorize.assert_called_once_with(7, 0, "user", "tenant")
    preparation.model_controls.assert_called_once_with(request, "tenant", {"agent_id": 7})
    policy.assert_called_once_with(7, "tenant", 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("is_debug", [True, False])
async def test_unprepared_conversation_rejects_without_dispatch(preparation, mocker, is_debug):
    from management.services.agent import conversation_submission, prepared_turn

    async def submit(payload, owner, tenant, dispatch, **_options):
        return await dispatch(payload, owner, tenant)

    mocker.patch.object(conversation_submission, "submit_conversation", side_effect=submit)
    start_turn = mocker.patch.object(prepared_turn, "start_turn", return_value=None)
    preparation.compile.return_value = None
    payload = CompatibilityConversationRun(request={"query": "hello", "agent_id": 7, "is_debug": is_debug})
    with pytest.raises(ValidationError, match="Agent resources could not be prepared"):
        await runtime_client.forward_conversation_run(payload, ACTOR.user_id, ACTOR.tenant_id)
    assert payload.request["query"] == "hello"
    preparation.client.run_ephemeral.assert_not_awaited()
    assert preparation.compile.await_count == int(is_debug)
    assert start_turn.await_count == int(not is_debug)


@pytest.mark.asyncio
async def test_correlated_debug_preserves_response_headers(preparation):
    payload = CompatibilityConversationRun(
        request={"query": "hello", "agent_id": 7, "is_debug": True, "conversation_id": 42},
    )
    response = await runtime_client.forward_conversation_run(payload, ACTOR.user_id, ACTOR.tenant_id)
    assert response.headers["conversation_id"] == "42" and response.headers["Connection"] == "keep-alive"
    snapshot, user, tenant = preparation.client.run_ephemeral.await_args.args
    assert len(snapshot.run_id) == 32
    assert (user, tenant) == ("user", "tenant")
    assert "conversation_id" not in snapshot.model_dump()
