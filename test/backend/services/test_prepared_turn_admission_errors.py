# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Ensure staging and confirmation errors cannot leave an unowned public run."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError as RequestValidationError
from starlette.responses import Response

from contracts.agent import AgentRequest, WorkbenchSessionConfig
from contracts.agentos import AgentStop, ToolBinding
from contracts.conversation import MessageSource
from contracts.errors.exceptions import (
    ForbiddenError, RunModelControlsError, RuntimeServiceUnavailableError, RuntimeUpstreamError,
    ValidationError, WorkbenchConfigVersionConflict, WorkbenchError,
)
from management.services.agent import prepared_turn
from management.services.automation import confirmation
from test.backend.services.test_prepared_public_turn import ACTOR, PAYLOAD, REFERENCE, flow


@pytest.mark.parametrize("overrides", [
    {"agent_id": None}, {"agent_id": 0}, {"agent_id": -1},
    {"is_debug": True}, {"enable_automation_tool": False},
])
def test_automation_request_requires_an_interactive_agent_with_proposal_tool(overrides):
    request = {**PAYLOAD.request, "entrypoint": "automation", "enable_automation_tool": True, **overrides}

    with pytest.raises(RequestValidationError, match="automation entrypoint requires an interactive Agent"):
        AgentRequest.model_validate(request)


async def test_automation_turn_requires_compiled_proposal_binding_before_runtime_admission(flow, mocker):
    operations, compile_snapshot, runtime, _ = flow
    compile_snapshot.return_value.resource = SimpleNamespace(tools=[])
    reject = mocker.patch.object(prepared_turn, "set_conversation_admission")
    request = AgentRequest.model_validate({**PAYLOAD.request, "entrypoint": "automation", "enable_automation_tool": True})

    assert prepared_turn.is_prepared_candidate(PAYLOAD, request)
    with pytest.raises(HTTPException) as exc:
        await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, runtime)

    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "AUTOMATION_PROPOSAL_UNAVAILABLE"}
    assert operations == []
    reject.assert_called_once()
    assert reject.call_args.kwargs == {"conversation_id": None, "journal_available": False}
    runtime.start_prepared_run.assert_not_awaited()


@pytest.mark.parametrize("query, confirms", [("确认创建", True), ("创建好了吗？", False), ("改到九点再创建", False)])
async def test_owned_chat_confirmation_uses_dedicated_runtime_processing(flow, query, confirms):
    _, compile_snapshot, runtime, _ = flow
    compile_snapshot.return_value.resource = SimpleNamespace(
        agent_id=7, version_no=4, tools=[ToolBinding(tool_id=prepared_turn.AUTOMATION_PROPOSAL_TOOL, version="1")],
    )
    request = AgentRequest(query=query, conversation_id=42, agent_id=7, enable_automation_tool=True)

    await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, runtime)

    assert compile_snapshot.call_args.kwargs.get("automation_confirmation", False) is confirms
    staged = prepared_turn.store.stage_turn.call_args.args[5]
    assert staged["query"] == query
    assert staged["automation"].get("confirm_from_chat", False) is confirms


async def test_affirmation_stages_the_server_selected_proposal_for_callback(flow):
    _, compile_snapshot, runtime, _ = flow
    compile_snapshot.return_value.resource = SimpleNamespace(
        agent_id=7, version_no=4, tools=[ToolBinding(tool_id=prepared_turn.AUTOMATION_PROPOSAL_TOOL, version="1")],
    )
    confirmation.previous_automation_invitation.return_value = 71
    request = AgentRequest(query="好", conversation_id=42, agent_id=7)
    await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, runtime)
    assert compile_snapshot.call_args.kwargs["automation_confirmation"] is True
    automation_context = prepared_turn.store.stage_turn.call_args.args[5]["automation"]
    assert automation_context["confirmation_action"] == "confirm"
    assert automation_context["confirmation_proposal_id"] == 71


