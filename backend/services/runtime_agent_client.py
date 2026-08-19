"""HTTP client used by Northbound to delegate Agent execution to Runtime."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from consts.const import RUNTIME_SERVICE_URL
from services.agent_stream_contract import _run_interrupted_chunk
from utils.http_client_utils import create_httpx_client


logger = logging.getLogger(__name__)

RUN_TIMEOUT = httpx.Timeout(connect=5.0, pool=5.0, write=30.0, read=None)
STOP_TIMEOUT = httpx.Timeout(connect=5.0, pool=5.0, write=30.0, read=30.0)


class RuntimeServiceError(HTTPException):
    """An HTTP error that must be returned to the Northbound caller."""

    def __init__(self, status_code: int, content: bytes, content_type: str = "application/json"):
        super().__init__(status_code=status_code, detail="Runtime service request failed")
        self.content = content
        self.content_type = content_type


def runtime_service_error_response(exc: RuntimeServiceError):
    """Build a response without rewriting an upstream 4xx business error."""
    from fastapi import Response

    return Response(
        content=exc.content,
        status_code=exc.status_code,
        headers={"Content-Type": exc.content_type},
    )


def _service_error(status_code: int, message: str) -> RuntimeServiceError:
    return RuntimeServiceError(
        status_code=status_code,
        content=json.dumps({"message": message}, ensure_ascii=False).encode("utf-8"),
    )


class RuntimeAgentClient:
    """Lifespan-managed Runtime client with streaming response ownership."""

    def __init__(self, base_url: str = RUNTIME_SERVICE_URL):
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    async def start(self) -> None:
        """Create the reusable HTTP client without probing Runtime readiness."""
        await self._ensure_client()

    async def close(self) -> None:
        """Close the reusable HTTP client."""
        async with self._client_lock:
            client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    async def _ensure_client(self) -> httpx.AsyncClient:
        client = self._client
        if client is not None and not client.is_closed:
            return client
        async with self._client_lock:
            client = self._client
            if client is None or client.is_closed:
                client = create_httpx_client(follow_redirects=False)
                self._client = client
            return client

    @staticmethod
    async def _read_error(response: httpx.Response) -> RuntimeServiceError:
        try:
            content = await response.aread()
        finally:
            await response.aclose()

        if 400 <= response.status_code < 500:
            return RuntimeServiceError(
                status_code=response.status_code,
                content=content,
                content_type=response.headers.get("content-type", "application/json"),
            )
        return _service_error(502, "Runtime service returned an invalid response")

    async def run_agent(
        self,
        agent_request: Any,
        user_id: str,
        tenant_id: str,
        request_id: str,
        runtime_scope_id: str | None = None,
    ) -> StreamingResponse:
        """Open one Runtime Agent stream without retrying execution."""
        client = await self._ensure_client()
        payload = {
            "agent_request": agent_request.model_dump(mode="json"),
            "user_id": user_id,
            "tenant_id": tenant_id,
            "runtime_scope_id": runtime_scope_id,
        }
        request = client.build_request(
            "POST",
            f"{self.base_url}/internal/agent/run",
            json=payload,
            headers={"X-Request-Id": request_id},
            timeout=RUN_TIMEOUT,
        )
        try:
            upstream = await client.send(request, stream=True)
        except httpx.RequestError as exc:
            logger.warning("Runtime Agent connection failed request_id=%s: %s", request_id, exc)
            raise _service_error(503, "Runtime service is unavailable") from exc

        if not 200 <= upstream.status_code < 300:
            raise await self._read_error(upstream)

        async def proxy_stream() -> AsyncIterator[bytes]:
            tail = b""
            try:
                async for chunk in upstream.aiter_raw():
                    if not chunk:
                        continue
                    tail = (tail + chunk)[-4:]
                    yield chunk
            except httpx.RequestError as exc:
                logger.warning("Runtime Agent stream interrupted request_id=%s: %s", request_id, exc)
                separator = b"" if tail.endswith(b"\n\n") or tail.endswith(b"\r\n\r\n") else b"\n\n"
                yield separator + _run_interrupted_chunk().encode("utf-8")
            finally:
                await upstream.aclose()

        headers = {
            "Cache-Control": upstream.headers.get("cache-control", "no-cache"),
            "Connection": "keep-alive",
        }
        if conversation_id := upstream.headers.get("conversation_id"):
            headers["conversation_id"] = conversation_id
        return StreamingResponse(
            proxy_stream(),
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "text/event-stream").split(";", 1)[0],
            headers=headers,
        )

    async def stop_agent(
        self,
        conversation_id: int | str,
        user_id: str,
        request_id: str,
    ) -> dict[str, Any]:
        """Ask Runtime to publish a distributed cancellation signal."""
        client = await self._ensure_client()
        try:
            response = await client.post(
                f"{self.base_url}/internal/agent/stop",
                json={"conversation_id": conversation_id, "user_id": user_id},
                headers={"X-Request-Id": request_id},
                timeout=STOP_TIMEOUT,
            )
        except httpx.RequestError as exc:
            logger.warning("Runtime Agent stop connection failed request_id=%s: %s", request_id, exc)
            raise _service_error(503, "Runtime service is unavailable") from exc

        if not 200 <= response.status_code < 300:
            if 400 <= response.status_code < 500:
                raise RuntimeServiceError(
                    status_code=response.status_code,
                    content=response.content,
                    content_type=response.headers.get("content-type", "application/json"),
                )
            raise _service_error(502, "Runtime service returned an invalid response")
        return response.json()


runtime_agent_client = RuntimeAgentClient()
