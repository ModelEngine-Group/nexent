# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Delete public chunks using live edit rights and standard AgentOS operations."""

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


async def delete_manual_chunk(index_name, chunk_id, actor, *, reader=None, client=None, operation_seconds=180):
    if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 180:
        raise InvalidInput()
    cancelled = Event()
    context = OperationContext("knowledge-public-chunk-delete-" + uuid4().hex,
                               monotonic() + operation_seconds, cancelled=cancelled)
    threshold = context.remaining()
    reader = reader or KnowledgeFileReader()
    client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
    try:
        async with asyncio.timeout(threshold):
            row = await run_blocking("knowledge-public-chunk-delete-resource", reader.knowledge,
                index_name, actor, edit=True, context=context, lane="control-io", owner="management.knowledge_base")
            grant = chunks_resource_grant(row)
            request = ChunkMutationLookup(knowledge_id=grant.knowledge_id, chunk_id=chunk_id,
                operation="delete", resource_revision=grant.revision, resolve_public_id=True)
            target = await client.inspect_knowledge_chunk(request, actor.user_id, actor.tenant_id)
            context.remaining()
            if not isinstance(target, ChunkMutationTarget) or any(
                getattr(target, field) != value for field, value in request.model_dump().items()
            ):
                raise Conflict()
            # Revalidate transport results before using their trusted execution binding.
            target = ChunkMutationTarget.model_validate(target.model_dump(mode="json"))
            chunk = target.chunk
            if chunk is None:
                raise RuntimeError(f"Error deleting chunk: Chunk {chunk_id} not found in index {index_name}")
            ref = None if chunk.file_id is None else KnowledgeFileReference(
                knowledge_id=chunk.knowledge_id, file_id=chunk.file_id, file_version=chunk.file_version)
            intent = ChunkMutationIntent(knowledge_id=grant.knowledge_id, chunk_id=chunk.chunk_id,
                request_key=uuid4().hex, operation="delete", resource_revision=grant.revision,
                expected_change_epoch=target.change_epoch, file_ref=ref,
                generation=target.generation if ref else None, chunk_index=chunk.chunk_index if ref else None)
            state = await client.mutate_knowledge_chunk(intent, actor.user_id, actor.tenant_id)
            context.remaining()
            if not isinstance(state, ChunkMutationState) or any(
                getattr(state, field) != getattr(intent, field) for field in ("knowledge_id", "chunk_id", "operation")
            ):
                raise Conflict()
            if state.status != "completed":
                raise OutcomeUnknown(operation_id=context.operation_id)
            if not state.writer_ended or state.count_delta != -1 or state.commit_epoch is None or state.commit_epoch <= target.change_epoch:
                raise Conflict()
            return {"status": "success", "message": f"Chunk {chunk_id} deleted successfully", "chunk_id": chunk_id}
    except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
        logger.warning("knowledge_public_chunk_delete_timeout operation_id=%s threshold_seconds=%s exception_type=%s",
                       context.operation_id, threshold, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        cancelled.set()
