# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Project only physical quota counters; no body, model or credential access."""

from contracts.knowledge_collections import (
    KnowledgeCollectionsUsage,
    KnowledgeCollectionsUsageResult,
    KnowledgeCollectionUsage,
    KnowledgeUsageMetrics,
)
from nexent.storage.errors import ScopeDenied, Unavailable
from nexent.storage.models import VectorCollectionStatistics
from pydantic import ValidationError
from runtime.knowledge_base.collection_metadata import (
    STATISTICS_ERRORS,
    SUMMARY_FIELDS,
    KnowledgeCollectionMetadataService,
)

from infrastructure.knowledge_collection_metadata import (
    collection_metadata_vector_ports,
)


class KnowledgeCollectionUsageService(KnowledgeCollectionMetadataService):
    def __init__(
        self, client, *, ports=collection_metadata_vector_ports, operation_seconds=30
    ):
        super().__init__(
            client, ports=ports, display=None, operation_seconds=operation_seconds
        )

    def _read(self, request, actor, grant, *, context):
        resources = {item.knowledge_id: item for item in grant.knowledge_bases}
        result = []
        for key in request.knowledge_ids:
            context.remaining()
            resource = resources[key]
            with self.ports(actor, resource, context=context) as vectors:
                scope = vectors.scope
                if (
                    scope.service_role != "runtime"
                    or scope.system
                    or scope.resource_prefix
                    or scope.tenant_id != resource.resource_tenant_id
                    or scope.actor_id != actor.user_id
                    or scope.namespaces != {resource.collection}
                ):
                    raise ScopeDenied()
                present = vectors.collection_exists(
                    resource.collection, context=context
                )
                if type(present) is not bool:
                    raise Unavailable()
                values = {}
                if present:
                    try:
                        stats = vectors.statistics(
                            resource.collection, (SUMMARY_FIELDS[0],), context=context
                        )
                        if (
                            not isinstance(stats, VectorCollectionStatistics)
                            or stats.collection != resource.collection
                            or len(stats.summaries) != 1
                            or stats.summaries[0].name != "source"
                        ):
                            raise Unavailable()
                        values["statistics"] = KnowledgeUsageMetrics(
                            record_count=stats.record_count,
                            size_bytes=stats.size_bytes,
                            source_count=stats.summaries[0].distinct_count,
                        )
                    except tuple(STATISTICS_ERRORS) as error:
                        values["statistics_error"] = next(
                            code
                            for kind, code in STATISTICS_ERRORS.items()
                            if isinstance(error, kind)
                        )
                    except ValidationError as error:
                        raise Unavailable() from error
                result.append(
                    KnowledgeCollectionUsage(
                        knowledge_id=key,
                        expected_revision=resource.revision,
                        present=present,
                        **values,
                    )
                )
        return KnowledgeCollectionsUsageResult(items=result)

    async def describe(self, request, actor, *, context=None):
        return await self._describe(
            request, actor, KnowledgeCollectionsUsage, context=context
        )
