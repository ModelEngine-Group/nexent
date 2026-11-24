# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Cover Workbench policy and the authorized inputs sent to Runtime."""

import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.responses import StreamingResponse

from contracts.agent import AgentRequest, WorkbenchSessionConfig
from contracts.agentos import CompatibilityConversationRun
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.knowledge import ResolvedKnowledgeScope
from contracts.tool import ToolParamsRequest
from infrastructure.agent_tool_config import AUTOMATION_PROPOSAL_TOOL
from management.api.agent import conversation_run
from management.services.agent import conversation_submission, prepared_turn, runtime_client, workbench
from management.services.agent.preparation import evaluation_snapshot
from management.services.knowledge_base import mount, scope
from management.services.model import run_controls

from .test_agentos_raw_preparation import preparation
from .test_prepared_public_turn import ACTOR, PAYLOAD, REFERENCE, flow


@pytest.fixture
def plan():
    root = workbench.RuntimeAgentIdentity("agent:7:v2", 7, 2, "workbench_main", "Workbench", "SYSTEM")
    child = workbench.RuntimeAgentIdentity("agent:8:v5", 8, 5, "writer", "Writer", "PERSISTED")
    skill = workbench.ResolvedSkillMount(9, "skill-a", "A skill", (), {}, files=(("SKILL.md", b"# Skill"),))
    return workbench.ResolvedAgentPlan(
        workbench.PublishedRootDescriptor(root, {}), workbench.RootRuntimeOverlay(None, None, (), None),
        (skill,), child_mounts=(child,),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("debug,settings", [(False, {}), (False, {"11": {"temperature": 0}}), (True, {"11": {"temperature": 0}})])
async def test_workbench_compiler_receives_authorized_resources_and_pins_parameters(preparation, plan, mocker, debug, settings):
    config = WorkbenchSessionConfig(
        mode="single_agent_chat", agent_mounts=[{"agent_id": 8, "version_no": 5}],
        knowledge_scope={"local": {"mode": "disabled"}}, requested_output_tokens=2048,
    )
    request = AgentRequest(query="hello", entrypoint="workbench", workbench=config, model_id=11, is_debug=debug)
    tools = [{"name": "knowledge_search"}]
    knowledge = ResolvedKnowledgeScope(
        desired_scope=config.knowledge_scope.model_dump(mode="json"), local_disabled=True, tool_params=ToolParamsRequest(),
    )
    mocker.patch.object(workbench, "ENABLE_AGENT_WORKBENCH", True)
    resolve = mocker.patch.object(workbench, "resolve_workbench_config", return_value=(config, plan))
    mocker.patch.object(run_controls, "validate_agent_model_selection")
    mocker.patch.object(run_controls, "preflight_agent_turn_controls")
    tree = mocker.patch.object(scope, "snapshot_runtime_knowledge_tree", return_value=[
        {"agent_id": 7, "tools": []}, {"agent_id": 8, "tools": [{"name": "child"}]},
    ])
    records = mocker.patch.object(mount, "mount_knowledge_records", return_value=tools)
    authorize = mocker.patch.object(scope, "resolve_knowledge_scope", return_value=knowledge)

    if debug:
        request.model_parameter_preferences = settings
        result = await evaluation_snapshot.prepare_debug_snapshot(request, *ACTOR, language="en", timezone=None)
        assert result.workbench == config and result.knowledge is knowledge
        resolve.assert_called_once_with(config, tenant_id=ACTOR[1], user_id=ACTOR[0], is_debug=True)
    else:
        request.conversation_id = REFERENCE.conversation_id
        mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=False)
        portable = workbench.prepare_portable_workbench(request, None, *ACTOR)
        await evaluation_snapshot.prepare_conversation_snapshot(
            request, REFERENCE, *ACTOR, workbench=portable, new_conversation=True,
            owned_conversation={"model_parameter_preferences": settings},
        )
        resolve.assert_called_once_with(config, tenant_id=ACTOR[1], user_id=ACTOR[0])
    tree.assert_called_once_with(7, ACTOR[1], 2)
    records.assert_called_once_with([], config.knowledge_scope, ACTOR[1])
    assert authorize.call_args.kwargs["runtime_agent_tree"] == [{"agent_id": 7, "tools": tools}]
    kwargs = preparation.compile.await_args.kwargs
    assert kwargs["prepared_workbench"].plan is plan
    assert kwargs["runtime_sub_agent_mounts"] == [asdict(plan.child_mounts[0])]
    assert kwargs["runtime_skill_snapshot"] == [{
        "skill_id": 9, "name": "skill-a", "description": "A skill", "tool_ids": [],
        "config_values": {}, "tool_definitions": [], "files": [("SKILL.md", b"# Skill")],
    }]
    assert kwargs["runtime_knowledge_tools"] == tools
    assert kwargs["runtime_knowledge_context"]["scope"]["local_disabled"] is True
    assert kwargs["tool_params"] is knowledge.tool_params
    assert kwargs["override_version_no"] == 2 and kwargs["override_model_id"] == 11
    assert kwargs["requested_output_tokens"] == 2048
    assert kwargs["model_parameter_preferences"] == settings


