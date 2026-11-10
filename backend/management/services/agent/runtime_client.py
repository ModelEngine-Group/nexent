# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management AgentOS calls for Agent execution."""

from collections.abc import Awaitable, Callable

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from backend.http.client import create_httpx_client
from contracts.agent import AgentRequest
from contracts.agentos import (
    AgentResume, AgentRunReference, AgentStop, BackgroundRun, CompatibilityConversationRun, EvaluationAgentResult,
    EvaluationAgentRun, PreparedAgentCreatorRun, PreparedSkillCreatorRun, TrackedBackgroundResult,
)
from contracts.constants.environment import ENABLE_AGENT_WORKBENCH, RUNTIME_SERVICE_URL
from contracts.errors.exceptions import RunModelControlsError, RuntimeUpstreamError, ValidationError
from management.clients.agentos import AgentOSClient
from management.services.agent.agentos_events import (
    active_run_error_response, knowledge_scope_event_content, present_ephemeral_stream, present_public_resume,
)


def _agentos_client() -> AgentOSClient:
    return AgentOSClient(RUNTIME_SERVICE_URL, create_httpx_client)


async def forward_agent_run(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
) -> StreamingResponse:
    """Start an AgentOS compatibility run and relay its SSE response."""
    return await _agentos_client().run(agent_request.model_dump(mode="json"), user_id, tenant_id)


async def forward_creator_run(
    payload: PreparedSkillCreatorRun | PreparedAgentCreatorRun, user_id: str, tenant_id: str,
) -> StreamingResponse:
    return await _agentos_client().run_ephemeral(payload, user_id, tenant_id)


async def forward_a2a_run(agent_request: AgentRequest, user_id: str, tenant_id: str) -> StreamingResponse:
    from management.services.agent.preparation.evaluation_snapshot import prepare_a2a_snapshot

    snapshot = await prepare_a2a_snapshot(agent_request, user_id, tenant_id)
    if snapshot is None:
        return await forward_agent_run(agent_request, user_id, tenant_id)
    response = await _agentos_client().run_ephemeral(snapshot, user_id, tenant_id)
    return present_ephemeral_stream(response, user_id, snapshot.run_id)


async def forward_northbound_run(
    agent_request: AgentRequest, user_id: str, tenant_id: str, *,
    fallback: Callable[[], Awaitable[StreamingResponse]],
):
    payload = CompatibilityConversationRun(request=agent_request.model_dump(mode="json"))
    try:
        response = await forward_conversation_run(payload, user_id, tenant_id, northbound_fallback=fallback)
    except HTTPException as exc:
        if exc.status_code != 409 or exc.detail != {"code": "AGENTOS_RUN_ALREADY_ACTIVE"}:
            raise
    except RuntimeUpstreamError as exc:
        if exc.status_code != 409 or exc.headers.get("X-Stream-Status") != "conflict":
            raise
    else:
        if response.status_code != 409 or response.headers.get("X-Stream-Status") != "conflict":
            return response
        if response.background is not None:
            await response.background()
    return active_run_error_response(payload.language)


