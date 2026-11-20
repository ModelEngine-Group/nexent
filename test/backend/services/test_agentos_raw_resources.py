# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserve authorized knowledge and Workbench resources in debug handoff."""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from contracts.agent import AgentRequest
from contracts.agentos import CompatibilityConversationRun, PreparedEphemeralRun
from contracts.knowledge import ResolvedKnowledgeScope
from contracts.tool import ToolParamsRequest
from management.services.agent import runtime_client, workbench
from management.services.agent.preparation import evaluation_snapshot
from management.services.model import run_controls
from .test_agentos_raw_preparation import ACTOR, preparation


@pytest.mark.asyncio
@pytest.mark.parametrize("use_workbench", [False, True])
async def test_debug_exports_authorized_scope_and_mount_plan(preparation, mocker, use_workbench):
    overrides = {(7, 0): {"search": {"index_names": ["index-a"]}}}
    knowledge = ResolvedKnowledgeScope(
        desired_scope={"schema_version": 1}, tool_params=ToolParamsRequest(agents={}),
        local_knowledge_ids=["3"], local_index_names=["index-a"], local_display_names=["Docs"],
        warnings=[{"source": "local", "code": "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE"}],
    )
    tools = [{"name": "search", "class_name": "KnowledgeBaseSearchTool"}]
    request = AgentRequest(
        query="hello", agent_id=7, is_debug=True,
        **({"entrypoint": "workbench", "workbench": {"mode": "generic_chat", "knowledge_scope": {"schema_version": 1}}}
           if use_workbench else {"knowledge_scope": {"schema_version": 1}}),
    )
    if use_workbench:
        root = workbench.RuntimeAgentIdentity("agent:7:v0", 7, 0, "draft", "Draft", "SYSTEM")
        plan = workbench.ResolvedAgentPlan(
            workbench.PublishedRootDescriptor(root, {}), workbench.RootRuntimeOverlay(None, None, (), None), (),
        )
        mocker.patch.object(run_controls, "validate_agent_model_selection")
        mocker.patch.object(run_controls, "preflight_agent_turn_controls")
        resolve = mocker.patch.object(workbench, "resolve_workbench_config", return_value=(request.workbench, plan))
        authorize = mocker.patch.object(workbench, "resolve_workbench_knowledge", return_value=(knowledge, tools))
    else:
        authorize = mocker.patch.object(
            evaluation_snapshot, "prepare_native_knowledge",
            return_value=evaluation_snapshot.PreparedNativeKnowledge(knowledge, 0, overrides),
        )

    result = await evaluation_snapshot.prepare_debug_snapshot(
        request, ACTOR.user_id, ACTOR.tenant_id, language="zh", timezone=None,
    )

    values = preparation.compile.await_args.kwargs
    assert values["tool_params"] is knowledge.tool_params
    assert values["runtime_knowledge_context"]["scope"]["local_display_names"] == ["Docs"]
    assert result.knowledge is knowledge
    if use_workbench:
        scope = values["prepared_workbench"]
        assert scope.plan is plan and scope.config is request.workbench
        assert scope.knowledge is knowledge and scope.knowledge_tools == tools
        assert result.workbench is request.workbench
        resolve.assert_called_once_with(request.workbench, tenant_id="tenant", is_debug=True, user_id="user")
        authorize.assert_called_once()
        assert authorize.call_args.args[0:2] == (request.workbench, plan)
        assert authorize.call_args.args[-2:] == ("user", "tenant")
    else:
        assert values["authorized_knowledge_tools"] == overrides
        assert result.payload.native_knowledge is True
        authorize.assert_called_once_with(request.model_copy(update={"version_no": 0}), None, "user", "tenant")


@pytest.mark.asyncio
async def test_workbench_debug_uses_grant_dispatch_and_presents_opening_events(preparation, mocker):
    request = AgentRequest(query="hello", is_debug=True, entrypoint="workbench", workbench={"mode": "generic_chat"})
    knowledge = ResolvedKnowledgeScope(
        desired_scope={}, tool_params=ToolParamsRequest(), local_knowledge_ids=["3"],
        warnings=[{"source": "local", "code": "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE"}],
    )
    snapshot = preparation.compile.return_value
    prepared = evaluation_snapshot.PreparedDebug(
        PreparedEphemeralRun(**snapshot.model_dump(exclude={"conversation_id"}), run_id="9" * 32),
        knowledge, request.workbench,
    )
    mocker.patch.object(runtime_client, "ENABLE_AGENT_WORKBENCH", True)
    mocker.patch.object(evaluation_snapshot, "prepare_debug_snapshot", new=AsyncMock(return_value=prepared))

    async def events():
        yield b'data: {"type":"final_answer","content":"answer"}\n\n'

    granted = mocker.patch.object(runtime_client, "_run_prepared_debug", new=AsyncMock(return_value=StreamingResponse(events())))
    result = await runtime_client.forward_conversation_run(
        CompatibilityConversationRun(request=request.model_dump(mode="json")), ACTOR.user_id, ACTOR.tenant_id,
    )

    frames = [json.loads(frame.removeprefix(b"data: ")) async for frame in result.body_iterator]
    assert [frame["type"] for frame in frames] == ["workbench_config_resolved", "knowledge_scope_resolved", "final_answer"]
    assert frames[1]["content"]["warnings"] == knowledge.warnings
    granted.assert_awaited_once_with(preparation.client, prepared, ACTOR.user_id, ACTOR.tenant_id)
    preparation.client.run_ephemeral.assert_not_awaited()


@pytest.mark.asyncio
async def test_workbench_debug_disabled_rejects_before_preparation(preparation, mocker):
    mocker.patch.object(runtime_client, "ENABLE_AGENT_WORKBENCH", False)
    request = AgentRequest(query="hello", is_debug=True, entrypoint="workbench", workbench={"mode": "generic_chat"})
    with pytest.raises(HTTPException) as denied:
        await runtime_client.forward_conversation_run(
            CompatibilityConversationRun(request=request.model_dump(mode="json")), ACTOR.user_id, ACTOR.tenant_id,
        )
    assert denied.value.status_code == 404 and denied.value.detail == {"code": "WORKBENCH_DISABLED"}
    preparation.compile.assert_not_awaited()
    preparation.client.run_ephemeral.assert_not_awaited()
