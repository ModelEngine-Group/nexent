# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Browse immutable published chunk windows without inference or legacy-index reads."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import (
    KnowledgeChunk,
    KnowledgeChunks,
    KnowledgeChunksResult,
    ModelVersion,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import Comparison, Junction, OperationContext, PageRequest
from runtime.knowledge_base.publication import published_files, published_job
from runtime.knowledge_base.sample import PublishedKnowledgeReader, _snapshot

from infrastructure.agent_model_config import normalize_model_revision

logger = logging.getLogger(__name__)


def _scope(port, actor):
    scope = port.scope
    if (scope.system or scope.service_role != 'runtime' or scope.actor_id != actor.user_id or scope.tenant_id != actor.tenant_id):
        raise ScopeDenied()


def _window(records, vectors, request, resource, model, *, context):
    total, result = 0, []
    refs = None if request.file_refs is None else {(ref.file_id, ref.file_version) for ref in request.file_refs}
    for manifest in published_files(records, request.knowledge_id, context=context):
        if refs is not None and (manifest['file_id'], manifest['visible_version']) not in refs: continue
        job = published_job(records, resource, manifest, context=context)
        start, end = max(0, request.offset-total), min(job['chunk_count'], request.offset+request.limit-total)
        total += job['chunk_count']
        if start >= end: continue
        reference = {'knowledge_id': request.knowledge_id, 'file_id': manifest['file_id'], 'file_version': manifest['visible_version']}
        where = Junction('and', tuple(Comparison(key, 'eq', value) for key, value in reference.items()) + (
            Comparison('chunk_index', 'gte', start), Comparison('chunk_index', 'lt', end)))
        selected, cursor, seen = {}, None, set()
        while True:
            page = vectors.scan(resource.collection, where, PageRequest(limit=min(request.limit,500), cursor=cursor), context=context)
            for record in page.items:
                data = record.payload
                if record.key.collection != resource.collection or any(data.get(key) != value for key, value in reference.items()):
                    raise ScopeDenied()
                if record.generation is None or record.generation.value != manifest['visible_generation']: continue
                index = data.get('chunk_index')
                if (type(index) is not int or not start <= index < end or index in selected
                    or data.get('embedding_model_id') != model.model_id
                    or normalize_model_revision(data.get('embedding_revision')) != normalize_model_revision(model.revision)): raise Conflict()
                selected[index] = KnowledgeChunk(**reference, chunk_index=index, filename=data.get('filename',''),
                    content=data['content'], location=data.get('location',{}))
            if page.next_cursor is None: break
            if page.next_cursor in seen: raise Conflict()
            seen.add(page.next_cursor); cursor = page.next_cursor
        if len(selected) != end-start: raise Conflict()
        result.extend(selected[index] for index in range(start,end))
    return total, result


class KnowledgeChunksService(PublishedKnowledgeReader):
    operation_name = 'knowledge-chunks'

    async def chunks(self, request, actor, *, context=None):
        if not isinstance(request, KnowledgeChunks): raise InvalidInput()
        context = context or OperationContext('knowledge-chunks-'+uuid4().hex,monotonic()+self.operation_seconds)
        threshold = context.remaining()
        try:
            async with asyncio.timeout(threshold):
                grant = await self._grant(request,actor)
                resource = grant.knowledge_bases[0]
                metadata = await self.models.get(resource.embedding_model_id,actor)
                if metadata.model_id != resource.embedding_model_id or metadata.model_type not in {'embedding','multi_embedding'}: raise Conflict()
                model = ModelVersion(model_id=metadata.model_id,revision=metadata.revision)
                dimensions = await self.models.embedding_dimensions(model,actor)
                with self.ports(actor,grant,dimensions,context=context) as (records,ports):
                    vectors = ports[resource.collection]
                    _scope(records,actor); _scope(vectors,actor)
                    revision,_ = await self._blocking(_snapshot,records,request.knowledge_id,0,context=context)
                    if request.expected_data_revision is not None and request.expected_data_revision != revision: raise Conflict()
                    total,chunks = await self._blocking(_window,records,vectors,request,resource,model,context=context)
                    if await self._grant(request,actor) != grant: raise Conflict()
                    await self.models.embedding_dimensions(model,actor)
                    final,_ = await self._blocking(_snapshot,records,request.knowledge_id,0,context=context)
                    if final != revision: raise Conflict()
                next_offset = request.offset+len(chunks) if request.offset+len(chunks) < total else None
                return KnowledgeChunksResult(knowledge_id=request.knowledge_id,knowledge_revision=resource.revision,
                    data_revision=revision,embedding_model=model,total=total,chunks=chunks,next_offset=next_offset)
        except (TimeoutError,DeadlineExceeded) as error:
            logger.warning('knowledge_chunks_timeout operation_id=%s phase=read threshold_seconds=%s exception_type=%s',
                context.operation_id,threshold,type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
