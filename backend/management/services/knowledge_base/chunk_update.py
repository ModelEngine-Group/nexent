# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserve public document merging while updating through standard AgentOS."""

import asyncio
import logging
from datetime import datetime, timezone
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
from contracts.knowledge_chunk_projection import (
    PUBLIC_CHUNK_SOURCE_KEY,
    public_chunk_source,
)
from management.services.knowledge_base.chunk_browser import KnowledgeChunkBrowser
from management.services.knowledge_base.chunk_payload import (
    build_chunk_payload,
    merge_chunk_source,
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
    ScopeDenied,
)
from nexent.storage.models import OperationContext

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient

logger = logging.getLogger(__name__)


async def _source(chunk, grant, index_name, actor, reader, *, context):
    source = public_chunk_source(chunk.content, chunk.location)
    if source is not None:
        return source
    files = {}
    if chunk.file_id is not None:
        rows = await run_blocking("knowledge-public-chunk-update-files", reader.files,
            index_name, actor, context=context, lane="control-io", owner="management.knowledge_base")
        selected = [row for row in rows if row["file_id"] == chunk.file_id and row["delete_flag"] == "N"]
        if (len(selected) != 1 or selected[0]["knowledge_id"] != grant.knowledge_id
            or selected[0]["tenant_id"] != grant.resource_tenant_id):
            raise ScopeDenied()
        files[chunk.file_id] = selected[0]
    return {**chunk.location, **KnowledgeChunkBrowser._chunk(chunk, files)}


async def update_manual_chunk(index_name, chunk_id, payload, actor, *, reader=None, client=None, operation_seconds=180):
    if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 180:
        raise InvalidInput()
    cancelled = Event()
    context = OperationContext("knowledge-public-chunk-update-"+uuid4().hex,
                               monotonic()+operation_seconds, cancelled=cancelled)
    threshold = context.remaining()
    reader = reader or KnowledgeFileReader()
    client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
    try:
        async with asyncio.timeout(threshold):
            row = await run_blocking("knowledge-public-chunk-update-resource", reader.knowledge,
                index_name, actor, edit=True, context=context, lane="control-io", owner="management.knowledge_base")
            try:
                grant = chunks_resource_grant(row)
                request = ChunkMutationLookup(knowledge_id=grant.knowledge_id, chunk_id=chunk_id, operation="update",
                    resource_revision=grant.revision, resolve_public_id=True,
                    native_documents=environment.KNOWLEDGE_RUNTIME_HYBRID_ENABLED)
                target = await client.inspect_knowledge_chunk(request, actor.user_id, actor.tenant_id)
                context.remaining()
                if not isinstance(target, ChunkMutationTarget) or any(
                    getattr(target, field) != value for field, value in request.model_dump().items()
                ):
                    raise Conflict()
                target = ChunkMutationTarget.model_validate(target.model_dump(mode="json"))
                chunk = target.chunk
                if chunk is None:
                    raise RuntimeError(f"Error updating chunk: Chunk {chunk_id} not found in index {index_name}")
                source = await _source(chunk, grant, index_name, actor, reader, context=context)
                patch = build_chunk_payload({**payload.model_dump(exclude_unset=True, exclude={"metadata"}),
                    "updated_by": actor.user_id, "update_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")},
                    payload.metadata, ensure_create_time=False)
                changes = {"embedding": patch.pop("embedding")} if "embedding" in patch else {}
                merged = merge_chunk_source(source, patch)
                if "content" in patch:
                    changes["content"] = merged["content"]
                if "filename" in patch:
                    changes["filename"] = merged["filename"] if isinstance(merged["filename"], str) else None
                merged.pop("content", None)
                merged.pop("embedding", None)
                changes["location"] = {**chunk.location, PUBLIC_CHUNK_SOURCE_KEY: merged}
                ref = None if chunk.file_id is None else KnowledgeFileReference(
                    knowledge_id=chunk.knowledge_id, file_id=chunk.file_id, file_version=chunk.file_version)
                intent = ChunkMutationIntent(knowledge_id=grant.knowledge_id, chunk_id=chunk.chunk_id, operation="update",
                    resource_revision=grant.revision, request_key=uuid4().hex, expected_change_epoch=target.change_epoch,
                    native_documents=target.native_documents, storage_revision=target.storage_revision,
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
                if not state.writer_ended or state.count_delta != 0 or state.commit_epoch is None or state.commit_epoch <= target.change_epoch:
                    raise Conflict()
                return {"status": "success", "message": f"Chunk {chunk.chunk_id} updated successfully", "chunk_id": chunk.chunk_id}
            except ValueError as error:
                raise RuntimeError(f"Error updating chunk: {error}") from error
    except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
        logger.warning("knowledge_public_chunk_update_timeout operation_id=%s threshold_seconds=%s exception_type=%s",
                       context.operation_id, threshold, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        cancelled.set()
