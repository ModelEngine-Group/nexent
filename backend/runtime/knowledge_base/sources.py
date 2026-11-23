# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded physical source summaries use current read grants, SI and no inference."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import (
    KnowledgeChunksAuthorization,
    KnowledgeChunksGrant,
)
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from contracts.knowledge_sources import (
    KnowledgeSources,
    KnowledgeSourcesResult,
    KnowledgeSourceSummary,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    Comparison,
    OperationContext,
    VectorGroup,
    VectorGroupQuery,
    VectorSummaryField,
)
from runtime.knowledge_base.worker import cancellable_context

from infrastructure.knowledge_sources import knowledge_source_ports
from infrastructure.vdb.native_knowledge import native_source_groups

logger = logging.getLogger(__name__)


def _paths(name):
    return (("location", PUBLIC_CHUNK_SOURCE_KEY, name), ("location", name))


def _query(limit):
    return VectorGroupQuery(
        VectorSummaryField("source", _paths("path_or_url")),
        (
            VectorSummaryField("path", _paths("path_or_url")),
            VectorSummaryField(
                "filename",
                (("location", PUBLIC_CHUNK_SOURCE_KEY, "filename"), ("filename",)),
            ),
            VectorSummaryField("size", _paths("file_size")),
            VectorSummaryField("created", _paths("create_time")),
        ),
        limit,
    )


class KnowledgeSourcesService:
    def __init__(self, client, *, ports=knowledge_source_ports, operation_seconds=30):
        if (
            type(operation_seconds) not in {int, float}
            or not 0 < operation_seconds <= 180
        ):
            raise InvalidInput()
        self.client, self.ports, self.seconds = client, ports, operation_seconds

    async def _grant(self, request, actor):
        grant = await self.client.authorize_knowledge_chunks(
            KnowledgeChunksAuthorization(knowledge_id=request.knowledge_id),
            actor.user_id,
            actor.tenant_id,
        )
        if (
            not isinstance(grant, KnowledgeChunksGrant)
            or grant.knowledge_id != request.knowledge_id
            or grant.resource_tenant_id not in {actor.tenant_id, ASSET_OWNER_TENANT_ID}
        ):
            raise ScopeDenied()
        grant = KnowledgeChunksGrant.model_validate(grant.model_dump())
        if grant.revision != request.expected_revision:
            raise Conflict()
        return grant

    def _managed_groups(self, request, actor, grant, *, context):
        context.remaining()
        with self.ports(actor, grant, context=context) as vectors:
            scope = vectors.scope
            if (
                scope.system
                or scope.resource_prefix
                or scope.service_role != "runtime"
                or scope.actor_id != actor.user_id
                or scope.tenant_id != grant.resource_tenant_id
                or scope.namespaces != {grant.collection}
            ):
                raise ScopeDenied()
            present = vectors.collection_exists(grant.collection, context=context)
            if type(present) is not bool:
                raise Unavailable()
            values = (
                vectors.group(
                    grant.collection,
                    _query(request.limit),
                    where=Comparison("knowledge_id", "eq", request.knowledge_id),
                    context=context,
                )
                if present
                else ()
            )
            return present, values

    def _read(self, request, actor, grant, *, context):
        if request.native_documents:
            present, values = native_source_groups(actor, grant, request.limit, context=context)
        else:
            present, values = self._managed_groups(request, actor, grant, context=context)
        try:
            if not isinstance(values, tuple) or len(values) > request.limit:
                raise ValueError("Invalid source groups")
            sources = []
            for value in values:
                if not isinstance(value, VectorGroup):
                    raise TypeError("Invalid source group")
                if value.collection != grant.collection:
                    raise ScopeDenied()
                data = value.sample
                if not isinstance(data, dict) or not data.keys() <= {
                    "path",
                    "filename",
                    "size",
                    "created",
                }:
                    raise ValueError("Invalid sample")
                sources.append(
                    KnowledgeSourceSummary(
                        source_key=value.key,
                        path_or_url=data["path"],
                        filename=data.get("filename", ""),
                        file_size=data.get("size", 0),
                        create_time=data.get("created"),
                        chunk_count=value.count,
                    )
                )
            result = KnowledgeSourcesResult(
                knowledge_id=request.knowledge_id,
                revision=grant.revision,
                present=present,
                sources=sources,
            )
        except (KeyError, TypeError, ValueError):
            raise Unavailable(operation_id=context.operation_id) from None
        context.remaining()
        return result

    async def list_sources(self, request, actor, *, context=None):
        if not isinstance(request, KnowledgeSources):
            raise InvalidInput()
        request = KnowledgeSources.model_validate(request.model_dump())
        context = context or OperationContext(
            "knowledge-sources-" + uuid4().hex, monotonic() + self.seconds
        )
        context, cancelled = cancellable_context(context)
        try:
            async with asyncio.timeout(context.remaining()):
                grant = await self._grant(request, actor)
                result = await run_blocking(
                    "knowledge-sources",
                    self._read,
                    request,
                    actor,
                    grant,
                    context=context,
                    lane="control-io",
                    owner="runtime.knowledge_base",
                )
                if await self._grant(request, actor) != grant:
                    raise Conflict()
                context.remaining()
                return result
        except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
            logger.warning(
                "knowledge_sources_timeout operation_id=%s phase=sources threshold_seconds=%s exception_type=%s",
                context.operation_id,
                self.seconds,
                type(error).__name__,
            )
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        finally:
            cancelled.set()
