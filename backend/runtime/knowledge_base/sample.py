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
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.knowledge_chunk_projection import public_chunk_value
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import OperationContext
from runtime.knowledge_base.chunk_view import ChunkReadView, validate_read_ports
from runtime.knowledge_base.publication import published_files, published_job

from infrastructure.agent_model_config import normalize_model_revision
from infrastructure.knowledge_runtime import knowledge_search_ports

logger = logging.getLogger(__name__)


def _snapshot(records, knowledge_id, *, context):
    """Hash every visible manifest and the stable confirmed-change epoch."""
    view = ChunkReadView(records, knowledge_id, context=context)
    digest = hashlib.sha256(json.dumps([knowledge_id, view.version], separators=(",", ":")).encode())
    for row in published_files(records, knowledge_id, context=context):
        digest.update(json.dumps([row['file_id'], row['visible_version'], row['visible_generation'],
                                  row['visible_job_id']], separators=(',', ':')).encode())
    view.stable(context=context)
    return digest.hexdigest()



def _sample_chunk(record, model, *, allow_unbound=False):
    data = record.payload
    if record.vector:
        if not allow_unbound and (data.get('embedding_model_id') != model.model_id
            or normalize_model_revision(data.get('embedding_revision')) != normalize_model_revision(model.revision)):
            raise Conflict()
    elif data.get('embedding_model_id') is not None:
        raise Conflict()
    return KnowledgeSampleChunk(chunk_id=record.key.key, chunk_index=data.get('chunk_index'), content=data['content'],
        embedding=list(record.vector) if record.vector else None, location=data.get('location', {}))


def _sample_documents(records, vectors, resource, model, limit, *, context):
    view = ChunkReadView(records, resource.knowledge_id, context=context)
    selected, count = [], 0

    def select(item):
        nonlocal count
        count += 1
        if len(selected) < limit:
            selected.append(item)
        else:
            index = random.randrange(count)
            if index < limit:
                selected[index] = item

    for manifest in published_files(records, resource.knowledge_id, context=context):
        job = published_job(records, resource, manifest, context=context)
        if view.file_count(manifest, job, context=context):
            select((manifest, job, None, None))
    standalone_count = view.standalone_count(context=context)
    groups = {}
    if standalone_count:
        rows = view.standalone_records(vectors, resource, 0, standalone_count, context=context, include_vectors=True)
        for record in rows:
            path = record.payload.get('location', {}).get('path_or_url')
            path = path if isinstance(path, str) and path else None
            identity = ['path', path] if path is not None else ['chunk', record.key.key]
            key = hashlib.sha256(json.dumps([resource.knowledge_id, *identity], separators=(',', ':')).encode()).hexdigest()
            groups.setdefault((key, path), []).append(record)
        for (key, path), rows in groups.items():
            select((None, None, (key, path), rows))
    documents = []
    for manifest, job, independent, rows in selected:
        reference = None
        if manifest is not None:
            file_count = view.file_count(manifest, job, context=context)
            rows = view.file_records(vectors, resource, manifest, job, 0, file_count, context=context, include_vectors=True)
            reference = KnowledgeFileReference(knowledge_id=resource.knowledge_id, file_id=manifest['file_id'],
                                                file_version=manifest['visible_version'])
        documents.append(KnowledgeSampleDocument(file_ref=reference,
            standalone_key=independent[0] if independent else None, path_or_url=independent[1] if independent else None,
            filename=public_chunk_value(rows[0].payload.get('location', {}), 'filename', rows[0].payload.get('filename', '')),
            chunks=[_sample_chunk(row, model, allow_unbound=bool(row.vector)
                and row.payload.get('embedding_model_id') is None and row.payload.get('embedding_revision') is None
                and view.has_manual_create(row, context=context)) for row in rows]))
    view.stable(context=context)
    return documents


class PublishedKnowledgeReader:
    operation_name = 'knowledge-sample'

    def __init__(self, authorization_client, models, *, ports=knowledge_search_ports, operation_seconds=180):
        if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 180:
            raise InvalidInput()
        self.client, self.models, self.ports, self.operation_seconds = authorization_client, models, ports, operation_seconds

    async def _grant(self, request, actor):
        grant = await self.client.authorize_knowledge_search(
            KnowledgeSearchAuthorization(knowledge_ids=[request.knowledge_id]), actor.user_id, actor.tenant_id)
        if (len(grant.knowledge_bases) != 1 or grant.knowledge_bases[0].knowledge_id != request.knowledge_id
            or grant.knowledge_bases[0].resource_tenant_id not in {actor.tenant_id, ASSET_OWNER_TENANT_ID}):
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
                    validate_read_ports(records, vectors, grant, actor)
                    records = records[request.knowledge_id]
                    revision = await self._blocking(_snapshot, records, request.knowledge_id, context=context)
                    documents = await self._blocking(_sample_documents, records, vectors[resource.collection], resource,
                                                    model, request.document_limit, context=context)
                    if await self._grant(request, actor) != grant:
                        raise Conflict()
                    await self.models.embedding_dimensions(model, actor)
                    final = await self._blocking(_snapshot, records, request.knowledge_id, context=context)
                    if final != revision:
                        raise Conflict()
                    return KnowledgeSampleResult(knowledge_id=request.knowledge_id, knowledge_revision=resource.revision,
                        data_revision=revision, embedding_model=model, documents=documents)
        except (TimeoutError, DeadlineExceeded) as error:
            logger.warning('knowledge_sample_timeout operation_id=%s threshold_seconds=%s exception_type=%s',
                           context.operation_id, threshold, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
