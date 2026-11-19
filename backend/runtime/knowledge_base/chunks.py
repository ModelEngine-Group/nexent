# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Browse published and confirmed manual chunk windows without inference."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import (
    KnowledgeChunks,
    KnowledgeChunksAuthorization,
    KnowledgeChunksResult,
)
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_chunk_projection import (
    PUBLIC_CHUNK_SOURCE_KEY,
    public_path_matches,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import OperationContext
from runtime.knowledge_base.chunk_view import ChunkReadView
from runtime.knowledge_base.publication import published_files, published_job
from runtime.knowledge_base.sample import PublishedKnowledgeReader, _snapshot

from infrastructure.knowledge_runtime import knowledge_chunks_ports

logger = logging.getLogger(__name__)


def _scope(port, actor, resource):
    scope = port.scope
    if (scope.system or scope.service_role != 'runtime' or scope.actor_id != actor.user_id or scope.tenant_id != resource.resource_tenant_id
        or resource.resource_tenant_id not in {actor.tenant_id, ASSET_OWNER_TENANT_ID}):
        raise ScopeDenied()


def _window(records, vectors, request, resource, *, context):
    view = ChunkReadView(records, request.knowledge_id, context=context)
    total, result = 0, []
    refs = None if request.file_ids is None else set(request.file_ids)
    for manifest in published_files(records, request.knowledge_id, context=context):
        selected = refs is None or manifest['file_id'] in refs
        if not selected and request.standalone_path is None:
            continue
        job = published_job(records, resource, manifest, context=context)
        count = view.file_count(manifest, job, context=context)
        filtered = None
        if request.standalone_path is not None:
            rows = view.file_window(vectors, resource, manifest, job, 0, count, context=context) if count else []
            filtered = [row for row in rows if (
                public_path_matches(row.location, request.standalone_path)
                if PUBLIC_CHUNK_SOURCE_KEY in row.location else selected)]
            count = len(filtered)
        start, end = max(0, request.offset-total), min(count, request.offset+request.limit-total)
        total += count
        if start < end:
            result.extend(filtered[start:end] if filtered is not None else
                view.file_window(vectors, resource, manifest, job, start, end, context=context))
    if refs is None or request.standalone_path is not None:
        count = view.standalone_count(context=context)
        filtered = None
        if request.standalone_path is not None:
            rows = view.standalone_window(vectors, resource, 0, count, context=context) if count else []
            filtered = [row for row in rows if public_path_matches(row.location, request.standalone_path)]
            count = len(filtered)
        start, end = max(0, request.offset-total), min(count, request.offset+request.limit-total)
        total += count
        if start < end:
            result.extend(filtered[start:end] if filtered is not None else view.standalone_window(vectors, resource, start, end, context=context))
    view.stable(context=context)
    return total, result


class KnowledgeChunksService(PublishedKnowledgeReader):
    operation_name = 'knowledge-chunks'

    def __init__(self, authorization_client, *, ports=knowledge_chunks_ports, operation_seconds=180):
        super().__init__(authorization_client, None, ports=ports, operation_seconds=operation_seconds)

    async def _grant(self, request, actor):
        grant = await self.client.authorize_knowledge_chunks(KnowledgeChunksAuthorization(knowledge_id=request.knowledge_id),
                                                            actor.user_id, actor.tenant_id)
        if grant.knowledge_id != request.knowledge_id:
            raise ScopeDenied()
        if grant.revision != request.expected_revision:
            raise Conflict()
        return grant

    async def chunks(self, request, actor, *, context=None):
        if not isinstance(request, KnowledgeChunks): raise InvalidInput()
        context = context or OperationContext('knowledge-chunks-'+uuid4().hex,monotonic()+self.operation_seconds)
        threshold = context.remaining()
        try:
            async with asyncio.timeout(threshold):
                resource = await self._grant(request,actor)
                with self.ports(actor,resource,context=context) as (records,vectors):
                    _scope(records,actor,resource); _scope(vectors,actor,resource)
                    revision = await self._blocking(_snapshot,records,request.knowledge_id,context=context)
                    if request.expected_data_revision is not None and request.expected_data_revision != revision: raise Conflict()
                    total,chunks = await self._blocking(_window,records,vectors,request,resource,context=context)
                    if await self._grant(request,actor) != resource: raise Conflict()
                    final = await self._blocking(_snapshot,records,request.knowledge_id,context=context)
                    if final != revision: raise Conflict()
                next_offset = request.offset+len(chunks) if request.offset+len(chunks) < total else None
                return KnowledgeChunksResult(knowledge_id=request.knowledge_id,knowledge_revision=resource.revision,
                    data_revision=revision,total=total,chunks=chunks,next_offset=next_offset)
        except (TimeoutError,DeadlineExceeded,RuntimeServiceTimeoutError) as error:
            logger.warning('knowledge_chunks_timeout operation_id=%s phase=read threshold_seconds=%s exception_type=%s',
                context.operation_id,threshold,type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
