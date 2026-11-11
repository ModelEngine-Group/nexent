# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management AgentOS calls for Agent execution."""

import logging
from collections.abc import Awaitable, Callable

from anyio import CancelScope
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from redis.exceptions import RedisError

from backend.http.client import create_httpx_client
from contracts.agent import AgentRequest
from contracts.agentos import (
    AgentLegacyResume, AgentResume, AgentRunLookup, AgentRunReference, AgentStop, BackgroundRun, CompatibilityConversationRun, EvaluationAgentResult,
    EvaluationAgentRun, PreparedAgentCreatorRun, PreparedSkillCreatorRun, TrackedBackgroundResult,
    WorkbenchDebugSkillLookup, WorkbenchSkillMounts,
)
from contracts.constants.environment import ENABLE_AGENT_WORKBENCH, RUNTIME_SERVICE_URL
from contracts.errors.exceptions import (
    RunModelControlsError, RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError,
    ValidationError, WorkbenchError,
)
from infrastructure.rdb.agent_admission import AdmissionScopeError
from infrastructure.agentos_identity import ServicePrincipal
from management.clients.agentos import AgentOSClient
from management.services.agent.agentos_events import (
    active_run_error_response, knowledge_scope_event_content, present_ephemeral_stream, present_public_resume,
)
from management.services.agent.workbench_debug_grant import (
    WorkbenchDebugGrantUnavailable, close_workbench_debug_grant, open_workbench_debug_grant,
)
from nexent.core.concurrency import run_blocking

logger = logging.getLogger(__name__)


def _agentos_client() -> AgentOSClient:
    return AgentOSClient(RUNTIME_SERVICE_URL, create_httpx_client)


