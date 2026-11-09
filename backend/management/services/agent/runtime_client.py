# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""HTTP forwarding from northbound APIs to the runtime service."""

import httpx
from fastapi.responses import StreamingResponse

from contracts.constants.environment import RUNTIME_SERVICE_URL
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError
from contracts.agent import AgentRequest
from gateway.downstream.internal_tokens import generate_internal_runtime_jwt
from backend.http.client import create_httpx_client
from management.clients.agentos import AgentOSClient


_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_EVALUATION_DISPATCH_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
_EVALUATION_TRIAL_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
_RUNTIME_SERVICE_UNAVAILABLE_MESSAGE = "Runtime service is unavailable"


def _runtime_url(path: str) -> str:
    return f"{RUNTIME_SERVICE_URL}/api{path}"


def _forwarded_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in _HOP_BY_HOP_HEADERS
    }


def _authorization_headers(user_id: str, tenant_id: str) -> dict[str, str]:
    try:
        token = generate_internal_runtime_jwt(user_id, tenant_id)
    except ValueError as exc:
        raise RuntimeServiceUnavailableError(
            "Internal runtime authentication is not configured"
        ) from exc
    return {"Authorization": f"Bearer {token}"}


def dispatch_agent_evaluation_run(
    agent_evaluation_id: int,
    user_id: str,
    tenant_id: str,
) -> dict:
    """Dispatch evaluation execution to the runtime service.

    Evaluation setup remains in the config service, while agent execution and
    scoring run in the runtime process that has access to the shared sandbox
    workspace volume.  This synchronous wrapper is intentionally suitable for
    the config service's existing background thread pool.
    """
    try:
        with httpx.Client(
            headers=_authorization_headers(user_id, tenant_id),
            timeout=_EVALUATION_DISPATCH_TIMEOUT,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = client.post(
                _runtime_url("/agent-evaluations/internal/run"),
                json={"agent_evaluation_id": agent_evaluation_id},
            )
    except httpx.TimeoutException as exc:
        raise RuntimeServiceTimeoutError("Runtime evaluation dispatch timed out") from exc
    except httpx.RequestError as exc:
        raise RuntimeServiceUnavailableError(_RUNTIME_SERVICE_UNAVAILABLE_MESSAGE) from exc

    if response.status_code >= 400:
        raise RuntimeUpstreamError(
            status_code=response.status_code,
            content=response.content,
            headers=_forwarded_headers(response.headers),
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeServiceUnavailableError(
            "Runtime evaluation dispatch response is not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeServiceUnavailableError(
            "Runtime evaluation dispatch response is not a JSON object"
        )
    return payload


async def forward_agent_evaluation_trial_run(
    *,
    agent_id: int,
    agent_version_no: int,
    query: str,
    judge_model_id: int,
    evaluator_ids: list[int] | None,
    language: str,
    user_id: str,
    tenant_id: str,
) -> dict:
    """Execute an ad-hoc evaluation in the Runtime process and return its result."""
    try:
        async with create_httpx_client(
            headers=_authorization_headers(user_id, tenant_id),
            timeout=_EVALUATION_TRIAL_TIMEOUT,
        ) as client:
            response = await client.post(
                _runtime_url("/agent-evaluations/internal/trial-run"),
                json={
                    "agent_id": agent_id,
                    "agent_version_no": agent_version_no,
                    "query": query,
                    "judge_model_id": judge_model_id,
                    "evaluator_ids": evaluator_ids,
                    "language": language,
                },
            )
    except httpx.TimeoutException as exc:
        raise RuntimeServiceTimeoutError("Runtime trial evaluation timed out") from exc
    except httpx.RequestError as exc:
        raise RuntimeServiceUnavailableError(_RUNTIME_SERVICE_UNAVAILABLE_MESSAGE) from exc

    if response.status_code >= 400:
        raise RuntimeUpstreamError(
            status_code=response.status_code,
            content=response.content,
            headers=_forwarded_headers(response.headers),
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeServiceUnavailableError(
            "Runtime trial evaluation response is not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeServiceUnavailableError(
            "Runtime trial evaluation response is not a JSON object"
        )
    return payload


def _agentos_client() -> AgentOSClient:
    return AgentOSClient(RUNTIME_SERVICE_URL, create_httpx_client)


async def forward_agent_run(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
) -> StreamingResponse:
    """Start an AgentOS compatibility run and relay its SSE response."""
    return await _agentos_client().run(agent_request.model_dump(mode="json"), user_id, tenant_id)


async def forward_agent_stop(
    conversation_id: int,
    user_id: str,
    tenant_id: str,
) -> dict:
    """Cancel a Northbound conversation run through AgentOS."""
    return await _agentos_client().stop(conversation_id, user_id, tenant_id)
