# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management AgentOS calls for Agent execution."""

from fastapi.responses import StreamingResponse

from backend.http.client import create_httpx_client
from contracts.agent import AgentRequest
from contracts.agentos import (
    AgentResume, AgentStop, BackgroundAgentResult, BackgroundRun, CompatibilityConversationRun, EvaluationAgentResult,
    EvaluationAgentRun, TrackedBackgroundResult,
)
from contracts.constants.environment import RUNTIME_SERVICE_URL
from contracts.errors.exceptions import ValidationError
from management.clients.agentos import AgentOSClient
from management.services.agent.agentos_events import present_public_resume


def _agentos_client() -> AgentOSClient:
    return AgentOSClient(RUNTIME_SERVICE_URL, create_httpx_client)


async def forward_agent_run(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
) -> StreamingResponse:
    """Start an AgentOS compatibility run and relay its SSE response."""
    return await _agentos_client().run(agent_request.model_dump(mode="json"), user_id, tenant_id)


async def forward_conversation_run(payload: CompatibilityConversationRun, user_id: str, tenant_id: str):
    client = _agentos_client()
    from management.services.agent import prepared_turn
    from management.services.agent.conversation_submission import submit_conversation

    request = AgentRequest.model_validate(payload.request)
    conversation_id = request.conversation_id
    candidate = prepared_turn.is_prepared_candidate(payload, request)

    async def dispatch(claimed, owner, tenant):
        if candidate:
            response = await prepared_turn.start_turn(claimed, request, owner, tenant, client)
            if response is not None:
                return response
        if conversation_id and conversation_id > 0 and not request.is_debug:
            pending = await prepared_turn.find_pending_turn(conversation_id, owner, tenant)
            if pending is not None:
                if claimed.resume:
                    return await prepared_turn.resume_turn(pending, client)
                raise prepared_turn.active_turn_conflict()
        return await client.run_conversation(claimed, owner, tenant)

    if candidate or payload.idempotency_key is not None:
        return await submit_conversation(prepared_turn.with_submission_key(payload), user_id, tenant_id, dispatch)
    return await dispatch(payload, user_id, tenant_id)


async def forward_conversation_resume(payload: AgentResume, user_id: str, tenant_id: str):
    response = await _agentos_client().resume(payload, user_id, tenant_id)
    return present_public_resume(response, payload, user_id)


async def forward_agent_background(agent_request: AgentRequest, user_id: str, tenant_id: str) -> BackgroundAgentResult:
    return await _agentos_client().run_background(agent_request.model_dump(mode="json"), user_id, tenant_id)


async def forward_agent_inspect(conversation_id: int, user_id: str, tenant_id: str) -> bool:
    return (await _agentos_client().inspect(conversation_id, user_id, tenant_id)).running


async def forward_agent_stop(
    conversation_id: int,
    user_id: str,
    tenant_id: str,
) -> dict:
    """Cancel a Northbound conversation run through AgentOS."""
    return await _agentos_client().stop(conversation_id, user_id, tenant_id)


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