@pytest.mark.parametrize("error,status,code", [
    (ForbiddenError("no access"), 404, "AGENTOS_RUN_NOT_FOUND"),
    (prepared_turn.store.PreparedTurnConflict(), 409, "AGENTOS_RUN_ALREADY_ACTIVE"),
    (WorkbenchConfigVersionConflict(7, {}), 409, "WORKBENCH_CONFIG_VERSION_CONFLICT"),
    (WorkbenchError("WORKBENCH_DISABLED", status_code=404), 404, "WORKBENCH_DISABLED"),
    (RunModelControlsError("model_not_available"), 404, "model_not_available"),
    (RunModelControlsError("model_not_available", agent_id=48, agent_name="Chef", version_no=1),
     404, "model_not_available"),
    (RunModelControlsError("model_unavailable"), 409, "model_unavailable"),
    (RunModelControlsError("model_type_invalid"), 400, "model_type_invalid"),
    (RunModelControlsError("model_controls_invalid"), 422, "model_controls_invalid"),
    (ValidationError("invalid scope"), 422, None),
])
async def test_preparation_rejects_claim_before_runtime_admission(flow, mocker, error, status, code):
    _, compile_snapshot, runtime, _ = flow
    compile_snapshot.side_effect = error
    reject = mocker.patch.object(prepared_turn, "set_conversation_admission")
    request = AgentRequest.model_validate(PAYLOAD.request)

    with pytest.raises(HTTPException) as exc:
        await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, runtime)

    assert exc.value.status_code == status
    if isinstance(error, RunModelControlsError):
        assert exc.value.detail == error.to_detail()
    if code is not None:
        assert exc.value.detail["code"] == code
    else:
        assert exc.value.detail == "invalid scope"
    reject.assert_called_once()
    assert reject.call_args.kwargs == {"conversation_id": None, "journal_available": False}
    runtime.start_prepared_run.assert_not_awaited()


@pytest.mark.parametrize("error,status,code", [
    (prepared_turn.AdmissionScopeError(), 404, "AGENTOS_RUN_NOT_FOUND"),
    (WorkbenchConfigVersionConflict(4, {}), 409, "WORKBENCH_CONFIG_VERSION_CONFLICT"),
    (WorkbenchError("WORKBENCH_DISABLED", status_code=404), 404, "WORKBENCH_DISABLED"),
])
async def test_confirmation_rejects_and_fences_an_unbound_runtime(flow, error, status, code):
    _, _, runtime, staged = flow
    prepared_turn.store.confirm_turn.side_effect = error
    runtime.stop_run = AsyncMock(side_effect=RuntimeUpstreamError(404, b"", {}))
    with pytest.raises(HTTPException) as exc:
        await prepared_turn.start_turn(PAYLOAD, AgentRequest.model_validate(PAYLOAD.request), *ACTOR, runtime)
    assert (exc.value.status_code, exc.value.detail["code"]) == (status, code)
    runtime.stop_run.assert_awaited_once_with(AgentStop(**REFERENCE.model_dump(), prevent_start=True), *ACTOR)
    prepared_turn.store.close_turn.assert_called_once_with(staged)
    runtime.resume.assert_not_awaited()


async def test_missing_confirmation_never_presents_the_upstream_stream(flow):
    _, _, runtime, _ = flow
    prepared_turn.store.confirm_turn.side_effect = None
    prepared_turn.store.confirm_turn.return_value = None
    with pytest.raises(RuntimeServiceUnavailableError, match="no longer pending"):
        await prepared_turn.start_turn(PAYLOAD, AgentRequest.model_validate(PAYLOAD.request), *ACTOR, runtime)
    runtime.resume.assert_not_awaited()


