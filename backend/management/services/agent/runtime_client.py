# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management AgentOS calls for Agent execution."""

from fastapi.responses import StreamingResponse

from backend.http.client import create_httpx_client
from contracts.agent import AgentRequest
from contracts.agentos import (
    AgentResume, BackgroundAgentResult, CompatibilityConversationRun, EvaluationAgentResult, EvaluationAgentRun,
)
from contracts.constants.environment import RUNTIME_SERVICE_URL
from management.clients.agentos import AgentOSClient


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
    return await _agentos_client().run_conversation(payload, user_id, tenant_id)


async def forward_conversation_resume(payload: AgentResume, user_id: str, tenant_id: str):
    return await _agentos_client().resume(payload, user_id, tenant_id)


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
    client = _agentos_client()
    if prepared is not None:
        return await client.run_prepared_evaluation(prepared, user_id, tenant_id)
    return await client.run_evaluation_case(payload, user_id, tenant_id)
