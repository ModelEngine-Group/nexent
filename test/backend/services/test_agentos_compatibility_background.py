# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Recover fixed-ID background execution without requiring an automation row."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from contracts.agentos import AgentRunReference, BackgroundRun
from contracts.errors.exceptions import AgentBackgroundError
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.agent_admission import AdmissionClaim
from management.services.agent import background_compatibility as service

ACTOR = ServicePrincipal("actor", "tenant")
REFERENCE = AgentRunReference(conversation_id=42, run_id="a" * 32)
PAYLOAD = BackgroundRun(run_id=REFERENCE.run_id, request={"conversation_id": 42, "agent_id": 7, "query": "hello"})


@pytest.fixture
def flow(mocker):
    async def inline(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    mocker.patch.object(service, "_io", side_effect=inline)
    claim = mocker.patch.object(service, "claim_conversation_run", return_value=AdmissionClaim(
        REFERENCE.run_id, "pending", None, False, True,
    ))
    snapshot = SimpleNamespace(memory_enabled=True, resource=SimpleNamespace(agent_id=7))
    preparation = mocker.patch.object(service, "_prepare", return_value=(snapshot, {"query": "hello"}))
    staged = SimpleNamespace(reference=REFERENCE, user_id="actor", tenant_id="tenant", message_index=1,
                             assistant_message_id=None, memory_agent_id=7)
    confirmed = SimpleNamespace(**{**vars(staged), "assistant_message_id": 61})
    stage = mocker.patch.object(service.store, "stage_turn", return_value=staged)
    confirm = mocker.patch.object(service.store, "confirm_turn", return_value=confirmed)
    read = mocker.patch.object(service.store, "read_background_turn", return_value=staged)
    close = mocker.patch.object(service.store, "close_turn")
    reject = mocker.patch.object(service, "set_conversation_admission")
    receipt = mocker.patch.object(service, "get_prepared_projection_receipt", return_value=None)
    project = mocker.patch.object(service, "resume_assistant_projection", return_value=SimpleNamespace(
        status="completed", assistant_message_id=61, chunks=2,
    ))
    client = SimpleNamespace(start_prepared_run=AsyncMock(return_value=REFERENCE), inspect_run=AsyncMock(
        return_value=SimpleNamespace(**REFERENCE.model_dump(), status="running", latest_event_id=REFERENCE.run_id + ":1"),
    ), resume=AsyncMock())
    return SimpleNamespace(**locals())


@pytest.mark.asyncio
async def test_unknown_background_stages_before_start_and_projects_only_the_assistant(flow):
    async def start(snapshot, user, tenant):
        flow.stage.assert_called_once()
        flow.confirm.assert_not_called()
        assert (snapshot, user, tenant) == (flow.snapshot, "actor", "tenant")
        return REFERENCE

    flow.client.start_prepared_run.side_effect = start
    result = await service.run_background(flow.client, PAYLOAD, ACTOR)
    assert result.run_id == REFERENCE.run_id and result.assistant_message_id == 61 and result.chunks == 2
    assert flow.claim.call_args.kwargs == {"requested_run_id": REFERENCE.run_id}
    assert flow.stage.call_args.kwargs == {"omitted_user": True, "background_run": True}
    flow.confirm.assert_called_once_with(flow.staged)
    assert flow.project.await_args.kwargs["message_source"] == "AUTOMATION"
    flow.close.assert_called_once_with(flow.confirmed)


@pytest.mark.asyncio
async def test_retry_recovers_unknown_ack_without_compiling_or_starting_again(flow):
    flow.claim.return_value = AdmissionClaim(REFERENCE.run_id, "pending", 42, True, False)
    result = await service.run_background(flow.client, PAYLOAD, ACTOR)
    assert result.assistant_message_id == 61
    flow.preparation.assert_not_awaited()
    flow.stage.assert_not_called()
    flow.client.start_prepared_run.assert_not_awaited()
    flow.client.inspect_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_unobserved_runtime_admission_cannot_trigger_a_second_start(flow):
    flow.claim.return_value = AdmissionClaim(REFERENCE.run_id, "pending", 42, True, False)
    flow.client.inspect_run.return_value.status = "starting"
    flow.client.inspect_run.return_value.latest_event_id = None
    with pytest.raises(AgentBackgroundError) as pending:
        await service.run_background(flow.client, PAYLOAD, ACTOR)
    assert pending.value.status_code == 409
    flow.confirm.assert_not_called()
    flow.client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_unsupported_export_rejects_only_the_unstaged_claim(flow):
    flow.preparation.return_value = None
    assert await service.run_background(flow.client, PAYLOAD, ACTOR) is None
    flow.reject.assert_called_once()
    flow.stage.assert_not_called()
    flow.client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_lost_start_response_keeps_the_staged_projection_for_recovery(flow):
    from contracts.errors.exceptions import RuntimeServiceUnavailableError

    flow.client.start_prepared_run.side_effect = RuntimeServiceUnavailableError("unknown acknowledgement")
    with pytest.raises(RuntimeServiceUnavailableError):
        await service.run_background(flow.client, PAYLOAD, ACTOR)
    flow.confirm.assert_not_called()
    flow.close.assert_not_called()
    flow.reject.assert_not_called()


@pytest.mark.asyncio
async def test_definitive_runtime_rejection_releases_only_the_staged_marker(flow):
    from contracts.errors.exceptions import RuntimeUpstreamError

    flow.client.start_prepared_run.side_effect = RuntimeUpstreamError(409, b"conflict", {})
    with pytest.raises(RuntimeUpstreamError):
        await service.run_background(flow.client, PAYLOAD, ACTOR)
    flow.close.assert_called_once_with(flow.staged)
    flow.confirm.assert_not_called()
    flow.project.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_receipt_retries_without_touching_runtime(flow):
    flow.claim.return_value = AdmissionClaim(REFERENCE.run_id, "admitted", 42, True, False)
    flow.read.return_value = flow.confirmed
    flow.receipt.return_value = (61, "completed")
    result = await service.run_background(flow.client, PAYLOAD, ACTOR)
    assert result.assistant_message_id == 61 and result.chunks == 0
    flow.client.inspect_run.assert_not_awaited()
    flow.client.start_prepared_run.assert_not_awaited()
    flow.project.assert_not_awaited()


@pytest.mark.asyncio
async def test_preparation_failure_rejects_before_runtime_is_contacted(flow):
    flow.preparation.side_effect = ValueError("invalid resource")
    with pytest.raises(ValueError):
        await service.run_background(flow.client, PAYLOAD, ACTOR)
    flow.reject.assert_called_once()
    flow.client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_preparation_retains_request_settings_and_original_history_boundary(mocker):
    snapshot = SimpleNamespace(memory_enabled=True, resource=SimpleNamespace(agent_id=7, version_no=2))

    async def inline(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    mocker.patch.object(service, "_io", side_effect=inline)
    mocker.patch.object(service, "get_conversation", return_value={"runtime_metadata_version": 0})
    mocker.patch.object(service, "get_current_run_user_message_id", return_value=23)
    compile_run = mocker.patch.object(service, "prepare_conversation_snapshot", return_value=snapshot)
    request = service.AgentRequest.model_validate({**PAYLOAD.request, "model_id": 11, "reasoning_effort": "high"})
    prepared, turn = await service._prepare(request, REFERENCE, ACTOR)
    assert prepared is snapshot and turn["query"] == "hello" and turn["memory_agent_id"] == 7
    assert compile_run.await_args.args == (request, REFERENCE, "actor", "tenant")
    assert compile_run.await_args.kwargs["current_user_message_id"] == 23
    assert compile_run.await_args.kwargs["preserve_shared_reasoning"] is True
    assert request.model_id == 11 and request.reasoning_effort == "high"


@pytest.mark.asyncio
async def test_confirmation_conflict_stops_only_the_unbound_run(flow, mocker):
    from contracts.agentos import AgentStop
    from management.services.agent import prepared_turn

    mocker.patch.object(prepared_turn, "_io", side_effect=flow.inline)
    flow.confirm.side_effect = service.store.PreparedTurnConflict
    flow.client.stop_run = AsyncMock()
    with pytest.raises(AgentBackgroundError) as denied:
        await service.run_background(flow.client, PAYLOAD, ACTOR)
    assert denied.value.status_code == 409
    flow.client.stop_run.assert_awaited_once_with(AgentStop(**REFERENCE.model_dump(), prevent_start=True), "actor", "tenant")
    flow.close.assert_called_once_with(flow.staged)
    flow.project.assert_not_awaited()
