# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep internal debug policy and configuration when exporting AgentOS resources."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.responses import StreamingResponse

from contracts.agent import AgentRequest
from contracts.agentos import CompatibilityConversationRun, PreparedEvaluationRun
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent import raw_execution as service, runtime_client

ACTOR = ServicePrincipal("user", "tenant")


@pytest.fixture
def preparation(mocker):
    snapshot = PreparedEvaluationRun.model_validate({
        "mode": "nexent", "input": {"query": "prefixed"},
        "resource": {"agent_id": 7, "version_no": 0, "name": "draft", "description": "test",
                     "prompt_templates": {"system_prompt": "Answer"}, "tools": []},
        "models": {"llm": {"model_id": 11, "alias": "llm", "revision": "v1"}},
    })

    async def preflight(request, user, tenant, language, timezone, *, export_resources=False):
        assert (user, tenant, language, timezone) == (ACTOR.user_id, ACTOR.tenant_id, "zh", None)
        assert export_resources is True
        request.query = "prefixed"
        request.__dict__.update(_debug_run_id="debug-" + "9" * 32, _runtime_metadata_snapshot={"tag": "original"})
        return SimpleNamespace(created=False, workbench=None, knowledge=None, knowledge_tree=())

    original = mocker.patch.object(service, "_prepare_legacy_conversation", side_effect=preflight)
    compile_run = mocker.patch.object(service, "create_agent_run_info", new=AsyncMock(return_value=snapshot))
    client = SimpleNamespace(run_ephemeral=AsyncMock(return_value=StreamingResponse(iter([]))), run_conversation=AsyncMock())
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)
    return SimpleNamespace(snapshot=snapshot, original=original, compile=compile_run, client=client)


@pytest.mark.asyncio
async def test_raw_export_reuses_original_preparation_and_exact_run_arguments(preparation):
    request = AgentRequest(
        query="hello", agent_id=7, is_debug=True, conversation_id=42, model_id=11, enable_plan=True,
        generation_config={"temperature": 0.3}, reasoning_effort="high", reasoning_budget_tokens=4096,
        requested_output_tokens=1024, tool_params={"agents": {"root": {"tools": {"search": {"top_k": 5}}}}},
    )
    result = await service.prepare_raw_debug(request, ACTOR)
    assert result.payload.run_id == "9" * 32 and result.payload.debug is True
    assert result.payload.runtime_metadata == {"tag": "original"}
    assert result.payload.resource.version_no == 0
    values = preparation.compile.await_args.kwargs
    assert values["query"] == "prefixed" and values["conversation_id"] == 0
    assert (values["override_model_id"], values["override_version_no"]) == (11, None)
    assert (values["reasoning_effort"], values["reasoning_budget_tokens"], values["requested_output_tokens"]) == ("high", 4096, 1024)
    assert values["runtime_generation_config"] == {"temperature": 0.3}
    assert values["tool_params"] == request.tool_params
    assert values["allow_memory_search"] is False and values["export_debug_planning"] is True
    assert "enable_automation_tool" not in values
    preparation.original.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("unsupported", ["nondebug", "export"])
async def test_raw_unsupported_keeps_original_payload_in_explicit_fallback(preparation, unsupported):
    request = {"query": "hello", "agent_id": 7, "is_debug": True}
    if unsupported == "nondebug":
        request["is_debug"] = False
    else:
        preparation.compile.return_value = None
    payload = CompatibilityConversationRun(request=request, invocation="northbound")
    preparation.client.run_conversation.return_value = StreamingResponse(iter([]))
    response = await service.forward_raw_run(payload, ACTOR)
    assert response is preparation.client.run_conversation.return_value
    preparation.client.run_conversation.assert_awaited_once_with(
        payload.model_copy(update={"preparation": "legacy"}), "user", "tenant",
    )
    assert payload.request["query"] == "hello"
    preparation.client.run_ephemeral.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_correlated_debug_preserves_response_headers(preparation):
    payload = CompatibilityConversationRun(
        request={"query": "hello", "agent_id": 7, "is_debug": True, "conversation_id": 42}, invocation="northbound",
    )
    response = await service.forward_raw_run(payload, ACTOR)
    assert response.headers["conversation_id"] == "42" and response.headers["Connection"] == "keep-alive"
    snapshot, user, tenant = preparation.client.run_ephemeral.await_args.args
    assert (snapshot.run_id, user, tenant) == ("9" * 32, "user", "tenant")
    preparation.client.run_conversation.assert_not_awaited()
