# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Neutral HTTP transport and typed clients for signed AgentOS operations."""

import asyncio
import logging

import httpx
from contracts.agentos import (
    MAX_REQUEST_BYTES,
    AgentActiveRun,
    AgentLegacyResume,
    AgentMemoryReceipt,
    AgentMemoryStore,
    AgentMessageRunLookup,
    AgentOperation,
    AgentResume,
    AgentRunLookup,
    AgentRunReference,
    AgentRunState,
    AgentStop,
    AgentToolResult,
    CompatibilityStop,
    DebugRunReference,
    EvaluationAgentResult,
    ManagementOperation,
    MemoryOperation,
    ModelCatalogPage,
    ModelInvocation,
    ModelMetadata,
    ModelOperation,
    ModelReference,
    ModelResult,
    PreparedAgentCreatorRun,
    PreparedAgentRun,
    PreparedEphemeralRun,
    PreparedEvaluationRun,
    PreparedSkillCreatorRun,
)
from contracts.agentos_knowledge import (
    FileCleanseReleased,
    FileCleanseState,
    KnowledgeBaseState,
    KnowledgeChunksGrant,
    KnowledgeChunksResult,
    KnowledgeContentGrant,
    KnowledgeFileGrant,
    KnowledgeJobState,
    KnowledgeOperation,
    KnowledgeSampleResult,
    KnowledgeSearchGrant,
    KnowledgeSearchResult,
)
from contracts.constants import environment
from contracts.errors.exceptions import (
    RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError,
    RuntimeUpstreamError,
)
from contracts.knowledge_base_deletion import (
    KnowledgeBaseDeleteGrant,
    KnowledgeBaseDeleteState,
)
from contracts.knowledge_chunk_mutation import (
    ChunkMutationGrant,
    ChunkMutationState,
    ChunkMutationTarget,
)
from contracts.knowledge_collections import (
    KnowledgeCollectionEnsured,
    KnowledgeCollectionGrant,
    KnowledgeCollectionsDescribed,
    KnowledgeCollectionsGrant,
    KnowledgeCollectionStatus,
    KnowledgeCollectionsUsageResult,
)
from contracts.knowledge_documents import KnowledgeDocumentsAppended
from contracts.knowledge_sources import KnowledgeSourcesResult
from pydantic import ValidationError
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from infrastructure.agentos_identity import (
    AgentOSIdentityError,
    ServicePrincipal,
    sign_call,
)

_STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
_REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
_MODEL_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)
_KNOWLEDGE_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
_KNOWLEDGE_DEADLINE_SECONDS = 10.0
_KNOWLEDGE_SEARCH_DEADLINE_SECONDS = 180.0
_COLLECTION_USAGE_DEADLINE_SECONDS = 40.0
_TOOL_DEADLINE_SECONDS = 600.0
logger = logging.getLogger(__name__)
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

    async def invoke_tool(self, payload, user_id, tenant_id):
        try:
            async with asyncio.timeout(_TOOL_DEADLINE_SECONDS):
                response = await self._post_json(
                    AgentOperation.INVOKE_TOOL, payload, user_id, tenant_id,
                    timeout=httpx.Timeout(connect=5, read=600, write=30, pool=5),
                )
                return self._validate_result(AgentToolResult, response)
        except (TimeoutError, RuntimeServiceTimeoutError) as error:
            logger.warning("agentos_tool_timeout run_id=%s phase=request threshold_seconds=%s exception_type=%s",
                           payload.run_id, _TOOL_DEADLINE_SECONDS, type(error).__name__)
            raise RuntimeServiceTimeoutError("AgentOS tool invocation timed out") from error

    async def submit_file_cleanse(self, payload, user_id, tenant_id):
        return await self._record_json(ManagementOperation.FILE_CLEANSE, payload, user_id, tenant_id, FileCleanseState)

    async def inspect_file_cleanse(self, payload, user_id, tenant_id):
        return await self._record_json(ManagementOperation.FILE_CLEANSE_STATUS, payload, user_id, tenant_id, FileCleanseState)

    async def cancel_file_cleanse(self, payload, user_id, tenant_id):
        return await self._record_json(ManagementOperation.FILE_CLEANSE_CANCEL, payload, user_id, tenant_id, FileCleanseState)

    async def release_file_cleanse(self, payload, user_id, tenant_id):
        return await self._record_json(ManagementOperation.FILE_CLEANSE_RELEASE, payload, user_id, tenant_id, FileCleanseReleased)

    async def authorize_knowledge(self, payload, user_id, tenant_id):
        return await self._record_json(ManagementOperation.KNOWLEDGE_AUTHORIZE, payload, user_id, tenant_id, KnowledgeFileGrant)

    async def authorize_knowledge_collection(self, payload, user_id, tenant_id):
        return await self._record_json(ManagementOperation.KNOWLEDGE_COLLECTION_AUTHORIZE, payload, user_id, tenant_id, KnowledgeCollectionGrant)

    async def authorize_collection_metadata(self, payload, user_id, tenant_id):
        return await self._record_json(ManagementOperation.KNOWLEDGE_COLLECTION_METADATA_AUTHORIZE, payload,
                                       user_id, tenant_id, KnowledgeCollectionsGrant)

    async def describe_knowledge_collections(self, payload, user_id, tenant_id):
        return await self._knowledge_request(KnowledgeOperation.DESCRIBE_COLLECTIONS, payload,
                                             user_id, tenant_id, KnowledgeCollectionsDescribed)

    async def knowledge_collection_usage(self, payload, user_id, tenant_id):
        return await self._knowledge_request(KnowledgeOperation.COLLECTION_USAGE,payload,
                                             user_id,tenant_id,KnowledgeCollectionsUsageResult,
                                             deadline_seconds=_COLLECTION_USAGE_DEADLINE_SECONDS)

    async def ensure_knowledge_collection(self, payload, user_id, tenant_id):
        return await self._knowledge_request(KnowledgeOperation.ENSURE_COLLECTION, payload, user_id, tenant_id, KnowledgeCollectionEnsured)

    async def inspect_knowledge_collection(self, payload, user_id, tenant_id):
        return await self._knowledge_request(KnowledgeOperation.INSPECT_COLLECTION, payload, user_id, tenant_id, KnowledgeCollectionStatus)

    async def authorize_knowledge_search(self, payload, user_id, tenant_id):
        return await self._record_json(ManagementOperation.KNOWLEDGE_SEARCH_AUTHORIZE, payload, user_id, tenant_id, KnowledgeSearchGrant)

    async def authorize_knowledge_chunks(self, payload, user_id, tenant_id):
        return await self._record_json(ManagementOperation.KNOWLEDGE_CHUNKS_AUTHORIZE, payload, user_id, tenant_id, KnowledgeChunksGrant)

    async def authorize_knowledge_chunk_mutation(self, payload, user_id, tenant_id):
        return await self._record_json(ManagementOperation.KNOWLEDGE_CHUNK_MUTATION_AUTHORIZE, payload, user_id, tenant_id, ChunkMutationGrant)

    async def mutate_knowledge_chunk(self, payload, user_id, tenant_id):
        return await self._knowledge_request(KnowledgeOperation.MUTATE_CHUNK, payload, user_id, tenant_id, ChunkMutationState)

    async def append_knowledge_documents(self, payload, user_id, tenant_id):
        return await self._knowledge_request(KnowledgeOperation.APPEND_DOCUMENTS, payload, user_id, tenant_id, KnowledgeDocumentsAppended)

    async def inspect_knowledge_chunk(self, payload, user_id, tenant_id):
        return await self._record_json(KnowledgeOperation.INSPECT_CHUNK, payload, user_id, tenant_id, ChunkMutationTarget)

    async def authorize_knowledge_content(self, payload, user_id, tenant_id):
        return await self._record_json(ManagementOperation.KNOWLEDGE_CONTENT_AUTHORIZE, payload, user_id, tenant_id, KnowledgeContentGrant)

    async def authorize_knowledge_base_deletion(self, payload, user_id, tenant_id):
        return await self._record_json(ManagementOperation.KNOWLEDGE_BASE_DELETION_AUTHORIZE, payload, user_id, tenant_id, KnowledgeBaseDeleteGrant)

    async def delete_knowledge_base(self, payload, user_id, tenant_id):
        return await self._record_json(KnowledgeOperation.DELETE_BASE, payload, user_id, tenant_id, KnowledgeBaseDeleteState)

    async def inspect_knowledge_base_deletion(self, payload, user_id, tenant_id):
        return await self._record_json(KnowledgeOperation.INSPECT_BASE_DELETION, payload, user_id, tenant_id, KnowledgeBaseDeleteState)

    async def search_knowledge(self, payload, user_id, tenant_id):
        return await self._knowledge_request(KnowledgeOperation.SEARCH, payload, user_id, tenant_id, KnowledgeSearchResult)

    async def sample_knowledge(self, payload, user_id, tenant_id):
        return await self._knowledge_request(KnowledgeOperation.SAMPLE, payload, user_id, tenant_id, KnowledgeSampleResult)

    async def knowledge_chunks(self, payload, user_id, tenant_id):
        return await self._knowledge_request(KnowledgeOperation.CHUNKS, payload, user_id, tenant_id, KnowledgeChunksResult)

    async def list_knowledge_sources(self, payload, user_id, tenant_id):
        return await self._knowledge_request(KnowledgeOperation.SOURCES, payload, user_id, tenant_id, KnowledgeSourcesResult)

    async def inspect_knowledge_base(self, payload, user_id, tenant_id):
        return await self._knowledge_request(KnowledgeOperation.INSPECT_BASE, payload, user_id, tenant_id, KnowledgeBaseState)

    async def _knowledge_request(self, operation, payload, user_id, tenant_id, schema, *, deadline_seconds=None):
        seconds = _KNOWLEDGE_SEARCH_DEADLINE_SECONDS if deadline_seconds is None else deadline_seconds
        try:
            async with asyncio.timeout(seconds):
                result = await self._post_json(operation, payload, user_id, tenant_id, timeout=_MODEL_TIMEOUT)
                return self._validate_result(schema, result)
        except (TimeoutError, RuntimeServiceTimeoutError) as error:
            name = operation.name.lower()
            logger.warning("agentos_knowledge_%s_timeout phase=request threshold_seconds=%s exception_type=%s",
                           name, seconds, type(error).__name__)
            raise RuntimeServiceTimeoutError(f"AgentOS knowledge {name} timed out") from error

    async def upload_knowledge_file(self, payload, user_id, tenant_id):
        return await self._record_json(KnowledgeOperation.UPLOAD, payload, user_id, tenant_id, KnowledgeJobState)

    async def inspect_knowledge_file(self, payload, user_id, tenant_id):
        return await self._record_json(KnowledgeOperation.INSPECT, payload, user_id, tenant_id, KnowledgeJobState)

    async def delete_knowledge_file(self, payload, user_id, tenant_id):
        return await self._record_json(KnowledgeOperation.DELETE, payload, user_id, tenant_id, KnowledgeJobState)

    async def _record_json(self, operation, payload, user_id, tenant_id, schema):
        try:
            async with asyncio.timeout(_KNOWLEDGE_DEADLINE_SECONDS):
                result = await self._post_json(operation, payload, user_id, tenant_id, timeout=_KNOWLEDGE_TIMEOUT)
                return self._validate_result(schema, result)
        except (TimeoutError, RuntimeServiceTimeoutError) as exc:
            event = "agentos_file_cleanse_timeout" if operation in {
                ManagementOperation.FILE_CLEANSE, ManagementOperation.FILE_CLEANSE_STATUS,
                ManagementOperation.FILE_CLEANSE_CANCEL, ManagementOperation.FILE_CLEANSE_RELEASE,
            } else "agentos_knowledge_timeout"
            logger.warning(
                "%s operation=%s phase=request threshold_seconds=%s exception_type=%s",
                event, operation.name, _KNOWLEDGE_DEADLINE_SECONDS, type(exc).__name__,
            )
            raise RuntimeServiceTimeoutError("AgentOS record request timed out") from exc

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

    async def start_prepared_run(self, payload: PreparedAgentRun, user_id: str, tenant_id: str) -> AgentRunReference:
        result = await self._post_json(AgentOperation.RUN, payload, user_id, tenant_id)
        return self._validate_result(AgentRunReference, result)

    async def store_agent_memory(
        self, payload: AgentMemoryStore, user_id: str, tenant_id: str,
    ) -> AgentMemoryReceipt:
        result = await self._post_json(MemoryOperation.STORE, payload, user_id, tenant_id, timeout=_MODEL_TIMEOUT)
        return self._validate_result(AgentMemoryReceipt, result)

    async def run_ephemeral(
        self, payload: PreparedEphemeralRun | PreparedSkillCreatorRun | PreparedAgentCreatorRun, user_id: str, tenant_id: str,
    ) -> StreamingResponse:
        return await self._open_stream(AgentOperation.RUN_EPHEMERAL, payload, user_id, tenant_id)

    async def resume(self, request: AgentResume, user_id: str, tenant_id: str) -> StreamingResponse:
        return await self._open_stream(AgentOperation.RESUME, request, user_id, tenant_id)

    async def resume_legacy(self, request: AgentLegacyResume, user_id: str, tenant_id: str) -> StreamingResponse:
        return await self._open_stream(AgentOperation.RESUME_LEGACY, request, user_id, tenant_id)

    async def _open_stream(self, operation, request, user_id, tenant_id):
        url, body, headers = self._request(operation, request, user_id, tenant_id)
        client = self.create_client(headers=headers, timeout=_STREAM_TIMEOUT, follow_redirects=False)
        try:
            async with asyncio.timeout(environment.AGENTOS_STREAM_OPEN_TIMEOUT_SECONDS):
                upstream = await client.send(client.build_request("POST", url, content=body), stream=True)
        except BaseException as exc:
            await client.aclose()
            if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
                logger.warning(
                    "agentos_stream_open_timeout operation=%s phase=headers threshold_seconds=%s error_type=%s",
                    operation.name, environment.AGENTOS_STREAM_OPEN_TIMEOUT_SECONDS, type(exc).__name__,
                )
                raise RuntimeServiceTimeoutError("Runtime agent run request timed out") from exc
            if isinstance(exc, httpx.RequestError):
                raise RuntimeServiceUnavailableError("Runtime service is unavailable") from exc
            raise

        closed = False

        async def close_upstream():
            nonlocal closed
            if not closed:
                closed = True
                try:
                    await upstream.aclose()
                finally:
                    await client.aclose()

        async def body_iterator():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await close_upstream()

        return StreamingResponse(
            body_iterator(), status_code=upstream.status_code, headers=_response_headers(upstream.headers),
            background=BackgroundTask(close_upstream),
        )

    async def run_prepared_evaluation(self, payload: PreparedEvaluationRun, user_id: str, tenant_id: str) -> EvaluationAgentResult:
        result = await self._post_json(
            AgentOperation.EVALUATION_CASE, payload, user_id, tenant_id, _STREAM_TIMEOUT,
        )
        return self._validate_result(EvaluationAgentResult, result)

    async def find_active_run(self, conversation_id: int, user_id: str, tenant_id: str) -> str | None:
        result = await self._post_json(
            AgentOperation.ACTIVE, CompatibilityStop(conversation_id=conversation_id), user_id, tenant_id,
        )
        return self._validate_result(AgentActiveRun, result).run_id

    async def stop_debug_run(self, run_id: str, user_id: str, tenant_id: str) -> dict:
        return await self._post_json(
            AgentOperation.STOP, DebugRunReference(run_id=run_id), user_id, tenant_id,
        )

    async def inspect_run(
        self, payload: AgentRunLookup | AgentMessageRunLookup, user_id: str, tenant_id: str,
    ) -> AgentRunState:
        result = await self._post_json(AgentOperation.INSPECT, payload, user_id, tenant_id)
        return self._validate_result(AgentRunState, result)

    async def stop_run(self, payload: AgentStop, user_id: str, tenant_id: str) -> AgentRunState:
        result = await self._post_json(AgentOperation.STOP, payload, user_id, tenant_id)
        return self._validate_result(AgentRunState, result)

    async def get_model(self, model_id: int, user_id: str, tenant_id: str) -> ModelMetadata:
        payload = ModelReference(model_id=model_id)
        result = await self._post_json(ModelOperation.GET, payload, user_id, tenant_id)
        return self._validate_result(ModelMetadata, result)

    async def list_models(self, payload, user_id: str, tenant_id: str):
        result = await self._post_json(ModelOperation.LIST, payload, user_id, tenant_id)
        return self._validate_result(ModelCatalogPage, result)

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