async def test_authorized_workbench_stages_skill_root(flow, mocker):
    _, compile_snapshot, runtime, _ = flow
    config = WorkbenchSessionConfig(mode="generic_chat")
    plan = SimpleNamespace(config=config, version=3, previous_version=2, knowledge=None)
    mocker.patch.object(prepared_turn, "_prepare_workbench", return_value=plan)
    compile_snapshot.return_value.resource = SimpleNamespace(
        agent_id=7, version_no=4, workbench_skill_refs=[{"skill_id": 8}],
        tools=[ToolBinding(tool_id=prepared_turn.AUTOMATION_PROPOSAL_TOOL, version="1")],
    )
    compile_snapshot.return_value.models = SimpleNamespace(llm=SimpleNamespace(model_id=11))
    request = AgentRequest(
        query="question", conversation_id=42, entrypoint="workbench", workbench=config, enable_automation_tool=True,
    )
    response = await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, runtime)
    assert response.headers["X-Workbench-Config-Version"] == "3"
    turn = prepared_turn.store.stage_turn.call_args.args[5]
    assert turn["workbench_skill_root"] == {"agent_id": 7, "version_no": 4}
    assert turn["automation"]["model_id"] == 11
    assert turn["workbench_update"] == {"config": config.model_dump(mode="json"), "expected_version": 2, "version": 3}


async def test_native_admission_stages_model_and_original_automation_context(flow, mocker):
    _, compile_snapshot, runtime, _ = flow
    mocker.patch.object(prepared_turn.store, "allocate_conversation_id", return_value=42)
    compile_snapshot.return_value.resource = SimpleNamespace(
        agent_id=7, version_no=4, tools=[ToolBinding(tool_id=prepared_turn.AUTOMATION_PROPOSAL_TOOL, version="1")],
    )
    request = AgentRequest(
        query="question", agent_id=7, model_id=11, model_parameter_preferences={"11": {"temperature": 0}},
        minio_files=[{"name": "file.txt"}], enable_automation_tool=True,
    )
    await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, runtime)
    staging = prepared_turn.store.stage_turn.call_args
    assert staging.args[5]["automation"] == {
        "agent_id": 7, "agent_version_no": 4, "model_id": 11, "tool_params": None, "has_attachments": True,
    }
    assert staging.kwargs["selected_model_id"] == 11
    assert staging.kwargs["model_parameter_preferences"] == {"11": {"temperature": 0}}


@pytest.mark.parametrize("case", ["owned", "wrong-message", "missing"])
async def test_terminal_projection_only_closes_the_bound_assistant(flow, mocker, case):
    _, _, runtime, staged = flow
    turn = SimpleNamespace(**{**vars(staged), "assistant_message_id": 61, "memory_agent_id": 7,
                               "message_source": MessageSource.AUTOMATION})
    receipt = {"owned": (61, "completed"), "wrong-message": (62, "completed"), "missing": None}[case]
    lookup = mocker.patch.object(prepared_turn, "get_prepared_projection_receipt", return_value=receipt)
    project = mocker.patch.object(prepared_turn, "resume_assistant_projection")
    if case == "wrong-message":
        with pytest.raises(RuntimeServiceUnavailableError, match="does not match the reserved message"):
            await prepared_turn._finish_projection(turn, runtime)
        prepared_turn.store.close_turn.assert_not_called()
    else:
        await prepared_turn._finish_projection(turn, runtime)
        prepared_turn.store.close_turn.assert_called_once_with(turn)
    lookup.assert_called_once_with(
        projection_run_id=REFERENCE.run_id, conversation_id=42, message_index=9,
        message_source=MessageSource.AUTOMATION, user_id=ACTOR[0], tenant_id=ACTOR[1],
    )
    if case == "missing":
        project.assert_awaited_once_with(
            runtime.resume, REFERENCE, *ACTOR, message_index=9, message_source=MessageSource.AUTOMATION,
            assistant_message_id=61, memory_agent_id=7,
        )
    else:
        project.assert_not_awaited()
    if case == "wrong-message":
        runtime.acknowledge_projection.assert_not_awaited()
    else:
        runtime.acknowledge_projection.assert_awaited_once_with(REFERENCE, *ACTOR)


@pytest.mark.parametrize("requested", ["workbench", "native"])
async def test_existing_thread_cannot_switch_its_chat_entrypoint(flow, mocker, requested):
    _, compile_snapshot, runtime, _ = flow
    reject = mocker.patch.object(prepared_turn, "set_conversation_admission")
    prepared_turn.get_conversation.return_value = (
        {} if requested == "workbench" else {"workbench_config": {"mode": "generic_chat"}}
    )
    request = AgentRequest(
        query="question", conversation_id=42, agent_id=7, entrypoint=requested if requested == "workbench" else None,
        enable_automation_tool=False,
    )
    with pytest.raises(HTTPException) as exc:
        await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, runtime)
    assert exc.value.status_code == 403
    assert "different chat entrypoint" in exc.value.detail
    reject.assert_called_once()
    compile_snapshot.assert_not_awaited()
    runtime.start_prepared_run.assert_not_awaited()


