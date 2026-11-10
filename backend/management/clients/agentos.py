# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management HTTP adapter for the AgentOS compatibility operations."""

import httpx
from pydantic import ValidationError
from starlette.responses import StreamingResponse

from contracts.agentos import (
    MAX_REQUEST_BYTES,
    AgentActiveRun,
    AgentOperation,
    AgentRunLookup,
    AgentStop,
    BackgroundRun,
    DebugRunReference,
    AgentResume,
    AgentRunState,
    AgentRunningState,
    BackgroundAgentResult,
    CompatibilityConversationRun,
    CompatibilityOperation,
    CompatibilityRun,
    CompatibilityStop,
    EvaluationAgentResult,
    EvaluationAgentRun,
    ModelInvocation,
    ModelMetadata,
    ModelOperation,
    ModelReference,
    ModelResult,
    PreparedEvaluationRun,
    TrackedBackgroundResult,
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
        return await self._open_stream(
            CompatibilityOperation.RUN, CompatibilityRun(request=request), user_id, tenant_id,
        )

    async def run_conversation(self, request: CompatibilityConversationRun, user_id: str, tenant_id: str):
        return await self._open_stream(CompatibilityOperation.CONVERSATION_RUN, request, user_id, tenant_id)

    async def resume(self, request: AgentResume, user_id: str, tenant_id: str) -> StreamingResponse:
        return await self._open_stream(AgentOperation.RESUME, request, user_id, tenant_id)

    async def _open_stream(self, operation, request, user_id, tenant_id):
        url, body, headers = self._request(operation, request, user_id, tenant_id)
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

    async def run_evaluation_case(self, payload: EvaluationAgentRun, user_id: str, tenant_id: str) -> EvaluationAgentResult:
        result = await self._post_json(
            CompatibilityOperation.EVALUATION_CASE, payload, user_id, tenant_id, _STREAM_TIMEOUT,
        )
        return self._validate_result(EvaluationAgentResult, result)

    async def run_prepared_evaluation(self, payload: PreparedEvaluationRun, user_id: str, tenant_id: str) -> EvaluationAgentResult:
        result = await self._post_json(
            AgentOperation.EVALUATION_CASE, payload, user_id, tenant_id, _STREAM_TIMEOUT,
        )
        return self._validate_result(EvaluationAgentResult, result)

    async def run_background(self, request, user_id, tenant_id) -> BackgroundAgentResult:
        result = await self._post_json(
            CompatibilityOperation.BACKGROUND, CompatibilityRun(request=request), user_id, tenant_id, _STREAM_TIMEOUT,
        )
        return self._validate_result(BackgroundAgentResult, result)

    async def inspect(self, conversation_id, user_id, tenant_id) -> AgentRunningState:
        result = await self._post_json(
            CompatibilityOperation.INSPECT, CompatibilityStop(conversation_id=conversation_id), user_id, tenant_id,
        )
        return self._validate_result(AgentRunningState, result)

    async def stop(self, conversation_id, user_id, tenant_id):
        payload = CompatibilityStop(conversation_id=conversation_id)
        return await self._post_json(CompatibilityOperation.STOP, payload, user_id, tenant_id)

    async def run_tracked_background(self, payload: BackgroundRun, user_id: str, tenant_id: str) -> TrackedBackgroundResult:
        result = await self._post_json(AgentOperation.BACKGROUND, payload, user_id, tenant_id, _STREAM_TIMEOUT)
        tracked_result = self._validate_result(TrackedBackgroundResult, result)
        if tracked_result.run_id != payload.run_id:
            raise RuntimeServiceUnavailableError("AgentOS returned a different background run ID")
        return tracked_result

    async def find_active_run(self, conversation_id: int, user_id: str, tenant_id: str) -> str | None:
        result = await self._post_json(
            AgentOperation.ACTIVE, CompatibilityStop(conversation_id=conversation_id), user_id, tenant_id,
        )
        return self._validate_result(AgentActiveRun, result).run_id

    async def stop_debug_run(self, run_id: str, user_id: str, tenant_id: str) -> dict:
        return await self._post_json(
            CompatibilityOperation.DEBUG_STOP, DebugRunReference(run_id=run_id), user_id, tenant_id,
        )

    async def inspect_run(self, payload: AgentRunLookup, user_id: str, tenant_id: str) -> AgentRunState:
        result = await self._post_json(AgentOperation.INSPECT, payload, user_id, tenant_id)
        return self._validate_result(AgentRunState, result)

    async def stop_run(self, payload: AgentStop, user_id: str, tenant_id: str) -> AgentRunState:
        result = await self._post_json(AgentOperation.STOP, payload, user_id, tenant_id)
        return self._validate_result(AgentRunState, result)

    async def get_model(self, model_id: int, user_id: str, tenant_id: str) -> ModelMetadata:
        payload = ModelReference(model_id=model_id)
        result = await self._post_json(ModelOperation.GET, payload, user_id, tenant_id)
        return self._validate_result(ModelMetadata, result)

    async def invoke_model(self, payload: ModelInvocation, user_id: str, tenant_id: str) -> ModelResult:
        result = await self._post_json(ModelOperation.INVOKE, payload, user_id, tenant_id, _MODEL_TIMEOUT)
        return self._validate_result(ModelResult, result)

    async def model_command(self, operation, payload, user_id, tenant_id):
        response = await self._post_json(operation, payload, user_id, tenant_id, _MODEL_TIMEOUT)
        if "result" not in response:
            raise RuntimeServiceUnavailableError("Invalid AgentOS model administration response")
        return response["result"]

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
