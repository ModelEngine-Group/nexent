# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management HTTP adapter for the AgentOS compatibility operations."""

import httpx
from pydantic import ValidationError
from starlette.responses import StreamingResponse

from contracts.agentos import (
    MAX_REQUEST_BYTES,
    CompatibilityOperation,
    CompatibilityRun,
    CompatibilityStop,
    ModelInvocation,
    ModelMetadata,
    ModelOperation,
    ModelReference,
    ModelResult,
)
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError
from infrastructure.agentos_identity import AgentOSIdentityError, ServicePrincipal, sign_call

_STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
_REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
_MODEL_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)
_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}


def _response_headers(headers):
    excluded = _HOP_HEADERS | {name.strip().lower() for name in headers.get("connection", "").split(",")}
    return {name: value for name, value in headers.items() if name.lower() not in excluded}


class AgentOSClient:
    def __init__(self, runtime_url, create_client):
        self.runtime_url = runtime_url.rstrip("/")
        self.create_client = create_client

    def _request(self, operation, payload, user_id, tenant_id):
        body = payload.model_dump_json().encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            raise RuntimeUpstreamError(
                status_code=413,
                content=b'{"code":"AGENTOS_REQUEST_TOO_LARGE"}',
                headers={"content-type": "application/json"},
            )
        try:
            token = sign_call(operation, body, ServicePrincipal(user_id, tenant_id))
        except AgentOSIdentityError as exc:
            raise RuntimeServiceUnavailableError("Internal runtime authentication is not configured") from exc
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        return f"{self.runtime_url}/api{operation.value}", body, headers

    async def run(self, request, user_id, tenant_id):
        url, body, headers = self._request(
            CompatibilityOperation.RUN, CompatibilityRun(request=request), user_id, tenant_id,
        )
        client = self.create_client(headers=headers, timeout=_STREAM_TIMEOUT, follow_redirects=False)
        try:
            upstream = await client.send(client.build_request("POST", url, content=body), stream=True)
        except BaseException as exc:
            await client.aclose()
            if isinstance(exc, httpx.TimeoutException):
                raise RuntimeServiceTimeoutError("Runtime agent run request timed out") from exc
            if isinstance(exc, httpx.RequestError):
                raise RuntimeServiceUnavailableError("Runtime service is unavailable") from exc
            raise

        async def body_iterator():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                try:
                    await upstream.aclose()
                finally:
                    await client.aclose()

        return StreamingResponse(
            body_iterator(), status_code=upstream.status_code, headers=_response_headers(upstream.headers),
        )

    async def stop(self, conversation_id, user_id, tenant_id):
        payload = CompatibilityStop(conversation_id=conversation_id)
        return await self._post_json(CompatibilityOperation.STOP, payload, user_id, tenant_id)

    async def get_model(self, model_id: int, user_id: str, tenant_id: str) -> ModelMetadata:
        payload = ModelReference(model_id=model_id)
        result = await self._post_json(ModelOperation.GET, payload, user_id, tenant_id)
        return self._validate_result(ModelMetadata, result)

    async def invoke_model(self, payload: ModelInvocation, user_id: str, tenant_id: str) -> ModelResult:
        result = await self._post_json(ModelOperation.INVOKE, payload, user_id, tenant_id, _MODEL_TIMEOUT)
        return self._validate_result(ModelResult, result)

    @staticmethod
    def _validate_result(schema, result):
        try:
            return schema.model_validate(result)
        except ValidationError as exc:
            raise RuntimeServiceUnavailableError("Invalid AgentOS response") from exc

    async def _post_json(self, operation, payload, user_id, tenant_id, timeout=_REQUEST_TIMEOUT):
        url, body, headers = self._request(operation, payload, user_id, tenant_id)
        try:
            async with self.create_client(headers=headers, timeout=timeout, follow_redirects=False) as client:
                response = await client.post(url, content=body)
        except httpx.TimeoutException as exc:
            raise RuntimeServiceTimeoutError("AgentOS request timed out") from exc
        except httpx.RequestError as exc:
            raise RuntimeServiceUnavailableError("Runtime service is unavailable") from exc
        if not response.is_success:
            raise RuntimeUpstreamError(
                status_code=response.status_code, content=response.content, headers=_response_headers(response.headers),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeServiceUnavailableError("AgentOS response is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeServiceUnavailableError("AgentOS response is not a JSON object")
        return payload