@pytest.mark.parametrize("case", ["active-missing", "lookup-failed", "other-run", "no-assistant", "revoked", "bad-header", "other-response"])
async def test_legacy_resume_only_adapts_the_same_scoped_run(flow, mocker, case):
    _, _, runtime, _ = flow
    runtime.find_active_run.return_value = REFERENCE.run_id
    runtime.inspect_run = AsyncMock(return_value=SimpleNamespace(
        **REFERENCE.model_dump(), status="running", assistant_message_id=61,
    ))
    index = mocker.patch.object(prepared_turn.store, "read_legacy_resume_index", return_value=4)
    cleanup = AsyncMock()
    upstream = Response(status_code=451 if case == "other-response" else 200, background=cleanup,
                        headers={"X-AgentOS-Replay-Count": "invalid", "X-AgentOS-Run-ID": REFERENCE.run_id})
    runtime.resume.return_value = upstream
    if case == "active-missing":
        runtime.find_active_run.side_effect = RuntimeUpstreamError(404, b"", {})
    elif case == "lookup-failed":
        runtime.inspect_run.side_effect = RuntimeUpstreamError(502, b"", {})
    elif case == "other-run":
        runtime.inspect_run.return_value.run_id = "b" * 32
    elif case == "no-assistant":
        runtime.inspect_run.return_value.assistant_message_id = None
    elif case == "revoked":
        index.side_effect = prepared_turn.AdmissionScopeError

    if case in {"lookup-failed", "other-run", "revoked"}:
        failure = {"lookup-failed": RuntimeUpstreamError, "other-run": RuntimeServiceUnavailableError,
                   "revoked": HTTPException}[case]
        with pytest.raises(failure):
            await prepared_turn._resume_tracked_legacy(42, *ACTOR, runtime)
    else:
        result = await prepared_turn._resume_tracked_legacy(42, *ACTOR, runtime)
        assert result is (upstream if case == "other-response" else None)
    if case in {"bad-header", "other-response"}:
        runtime.resume.assert_awaited_once()
    else:
        runtime.resume.assert_not_awaited()
    assert cleanup.await_count == (case == "bad-header")


@pytest.mark.parametrize("error,status", [(prepared_turn.AdmissionScopeError, 403), (
    WorkbenchError("WORKBENCH_DISABLED", status_code=404), 404,
)])
async def test_cursorless_resume_preserves_permission_and_feature_errors(flow, mocker, error, status):
    _, _, runtime, _ = flow
    find = mocker.patch.object(prepared_turn.store, "read_cursorless_resume", side_effect=error)
    with pytest.raises(HTTPException) as exc:
        await prepared_turn.resume_cursorless(42, *ACTOR, runtime)
    assert exc.value.status_code == status
    find.assert_called_once_with(42, *ACTOR)
    runtime.resume.assert_not_awaited()


async def test_pending_lookup_does_not_disclose_unowned_turn(flow, mocker):
    lookup = mocker.patch.object(prepared_turn.store, "pending_turn", side_effect=prepared_turn.AdmissionScopeError)
    assert await prepared_turn.find_pending_turn(42, *ACTOR) is None
    lookup.assert_called_once_with(42, *ACTOR)


async def test_runtime_stop_failure_leaves_staged_turn_for_reconciliation(flow):
    _, _, runtime, staged = flow
    upstream = RuntimeUpstreamError(503, b"", {})
    runtime.stop_run = AsyncMock(side_effect=upstream)
    with pytest.raises(RuntimeUpstreamError) as exc:
        await prepared_turn._cancel_unbound_turn(runtime, staged)
    assert exc.value is upstream
    prepared_turn.store.close_turn.assert_not_called()
