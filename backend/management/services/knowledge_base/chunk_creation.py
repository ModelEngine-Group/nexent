# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Create public chunks through AgentOS with the original source and model input."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import KnowledgeFileReference
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_chunk_mutation import (
    ChunkMutationIntent,
    ChunkMutationLookup,
    ChunkMutationState,
    ChunkMutationTarget,
)
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from management.services.knowledge_base.chunk_payload import (
    build_chunk_payload,
    public_chunk_key,
)
from management.services.knowledge_base.chunks_authorization import (
    chunks_resource_grant,
)
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    OutcomeUnknown,
)
from nexent.storage.models import OperationContext

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient

logger = logging.getLogger(__name__)


async def create_manual_chunk(index_name, payload, actor, *, reader=None, client=None, operation_seconds=180,
                              require_embedding=False):
    if type(require_embedding) is not bool:
        raise InvalidInput()
    if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 180:
        raise InvalidInput()
    cancelled = Event()
    context = OperationContext("knowledge-public-chunk-create-"+uuid4().hex,
                               monotonic()+operation_seconds, cancelled=cancelled)
    threshold = context.remaining()
    reader = reader or KnowledgeFileReader()
    client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
    try:
        async with asyncio.timeout(threshold):
            row = await run_blocking("knowledge-public-chunk-create-resource", reader.knowledge,
                index_name, actor, edit=True, context=context, lane="control-io", owner="management.knowledge_base")
            try:
                grant = chunks_resource_grant(row)
                source = build_chunk_payload({"id": payload.chunk_id or "chunk_"+uuid4().hex, "content": payload.content,
                    "title": payload.title, "filename": payload.filename, "path_or_url": payload.path_or_url,
                    "created_by": actor.user_id}, payload.metadata)
                key = public_chunk_key(source["id"])
                request = ChunkMutationLookup(knowledge_id=grant.knowledge_id, chunk_id=key, operation="create",
                                              resource_revision=grant.revision)
                target = await client.inspect_knowledge_chunk(request, actor.user_id, actor.tenant_id)
                context.remaining()
                if not isinstance(target, ChunkMutationTarget) or any(
                    getattr(target, field) != value for field, value in request.model_dump().items()
                ):
                    raise Conflict()
                target = ChunkMutationTarget.model_validate(target.model_dump(mode="json"))
                chunk = target.chunk
                ref = None if chunk is None or chunk.file_id is None else KnowledgeFileReference(
                    knowledge_id=chunk.knowledge_id, file_id=chunk.file_id, file_version=chunk.file_version)
                model_id = row["embedding_model_id"]
                changes = {"content": source.pop("content"), "filename": source.get("filename") if isinstance(source.get("filename"), str) else None,
                    "supplied_embedding": source.pop("embedding", None), "location": {PUBLIC_CHUNK_SOURCE_KEY: source},
                    "embedding_input": payload.content,
                    "embedding_model": {"model_id": model_id} if type(model_id) is int and model_id > 0 else None}
                if require_embedding:
                    changes["require_embedding"] = True
                intent = ChunkMutationIntent(knowledge_id=grant.knowledge_id, chunk_id=key, operation="create",
                    request_key=uuid4().hex, resource_revision=grant.revision, expected_change_epoch=target.change_epoch,
                    file_ref=ref, generation=target.generation if ref else None, chunk_index=chunk.chunk_index if ref else None,
                    changes=changes)
                state = await client.mutate_knowledge_chunk(intent, actor.user_id, actor.tenant_id)
                context.remaining()
                if not isinstance(state, ChunkMutationState) or any(
                    getattr(state, field) != getattr(intent, field) for field in ("knowledge_id", "chunk_id", "operation")
                ):
                    raise Conflict()
                if state.status != "completed":
                    raise OutcomeUnknown(operation_id=context.operation_id)
                if (not state.writer_ended or state.count_delta != (1 if chunk is None else 0)
                    or state.commit_epoch is None or state.commit_epoch <= target.change_epoch):
                    raise Conflict()
                return {"status": "success", "message": f"Chunk {key} created successfully", "chunk_id": key}
            except ValueError as error:
                raise RuntimeError(f"Error creating chunk: {error}") from error
    except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
        logger.warning("knowledge_public_chunk_create_timeout operation_id=%s threshold_seconds=%s exception_type=%s",
                       context.operation_id, threshold, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        cancelled.set()
