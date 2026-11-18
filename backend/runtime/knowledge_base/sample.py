# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read complete published document samples; summary orchestration stays in Management."""

import asyncio
import hashlib
import json
import logging
import random
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import (
    KnowledgeFileReference,
    KnowledgeSample,
    KnowledgeSampleChunk,
    KnowledgeSampleDocument,
    KnowledgeSampleResult,
    KnowledgeSearchAuthorization,
    ModelVersion,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import (
    Comparison,
    Junction,
    OperationContext,
    PageRequest,
)
from runtime.knowledge_base.publication import published_files, published_job

from infrastructure.agent_model_config import normalize_model_revision
from infrastructure.knowledge_runtime import knowledge_search_ports

logger = logging.getLogger(__name__)


def _snapshot(records, knowledge_id, limit, *, context):
    """Hash every visible manifest and reservoir-sample files with bounded memory."""
    digest = hashlib.sha256(str(knowledge_id).encode())
    selected = []
    for count, row in enumerate(published_files(records, knowledge_id, context=context), start=1):
        digest.update(json.dumps([row['file_id'], row['visible_version'], row['visible_generation'],
                                  row['visible_job_id']], separators=(',', ':')).encode())
        if len(selected) < limit:
            selected.append(row)
        elif limit:
            index = random.randrange(count)
            if index < limit: selected[index] = row
    return digest.hexdigest(), selected



def _document(records, vectors, resource, manifest, model, *, context):
    job = published_job(records, resource, manifest, context=context)
    reference = KnowledgeFileReference(knowledge_id=resource.knowledge_id, file_id=manifest['file_id'],
                                       file_version=manifest['visible_version'])
    where = Junction('and', tuple(Comparison(name, 'eq', value) for name, value in reference.model_dump().items()))
    chunks, cursor, filename = {}, None, None
    while True:
        page = vectors.scan(resource.collection, where, PageRequest(limit=500, cursor=cursor), context=context)
        for record in page.items:
            data = record.payload
            if record.key.collection != resource.collection or any(data.get(k) != v for k, v in reference.model_dump().items()):
                raise ScopeDenied()
            if record.generation is None or record.generation.value != manifest['visible_generation']:
                continue
            if (data.get('embedding_model_id') != model.model_id
                or normalize_model_revision(data.get('embedding_revision')) != normalize_model_revision(model.revision)):
                raise Conflict()
            chunk = KnowledgeSampleChunk(chunk_index=data['chunk_index'], content=data['content'],
                                        embedding=list(record.vector), location=data.get('location', {}))
            if chunk.chunk_index in chunks or chunk.chunk_index >= job['chunk_count']:
                raise Conflict()
            chunks[chunk.chunk_index] = chunk
            actual_name = data.get('filename', '')
            if filename is not None and actual_name != filename:
                raise Conflict()
            filename = actual_name
        if page.next_cursor is None:
            break
        if page.next_cursor == cursor:
            raise Conflict()
        cursor = page.next_cursor
    if len(chunks) != job['chunk_count']:
        raise Conflict()
    return KnowledgeSampleDocument(file_ref=reference, filename=filename or '',
                                   chunks=[chunks[i] for i in range(len(chunks))])


class PublishedKnowledgeReader:
    operation_name = 'knowledge-sample'

    def __init__(self, authorization_client, models, *, ports=knowledge_search_ports, operation_seconds=180):
        if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 180:
            raise InvalidInput()
        self.client, self.models, self.ports, self.operation_seconds = authorization_client, models, ports, operation_seconds

    async def _grant(self, request, actor):
        grant = await self.client.authorize_knowledge_search(
            KnowledgeSearchAuthorization(knowledge_ids=[request.knowledge_id]), actor.user_id, actor.tenant_id)
        if len(grant.knowledge_bases) != 1 or grant.knowledge_bases[0].knowledge_id != request.knowledge_id:
            raise ScopeDenied()
        if grant.knowledge_bases[0].revision != request.expected_revision:
            raise Conflict()
        return grant

    @classmethod
    async def _blocking(cls, method, *args, context):
        def execute():
            context.remaining()
            result = method(*args, context=context)
            context.remaining()
            return result
        return await run_blocking(cls.operation_name, execute, lane='control-io', owner='runtime.knowledge_base')


class KnowledgeSampleService(PublishedKnowledgeReader):
    async def sample(self, request, actor, *, context=None):
        if not isinstance(request, KnowledgeSample):
            raise InvalidInput()
        context = context or OperationContext('knowledge-sample-' + uuid4().hex, monotonic() + self.operation_seconds)
        threshold = context.remaining()
        try:
            async with asyncio.timeout(threshold):
                grant = await self._grant(request, actor)
                resource = grant.knowledge_bases[0]
                metadata = await self.models.get(resource.embedding_model_id, actor)
                if metadata.model_id != resource.embedding_model_id or metadata.model_type != 'embedding':
                    raise Conflict()
                model = ModelVersion(model_id=metadata.model_id, revision=metadata.revision)
                dimensions = await self.models.embedding_dimensions(model, actor)
                with self.ports(actor, grant, dimensions, context=context) as (records, vectors):
                    revision, manifests = await self._blocking(_snapshot, records, request.knowledge_id,
                                                               request.document_limit, context=context)
                    documents = [await self._blocking(_document, records, vectors[resource.collection], resource,
                                 row, model, context=context) for row in manifests]
                    if await self._grant(request, actor) != grant:
                        raise Conflict()
                    await self.models.embedding_dimensions(model, actor)
                    final, _ = await self._blocking(_snapshot, records, request.knowledge_id, 0, context=context)
                    if final != revision:
                        raise Conflict()
                    return KnowledgeSampleResult(knowledge_id=request.knowledge_id, knowledge_revision=resource.revision,
                        data_revision=revision, embedding_model=model, documents=documents)
        except (TimeoutError, DeadlineExceeded) as error:
            logger.warning('knowledge_sample_timeout operation_id=%s threshold_seconds=%s exception_type=%s',
                           context.operation_id, threshold, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
