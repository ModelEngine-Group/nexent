"""HTTP forwarding from northbound APIs to the runtime service."""

from typing import AsyncIterator

import httpx
from fastapi.responses import StreamingResponse

from consts.const import RUNTIME_SERVICE_URL
from consts.exceptions import (
    RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError,
    RuntimeUpstreamError,
)
from consts.model import AgentRequest
from utils.auth_utils import generate_internal_runtime_jwt
from utils.http_client_utils import create_httpx_client


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
_STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
_REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
_EVALUATION_DISPATCH_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
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


async def forward_agent_run(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
) -> StreamingResponse:
    """Start a runtime agent run and proxy its response without buffering."""
    client = create_httpx_client(
        headers=_authorization_headers(user_id, tenant_id),
        timeout=_STREAM_TIMEOUT,
    )
    try:
        request = client.build_request(
            "POST",
            _runtime_url("/agent/internal/northbound/run"),
            json=agent_request.model_dump(mode="json"),
        )
        upstream = await client.send(request, stream=True)
    except httpx.TimeoutException as exc:
        await client.aclose()
        raise RuntimeServiceTimeoutError("Runtime agent run request timed out") from exc
    except httpx.RequestError as exc:
        await client.aclose()
        raise RuntimeServiceUnavailableError(_RUNTIME_SERVICE_UNAVAILABLE_MESSAGE) from exc
    except Exception:
        await client.aclose()
        raise

    async def body_iterator() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        body_iterator(),
        status_code=upstream.status_code,
        headers=_forwarded_headers(upstream.headers),
    )


async def forward_agent_stop(
    conversation_id: int,
    user_id: str,
    tenant_id: str,
) -> dict:
    """Ask the runtime service to stop a northbound agent run."""
    try:
        async with create_httpx_client(
            headers=_authorization_headers(user_id, tenant_id),
            timeout=_REQUEST_TIMEOUT,
        ) as client:
            response = await client.post(
                _runtime_url(f"/agent/internal/northbound/stop/{conversation_id}")
            )
    except httpx.TimeoutException as exc:
        raise RuntimeServiceTimeoutError("Runtime stop request timed out") from exc
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
            "Runtime stop response is not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeServiceUnavailableError(
            "Runtime stop response is not a JSON object"
        )
    return payload
