# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read public tenant usage using SI accounting and signed AgentOS statistics."""

import logging
import time

from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeUpstreamError
from contracts.knowledge_collections import (
    KnowledgeCollectionsUsage,
    KnowledgeCollectionsUsageResult,
)
from management.services.knowledge_base.quota_formatting import vector_bytes_for_display
from management.services.knowledge_base.quota_usage_read import TenantQuotaUsageReader
from management.services.knowledge_base.usage_cache import (
    CACHE_TTL_SECONDS,
    _usage_cache,
    async_usage_refresh_guard,
    store_usage_cache,
)
from management.services.knowledge_base.usage_projection import project_usage
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OperationCancelled,
    ScopeDenied,
)

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient
from infrastructure.knowledge_search import knowledge_search_revision

logger = logging.getLogger(__name__)


class TenantQuotaUsage:
    def __init__(self, *, reader=None, client=None):
        self.reader = reader or TenantQuotaUsageReader()
        self.client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)

    async def _blocking(self, phase, action, *args, context):
        return await run_blocking('tenant-quota-usage-' + phase, action, *args, context=context,
                                  lane='control-io', owner='management.knowledge_base')

    async def _statistics(self, actor, rows, context):
        selected = [row for row in rows if row.get('index_name') and row.get('knowledge_sources') != 'datamate']
        observed = {}
        for start in range(0, len(selected), 100):
            context.remaining()
            batch = selected[start:start + 100]
            expected = {row['knowledge_id']: knowledge_search_revision(row) for row in batch}
            if len(expected) != len(batch):
                raise Conflict()
            try:
                response = await self.client.knowledge_collection_usage(KnowledgeCollectionsUsage(
                    knowledge_ids=list(expected), expected_revisions=expected), actor.user_id, actor.tenant_id)
            except RuntimeUpstreamError as error:
                kind = {403: ScopeDenied, 409: Conflict}.get(error.status_code)
                if kind is not None:
                    raise kind(operation_id=context.operation_id) from error
                logger.warning('tenant_quota_statistics_unavailable operation_id=%s exception_type=%s',
                               context.operation_id, type(error).__name__)
                continue
            except RuntimeServiceTimeoutError:
                # The AgentOS client already logs its bounded transport timeout.
                context.remaining()
                continue
            except (DeadlineExceeded, OperationCancelled, ScopeDenied, Conflict):
                raise
            except Exception as error:  # noqa: BLE001 - Preserve optional ES observability failure.
                logger.warning('tenant_quota_statistics_unavailable operation_id=%s exception_type=%s',
                               context.operation_id, type(error).__name__)
                continue
            if not isinstance(response, KnowledgeCollectionsUsageResult) or (
                [item.knowledge_id for item in response.items] != list(expected)
                or any(item.expected_revision != expected[item.knowledge_id] for item in response.items)
            ):
                raise Conflict()
            observed.update((item.knowledge_id, item.statistics) for item in response.items)
        context.remaining()
        return observed

    async def read(self, tenant, actor, *, force_refresh=False, detail=False, context):
        await self._blocking('authorize', self.reader.authorize, tenant, actor, context=context)
        async with async_usage_refresh_guard(tenant) as generation:
            context.remaining()
            now = time.time()
            cached = _usage_cache.get(tenant)
            refresh = force_refresh or cached is None or now - cached[0] >= CACHE_TTL_SECONDS
            if refresh:
                inputs = await self._blocking('inputs', self.reader.read, tenant, actor, context=context)
                rows = inputs['knowledge_bases']
                observed = await self._statistics(actor, rows, context)
                details = {}
                for row in rows:
                    index = row.get('index_name')
                    if not index:
                        continue
                    stats = observed.get(row['knowledge_id'])
                    details[index] = {
                        'source_size_bytes': inputs['source_bytes_by_kb'].get(row['knowledge_id'], 0),
                        'store_size_bytes': vector_bytes_for_display(stats.size_bytes) if stats is not None else 0,
                        'doc_count': stats.source_count if stats is not None else 0,
                    }
                storage = {'details': details, 'total_es_bytes': sum(row['store_size_bytes'] for row in details.values())}
                usage = project_usage(rows, storage, inputs['tenant_source_bytes'], inputs, inputs, inputs['summary'])
            else:
                usage = cached[1]
            roles = await self._blocking('authorize', self.reader.authorize, tenant, actor, context=context)
            context.remaining()
            if refresh:
                store_usage_cache(tenant, now, usage, generation)
            result = dict(usage)
            if not detail:
                result.pop('breakdown', None)
            return roles, result
