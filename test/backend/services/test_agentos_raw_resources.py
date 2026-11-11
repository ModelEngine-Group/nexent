# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep authorized knowledge and Workbench resources across raw AgentOS handoff."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.responses import StreamingResponse

from contracts.agent import AgentRequest
from contracts.agentos import CompatibilityConversationRun
from contracts.knowledge import ResolvedKnowledgeScope
from contracts.tool import ToolParamsRequest
from management.services.agent import raw_execution as service, runtime_client
from .test_agentos_raw_preparation import ACTOR, preparation


@pytest.mark.asyncio
@pytest.mark.parametrize("workbench", [False, True])
async def test_raw_exports_the_same_authorized_scope_and_mount_plan(preparation, mocker, workbench):
    request = AgentRequest(
        query="hello", agent_id=7, is_debug=True, knowledge_scope={"schema_version": 1},
        **({"entrypoint": "workbench", "workbench": {"mode": "generic_chat", "knowledge_scope": {"schema_version": 1}}}
           if workbench else {}),
    )
    overrides = {"draft": {"search": {"index_names": ["index-a"]}}}
    knowledge = ResolvedKnowledgeScope(
        desired_scope={"schema_version": 1}, tool_params=ToolParamsRequest(agents={}),
        local_knowledge_ids=["3"], local_index_names=["index-a"], managed_tool_overrides=overrides,
        warnings=[{"source": "local", "code": "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE"}],
    )
    plan = SimpleNamespace(child_mounts=[], root_skills=[])
    tools = [{"name": "search", "class_name": "KnowledgeBaseSearchTool"}]

    async def authorized(turn, user, tenant, language, timezone, *, export_resources=False):
        assert export_resources is True
        turn.tool_params = knowledge.tool_params
        turn.__dict__.update(_debug_run_id="debug-" + "9" * 32, _runtime_metadata_snapshot={})
        if workbench:
            turn.__dict__.update(_runtime_mount_plan=plan, _runtime_knowledge_tools=tools)
        return SimpleNamespace(
            created=False, workbench=turn.workbench, knowledge=knowledge,
            knowledge_tree=({"agent_id": 7, "version_no": 0, "agent_name": "draft"},),
        )

    preparation.original.side_effect = authorized
    result = await service.prepare_raw_debug(request, ACTOR)
    assert result is not None
    values = preparation.compile.await_args.kwargs
    assert values["tool_params"] == knowledge.tool_params
    assert result.knowledge is knowledge
    if workbench:
        scope = values["prepared_workbench"]
        assert scope.plan is plan and scope.config is request.workbench
        assert scope.knowledge is knowledge and scope.knowledge_tools == tools
        assert result.workbench is request.workbench
    else:
        assert values["authorized_knowledge_tools"] == {(7, 0): overrides["draft"]}
        assert result.payload.native_knowledge is True


@pytest.mark.asyncio
async def test_raw_workbench_uses_granted_debug_dispatch_and_retains_opening_events(preparation, mocker):
    from management.services.agent.preparation.evaluation_snapshot import PreparedDebug

    request = AgentRequest(query="hello", is_debug=True, entrypoint="workbench", workbench={"mode": "generic_chat"})
    knowledge = ResolvedKnowledgeScope(
        desired_scope={}, tool_params=ToolParamsRequest(), local_knowledge_ids=["3"],
        warnings=[{"source": "local", "code": "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE"}],
    )
    payload = SimpleNamespace(run_id="9" * 32)
    prepared = PreparedDebug(payload, knowledge, request.workbench)
    mocker.patch.object(service, "prepare_raw_debug", new=AsyncMock(return_value=prepared))

    async def events():
        yield b'data: {"type":"final_answer","content":"answer"}\n\n'

    granted = mocker.patch.object(runtime_client, "_run_prepared_debug", new=AsyncMock(return_value=StreamingResponse(events())))
    result = await service.forward_raw_run(CompatibilityConversationRun(
        request=request.model_dump(mode="json"), invocation="northbound",
    ), ACTOR)
    frames = [json.loads(frame[6:]) for frame in b"".join([item async for item in result.body_iterator]).split(b"\n\n") if frame]
    assert [frame["type"] for frame in frames] == ["workbench_config_resolved", "knowledge_scope_resolved", "final_answer"]
    assert frames[1]["content"]["warnings"] == knowledge.warnings
    granted.assert_awaited_once_with(preparation.client, prepared, ACTOR.user_id, ACTOR.tenant_id)
    preparation.client.run_ephemeral.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_workbench_disabled_keeps_original_feature_gate(preparation, mocker):
    from contracts.errors.exceptions import WorkbenchError
    from management.services.agent import subscription

    mocker.patch.object(subscription, "ENABLE_AGENT_WORKBENCH", False)
    mocker.patch.object(service, "_prepare_legacy_conversation", new=subscription._prepare_legacy_conversation)
    request = AgentRequest(query="hello", is_debug=True, entrypoint="workbench", workbench={"mode": "generic_chat"})
    with pytest.raises(WorkbenchError) as denied:
        await service.prepare_raw_debug(request, ACTOR)
    assert denied.value.code == "WORKBENCH_DISABLED" and denied.value.status_code == 404
    preparation.compile.assert_not_awaited()
