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
    RecordQuery,
    Sort,
)

from infrastructure.agent_model_config import normalize_model_revision
from infrastructure.knowledge_runtime import knowledge_search_ports
from infrastructure.rdb.knowledge_jobs import FILES, JOBS

logger = logging.getLogger(__name__)


def _snapshot(records, knowledge_id, limit, *, context):
    """Hash every visible manifest and reservoir-sample files with bounded memory."""
    digest = hashlib.sha256(str(knowledge_id).encode())
    selected, count, after = [], 0, None
    while True:
        terms = [Comparison('knowledge_id', 'eq', knowledge_id)]
        if after is not None:
            terms.append(Comparison('record_id', 'gt', after))
        page = records.query(FILES, RecordQuery(where=Junction('and', tuple(terms)),
            order_by=(Sort('record_id'),)), PageRequest(limit=500), context=context)
        for row in page.items:
            if row['knowledge_id'] != knowledge_id:
                raise ScopeDenied()
            key = row['record_id']
            if after is not None and key <= after:
                raise Conflict()
            after = key
            version = row['visible_version']
            if version is None or version <= row['tombstone_version']:
                continue
            if not row['visible_generation'] or not row['visible_job_id']:
                raise Conflict()
            digest.update(json.dumps([row['file_id'], version, row['visible_generation'],
                                      row['visible_job_id']], separators=(',', ':')).encode())
            count += 1
            if len(selected) < limit:
                selected.append(row)
            elif limit:
                index = random.randrange(count)
                if index < limit:
                    selected[index] = row
        if len(page.items) < 500:
            return digest.hexdigest(), selected


def _document(records, vectors, resource, manifest, model, *, context):
    job = records.get(JOBS, manifest['visible_job_id'], context=context)
    if (job is None or job['operation'] != 'upload' or job['status'] != 'completed'
        or job['knowledge_id'] != resource.knowledge_id or job['file_id'] != manifest['file_id']
        or job['file_version'] != manifest['visible_version'] or not job['writer_ended']
        or job['reconcile_required'] or job['attempt_id'] != manifest['visible_generation']
        or type(job['chunk_count']) is not int or job['chunk_count'] < 0):
        raise Conflict()
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


class KnowledgeSampleService:
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

    @staticmethod
    async def _blocking(method, *args, context):
        def execute():
            context.remaining()
            result = method(*args, context=context)
            context.remaining()
            return result
        return await run_blocking('knowledge-sample', execute, lane='control-io', owner='runtime.knowledge_base')

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