async def _run_prepared_debug(client, prepared, user_id, tenant_id):
    payload = prepared.payload
    if prepared.workbench is None or not payload.resource.workbench_skill_refs:
        return await client.run_ephemeral(payload, user_id, tenant_id)

    scope = WorkbenchDebugSkillLookup(
        run_id=payload.run_id, agent_id=payload.resource.agent_id, agent_version=payload.resource.version_no,
    )
    mounts = WorkbenchSkillMounts(mounts=[mount.model_dump(mode="json") for mount in prepared.workbench.skill_mounts])
    granted = False
    keep_image_grant = False
    try:
        with CancelScope(shield=True):
            try:
                await run_blocking(
                    "open-workbench-debug-grant", open_workbench_debug_grant,
                    scope, ServicePrincipal(user_id, tenant_id), mounts, lane="control-io", owner="management",
                )
            except (RedisError, WorkbenchDebugGrantUnavailable) as exc:
                raise HTTPException(status_code=503, detail={"code": "AGENTOS_WORKBENCH_SCOPE_UNAVAILABLE"}) from exc
            granted = True
        response = await client.run_ephemeral(payload, user_id, tenant_id)
        # The browser may read signed images after Runtime has closed the stream.
        keep_image_grant = response.status_code == 200 and any(
            binding.tool_id == "ind_aidp_search" and binding.version == "4" for binding in payload.resource.tools
        )
        return response
    finally:
        if granted and not keep_image_grant:
            with CancelScope(shield=True):
                try:
                    await run_blocking(
                        "close-workbench-debug-grant", close_workbench_debug_grant,
                        payload.run_id, lane="control-io", owner="management",
                    )
                except (RedisError, WorkbenchDebugGrantUnavailable):
                    logger.warning("Workbench debug grant will expire run_id=%s", payload.run_id)


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
    request = AgentRequest.model_validate(payload.request)
    if payload.resume and (request.is_debug or (request.conversation_id or 0) <= 0):
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_RESUME_REQUEST"})
    if request.entrypoint == "workbench" and not ENABLE_AGENT_WORKBENCH:
        raise HTTPException(status_code=404, detail={"code": "WORKBENCH_DISABLED"})

    from management.services.agent import prepared_turn
    from management.services.agent.conversation_submission import submit_conversation

    client = _agentos_client()
    saved_user = None
    if payload.user_message == "saved":
        if request.is_debug or payload.resume or (request.conversation_id or 0) <= 0:
            raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_SAVED_USER_REQUEST"})
        from management.services.agent.context import strip_current_time_prefix

        message_index = 2 * sum(item.role == "user" for item in request.history or [])
        try:
            saved_user = await run_blocking(
                "saved-user-source", prepared_turn.store.read_saved_user_turn,
                request.conversation_id, user_id, tenant_id, message_index,
                strip_current_time_prefix(request.query), request.minio_files, lane="control-io", owner="management",
            )
        except AdmissionScopeError as exc:
            raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"}) from exc
        except prepared_turn.store.PreparedTurnConflict as exc:
            raise prepared_turn.active_turn_conflict() from exc
        if payload.idempotency_key is None:
            payload = payload.model_copy(update={"idempotency_key": f"saved-message-{saved_user.message_id}"})
    if request.is_debug and not payload.resume and northbound_fallback is None:
        from management.services.agent.preparation.evaluation_snapshot import prepare_debug_snapshot

        try:
            prepared = await prepare_debug_snapshot(
                request, user_id, tenant_id, language=payload.language, timezone=payload.timezone,
            )
        except RunModelControlsError as exc:
            status = {"model_not_available": 404, "model_unavailable": 409, "model_type_invalid": 400}.get(exc.code, 422)
            raise HTTPException(status_code=status, detail={"code": exc.code}) from exc
        except WorkbenchError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc
        if prepared is not None:
            response = await _run_prepared_debug(client, prepared, user_id, tenant_id)
            opening = []
            if prepared.workbench is not None:
                opening.append({"type": "workbench_config_resolved", "content": {
                    "config_version": 0, "schema_version": prepared.workbench.schema_version,
                    "mode": prepared.workbench.mode,
                    "agent_mounts": [mount.model_dump(mode="json") for mount in prepared.workbench.agent_mounts],
                }})
            if prepared.knowledge is not None:
                opening.append({"type": "knowledge_scope_resolved", "content": knowledge_scope_event_content(prepared.knowledge)})
            public = present_ephemeral_stream(response, user_id, prepared.payload.run_id, opening_events=opening)
            if public.status_code == 200 and request.conversation_id is not None:
                public.headers["conversation_id"] = str(request.conversation_id)
            return public

    conversation_id = request.conversation_id
    northbound = northbound_fallback is not None or saved_user is not None
    temporary_workbench_claim = request.entrypoint == "workbench" and payload.idempotency_key is None
    candidate = prepared_turn.is_prepared_candidate(payload, request)

    async def dispatch(claimed, owner, tenant):
        if candidate:
            saved_options = {"saved_user": saved_user} if saved_user is not None else {}
            response = await prepared_turn.start_turn(
                claimed, request, owner, tenant, client, include_journal_controls=not northbound,
                metadata_from_northbound=northbound and request.metadata is not None,
                **saved_options,
            )
            if response is not None:
                return response
            if northbound_fallback is not None or temporary_workbench_claim:
                await prepared_turn.reject_unstaged_turn(claimed, owner, tenant)
                claimed = payload
        if conversation_id and conversation_id > 0 and not request.is_debug:
            if claimed.resume:
                response = await prepared_turn.resume_cursorless(conversation_id, owner, tenant, client)
                if response is not None:
                    return response
                return await client.resume_legacy(
                    AgentLegacyResume(conversation_id=conversation_id, workbench=request.entrypoint == "workbench"),
                    owner, tenant,
                )
            elif await prepared_turn.find_pending_turn(conversation_id, owner, tenant) is not None:
                raise prepared_turn.active_turn_conflict()
        if northbound_fallback is not None:
            return await northbound_fallback()
        return await client.run_conversation(claimed.model_copy(update={"preparation": "legacy"}), owner, tenant)

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
    client = _agentos_client()
    try:
        return await client.run_tracked_background(payload, user_id, tenant_id)
    except (RuntimeServiceTimeoutError, RuntimeServiceUnavailableError):
        if agent_request.conversation_id is not None and agent_request.conversation_id > 0:
            lookup = AgentRunLookup(run_id=run_id, conversation_id=agent_request.conversation_id)
            try:
                state = await client.inspect_run(lookup, user_id, tenant_id)
            except (RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError):
                state = None
            if (state is not None and state.status == "completed" and state.assistant_message_id is not None
                    and (state.run_id, state.conversation_id) == (lookup.run_id, lookup.conversation_id)):
                return TrackedBackgroundResult(
                    run_id=run_id, conversation_id=lookup.conversation_id,
                    assistant_message_id=state.assistant_message_id, chunks=0,
                )
        raise