async def forward_conversation_run(
    payload: CompatibilityConversationRun, user_id: str, tenant_id: str, *,
    northbound_fallback: Callable[[], Awaitable[StreamingResponse]] | None = None,
):
    client = _agentos_client()
    from management.services.agent import prepared_turn
    from management.services.agent.conversation_submission import submit_conversation

    request = AgentRequest.model_validate(payload.request)
    if payload.resume and request.entrypoint == "workbench" and not ENABLE_AGENT_WORKBENCH:
        raise HTTPException(status_code=404, detail={"code": "WORKBENCH_DISABLED"})
    if request.is_debug and not payload.resume and northbound_fallback is None:
        from management.services.agent.preparation.evaluation_snapshot import prepare_debug_snapshot

        try:
            prepared = await prepare_debug_snapshot(
                request, user_id, tenant_id, language=payload.language, timezone=payload.timezone,
            )
        except RunModelControlsError as exc:
            status = {"model_not_available": 404, "model_unavailable": 409, "model_type_invalid": 400}.get(exc.code, 422)
            raise HTTPException(status_code=status, detail={"code": exc.code}) from exc
        if prepared is not None:
            response = await client.run_ephemeral(prepared.payload, user_id, tenant_id)
            opening = None
            if prepared.knowledge is not None:
                opening = {"type": "knowledge_scope_resolved", "content": knowledge_scope_event_content(prepared.knowledge)}
            return present_ephemeral_stream(response, user_id, prepared.payload.run_id, opening_event=opening)

    conversation_id = request.conversation_id
    northbound = northbound_fallback is not None
    temporary_workbench_claim = request.entrypoint == "workbench" and payload.idempotency_key is None
    candidate = prepared_turn.is_prepared_candidate(payload, request)

    async def dispatch(claimed, owner, tenant):
        if candidate:
            response = await prepared_turn.start_turn(
                claimed, request, owner, tenant, client, include_journal_controls=not northbound,
                metadata_from_northbound=northbound and request.metadata is not None,
            )
            if response is not None:
                return response
            if northbound or temporary_workbench_claim:
                await prepared_turn.reject_unstaged_turn(claimed, owner, tenant)
                claimed = payload
        if conversation_id and conversation_id > 0 and not request.is_debug:
            if claimed.resume:
                response = await prepared_turn.resume_cursorless(conversation_id, owner, tenant, client)
                if response is not None:
                    return response
            elif await prepared_turn.find_pending_turn(conversation_id, owner, tenant) is not None:
                raise prepared_turn.active_turn_conflict()
        if northbound_fallback is not None:
            return await northbound_fallback()
        return await client.run_conversation(claimed, owner, tenant)

    if candidate or payload.idempotency_key is not None:
        return await submit_conversation(
            prepared_turn.with_submission_key(payload), user_id, tenant_id, dispatch,
            include_claim_headers=not (northbound or temporary_workbench_claim),
        )
    return await dispatch(payload, user_id, tenant_id)


async def forward_conversation_resume(payload: AgentResume, user_id: str, tenant_id: str):
    response = await _agentos_client().resume(payload, user_id, tenant_id)
    return present_public_resume(response, payload, user_id)


async def forward_agent_stop(
    conversation_id: int,
    user_id: str,
    tenant_id: str,
) -> dict:
    """Cancel a Northbound conversation run through AgentOS."""
    from management.services.agent.prepared_turn import find_pending_turn

    client = _agentos_client()
    pending = await find_pending_turn(conversation_id, user_id, tenant_id)
    if pending is None:
        run_id = await client.find_active_run(conversation_id, user_id, tenant_id)
        if run_id is None:
            return await client.stop(conversation_id, user_id, tenant_id)
        reference = AgentRunReference(run_id=run_id, conversation_id=conversation_id)
    else:
        reference = pending.reference

    state = await client.stop_run(
        AgentStop(**reference.model_dump(), prevent_start=pending is not None), user_id, tenant_id,
    )
    if state.cancellation_requested:
        message = f"successfully stopped agent run for user_id {user_id}, run_id {conversation_id}"
        return {"status": "success", "message": message}
    message = f"no running agent or preprocess tasks found for user_id {user_id}, run_id {conversation_id}"
    return {"status": "success", "message": message, "already_stopped": True}


async def forward_evaluation_case(payload: EvaluationAgentRun, user_id: str, tenant_id: str) -> EvaluationAgentResult:
    from management.services.agent.preparation.evaluation_snapshot import prepare_evaluation_snapshot

    prepared = await prepare_evaluation_snapshot(payload, user_id, tenant_id)
    if prepared is None:
        raise ValidationError("Evaluation resources could not be prepared for AgentOS")
    return await _agentos_client().run_prepared_evaluation(prepared, user_id, tenant_id)


async def forward_active_run(conversation_id: int, user_id: str, tenant_id: str) -> str | None:
    return await _agentos_client().find_active_run(conversation_id, user_id, tenant_id)


async def forward_scoped_stop(payload: AgentStop, user_id: str, tenant_id: str):
    return await _agentos_client().stop_run(payload, user_id, tenant_id)


async def forward_debug_stop(run_id: str, user_id: str, tenant_id: str):
    return await _agentos_client().stop_debug_run(run_id, user_id, tenant_id)


async def forward_tracked_background(
    agent_request: AgentRequest, run_id: str, user_id: str, tenant_id: str,
) -> TrackedBackgroundResult:
    payload = BackgroundRun(run_id=run_id, request=agent_request.model_dump(mode="json"))
    return await _agentos_client().run_tracked_background(payload, user_id, tenant_id)