@pytest.fixture
def existing_workbench(flow, plan, mocker):
    operations, compile_snapshot, client, staged = flow
    stored = WorkbenchSessionConfig(mode="single_agent_chat", agent_mounts=[{"agent_id": 8}])
    canonical = WorkbenchSessionConfig(mode="single_agent_chat", agent_mounts=[{"agent_id": 8, "version_no": 5}])
    conversation = {
        "conversation_id": REFERENCE.conversation_id, "workbench_config": stored.model_dump(mode="json"),
        "workbench_config_version": 2, "runtime_metadata": {"existing": True}, "runtime_metadata_version": 4,
    }
    prepared_turn.get_conversation.return_value = conversation
    compile_snapshot.return_value.resource = SimpleNamespace(agent_id=7, version_no=2, tools=[], workbench_skill_refs=[])
    compile_snapshot.return_value.runtime_metadata_version = 4
    mocker.patch.object(workbench, "ENABLE_AGENT_WORKBENCH", True)
    mocker.patch.object(runtime_client, "ENABLE_AGENT_WORKBENCH", True)
    resolve = mocker.patch.object(workbench, "resolve_workbench_config", return_value=(canonical, plan))
    reject = mocker.patch.object(prepared_turn, "reject_unstaged_turn")
    return SimpleNamespace(**locals())


@pytest.mark.asyncio
async def test_existing_workbench_returns_the_confirmed_config_and_metadata_version(existing_workbench):
    state = existing_workbench
    request = AgentRequest.model_validate({**PAYLOAD.request, "entrypoint": "workbench", "expected_workbench_config_version": 2})
    response = await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, state.client)
    chunks = [chunk async for chunk in response.body_iterator]

    state.resolve.assert_called_once_with(state.stored, tenant_id=ACTOR[1], user_id=ACTOR[0])
    assert state.operations == ["stage", "start", "confirm"]
    turn = prepared_turn.store.stage_turn.call_args.args[5]
    assert turn["workbench_update"] == {"config": state.canonical.model_dump(mode="json"), "expected_version": 2, "version": 3}
    assert "metadata_update" not in turn
    assert response.headers["x-runtime-metadata-version"] == "4"
    assert response.headers["x-workbench-config-version"] == "3"
    assert any(json.loads(chunk[6:])["type"] == "workbench_config_resolved" for chunk in chunks if chunk.startswith(b'data: {'))


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", [11, None])
async def test_workbench_send_stages_automation_with_request_model(existing_workbench, mocker, model_id):
    state = existing_workbench
    snapshot = state.compile_snapshot.return_value
    snapshot.resource.tools = [SimpleNamespace(tool_id=AUTOMATION_PROPOSAL_TOOL)]
    snapshot.models = SimpleNamespace(llm=SimpleNamespace(model_id=22))
    mocker.patch.object(run_controls, "get_model_by_model_id", return_value={"model_type": "llm"})
    mocker.patch.object(conversation_run, "get_current_user_id", return_value=ACTOR)
    mocker.patch.object(runtime_client, "_agentos_client", return_value=state.client)

    async def submit(payload, user_id, tenant_id, dispatch, **_options):
        claimed = payload.model_copy(update={"claimed_run_id": REFERENCE.run_id})
        return await dispatch(claimed, user_id, tenant_id)

    mocker.patch.object(conversation_submission, "submit_conversation", side_effect=submit)
    request = {
        **PAYLOAD.request, "entrypoint": "workbench", "expected_workbench_config_version": 2,
        "enable_automation_tool": True,
    }
    if model_id is not None:
        request["model_id"] = model_id

    app = FastAPI()
    app.include_router(conversation_run.router, prefix="/api")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://management") as http:
        response = await http.post("/api/agent/run", json=request, headers={"Idempotency-Key": "once"})

    assert response.status_code == 200
    assert state.operations == ["stage", "start", "confirm"]
    assert prepared_turn.store.stage_turn.call_args.args[5]["automation"] == {
        "agent_id": 7, "agent_version_no": 2, "model_id": model_id, "tool_params": None, "has_attachments": False,
    }
    state.client.start_prepared_run.assert_awaited_once_with(snapshot, *ACTOR)
    state.reject.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_workbench_rejects_without_a_submission(mocker):
    mocker.patch.object(runtime_client, "ENABLE_AGENT_WORKBENCH", False)
    submit = mocker.patch.object(conversation_submission, "submit_conversation")
    payload = CompatibilityConversationRun(request={**PAYLOAD.request, "entrypoint": "workbench"})

    with pytest.raises(HTTPException) as error:
        await runtime_client.forward_conversation_run(payload, *ACTOR)

    assert (error.value.status_code, error.value.detail) == (404, {"code": "WORKBENCH_DISABLED"})
    submit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_workbench", [False, True])
async def test_native_and_workbench_entrypoints_cannot_access_other_conversations(existing_workbench, stored_workbench):
    state = existing_workbench
    if not stored_workbench:
        del state.conversation["workbench_config"]
    request = AgentRequest.model_validate({**PAYLOAD.request, "entrypoint": None if stored_workbench else "workbench"})

    with pytest.raises(HTTPException) as error:
        await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, state.client)

    assert error.value.status_code == 403
    assert error.value.detail == "Conversation belongs to a different chat entrypoint"
    state.resolve.assert_not_called()
    state.client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_workbench_stale_metadata_rejects_before_compilation(existing_workbench):
    state = existing_workbench
    request = AgentRequest.model_validate({
        **PAYLOAD.request, "entrypoint": "workbench", "expected_workbench_config_version": 2,
        "metadata": {"ticket": "NEX-1"}, "expected_metadata_version": 3,
    })
    with pytest.raises(AppException) as error:
        await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, state.client)

    assert error.value.error_code == ErrorCode.CHAT_METADATA_VERSION_CONFLICT
    assert error.value.details == {"current_version": 4}
    state.reject.assert_awaited_once_with(PAYLOAD, *ACTOR)
    state.compile_snapshot.assert_not_awaited()
    state.client.start_prepared_run.assert_not_awaited()
