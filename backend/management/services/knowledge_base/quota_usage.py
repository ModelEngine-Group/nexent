# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read public tenant usage using SI accounting and signed AgentOS statistics."""

import logging
import time

from contracts.constants import environment
from management.services.knowledge_base.collection_statistics import (
    collection_usage_statistics,
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

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient

logger = logging.getLogger(__name__)


class TenantQuotaUsage:
    def __init__(self, *, reader=None, client=None):
        self.reader = reader or TenantQuotaUsageReader()
        self.client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)

    async def _blocking(self, phase, action, *args, context):
        return await run_blocking('tenant-quota-usage-' + phase, action, *args, context=context,
                                  lane='control-io', owner='management.knowledge_base')


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
                observed = await collection_usage_statistics(self.client, actor, rows, context)
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
