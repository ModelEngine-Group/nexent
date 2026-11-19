# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Describe authorized physical collections without inference, writes or body access."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_collections import (
    KnowledgeCollectionDescription,
    KnowledgeCollectionMetrics,
    KnowledgeCollectionsAuthorization,
    KnowledgeCollectionsDescribe,
    KnowledgeCollectionsDescribed,
    KnowledgeCollectionsGrant,
    KnowledgeModelDisplay,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    OperationContext,
    VectorCollectionInfo,
    VectorCollectionStatistics,
    VectorSummaryField,
)
from pydantic import ValidationError
from runtime.knowledge_base.worker import cancellable_context
from runtime.model.display import knowledge_model_display

from infrastructure.knowledge_collection_metadata import (
    collection_metadata_vector_ports,
)

logger = logging.getLogger(__name__)
SUMMARY_FIELDS = tuple(VectorSummaryField(name, (('location', 'nexent_public_chunk_v1', field), ('location', field)))
    for name, field in (('source', 'path_or_url'), ('processor', 'process_source'), ('model', 'embedding_model_name')))
STATISTICS_ERRORS = {Unavailable: 'unavailable', Conflict: 'conflict', NotFound: 'not_found',
                     CapabilityUnsupported: 'unsupported', InvalidInput: 'invalid_input'}


def _metrics(result, collection, context):
    if not isinstance(result, VectorCollectionStatistics) or result.collection != collection:
        raise Unavailable(operation_id=context.operation_id)
    fields = {field.name: field for field in result.summaries}
    if len(result.summaries) != 3 or set(fields) != {'source', 'processor', 'model'}:
        raise Unavailable(operation_id=context.operation_id)
    try:
        return KnowledgeCollectionMetrics(record_count=result.record_count, size_bytes=result.size_bytes,
            created_at_ms=result.created_at_ms, query_count=result.query_count, cache_hit_count=result.cache_hit_count,
            source_count=fields['source'].distinct_count,
            process_source=next(iter(fields['processor'].top_values), ''),
            embedding_model_name=next(iter(fields['model'].top_values), ''))
    except ValidationError as error:
        raise Unavailable(operation_id=context.operation_id) from error


class KnowledgeCollectionMetadataService:
    def __init__(self, client, *, ports=collection_metadata_vector_ports, display=knowledge_model_display, operation_seconds=30):
        if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 180:
            raise InvalidInput()
        self.client, self.ports, self.seconds = client, ports, operation_seconds
        self.display = display

    async def _grant(self, request, actor):
        grant = await self.client.authorize_collection_metadata(KnowledgeCollectionsAuthorization(
            knowledge_ids=request.knowledge_ids, view=request.view), actor.user_id, actor.tenant_id)
        if (not isinstance(grant, KnowledgeCollectionsGrant)
            or {g.knowledge_id for g in grant.knowledge_bases} != set(request.knowledge_ids)):
            raise ScopeDenied()
        grant = KnowledgeCollectionsGrant.model_validate(grant.model_dump())
        if any(request.expected_revisions[g.knowledge_id] != g.revision for g in grant.knowledge_bases):
            raise Conflict()
        return grant

    def _read(self, request, actor, grant, *, context):
        resources = {item.knowledge_id: item for item in grant.knowledge_bases}
        result = []
        for key in request.knowledge_ids:
            context.remaining()
            resource = resources[key]
            with self.ports(actor, resource, context=context) as vectors:
                scope = vectors.scope
                if (scope.service_role != 'runtime' or scope.system or scope.resource_prefix
                    or scope.tenant_id != resource.resource_tenant_id or scope.actor_id != actor.user_id
                    or scope.namespaces != {resource.collection}):
                    raise ScopeDenied()
                present = vectors.collection_exists(resource.collection, context=context)
                if type(present) is not bool:
                    raise Unavailable(operation_id=context.operation_id)
                values = {}
                if present:
                    info = vectors.describe_collection(resource.collection, context=context)
                    if not isinstance(info, VectorCollectionInfo) or info.collection != resource.collection:
                        raise Unavailable(operation_id=context.operation_id)
                    values.update(dimensions=info.dimensions, metric=info.metric)
                    if request.include_statistics:
                        try:
                            values['statistics'] = _metrics(vectors.statistics(resource.collection, SUMMARY_FIELDS,
                                                                              context=context), resource.collection, context)
                        except tuple(STATISTICS_ERRORS) as error:
                            values['statistics_error'] = next(code for kind, code in STATISTICS_ERRORS.items()
                                                             if isinstance(error, kind))
                        display = self.display(actor, resource, context=context)
                        if not isinstance(display, KnowledgeModelDisplay):
                            raise Unavailable(operation_id=context.operation_id)
                        values['model_display'] = display
                try:
                    result.append(KnowledgeCollectionDescription(knowledge_id=key, expected_revision=resource.revision,
                                                                present=present, **values))
                except ValidationError as error:
                    raise Unavailable(operation_id=context.operation_id) from error
        return KnowledgeCollectionsDescribed(items=result)

    async def describe(self, request, actor, *, context=None):
        if type(request) is not KnowledgeCollectionsDescribe:
            raise InvalidInput()
        request = KnowledgeCollectionsDescribe.model_validate(request.model_dump())
        context = context or OperationContext('knowledge-collection-describe-' + uuid4().hex, monotonic() + self.seconds)
        context, cancelled = cancellable_context(context)
        try:
            async with asyncio.timeout(context.remaining()):
                grant = await self._grant(request, actor)
                result = await run_blocking('knowledge-collection-describe', self._read, request, actor, grant,
                    context=context, lane='control-io', owner='runtime.knowledge_base')
                if await self._grant(request, actor) != grant:
                    raise Conflict()
                context.remaining()
                return result
        except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
            logger.warning('knowledge_collection_describe_timeout operation_id=%s phase=metadata threshold_seconds=%s exception_type=%s',
                           context.operation_id, self.seconds, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        finally:
            cancelled.set()
