# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Assemble privileged platform quota views from SI and AgentOS tenant usage."""

import logging

from management.services.knowledge_base.platform_quota_read import PlatformQuotaReader
from management.services.knowledge_base.quota_formatting import bytes_to_readable
from management.services.knowledge_base.quota_usage import TenantQuotaUsage
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OperationCancelled,
    ScopeDenied,
)

logger = logging.getLogger(__name__)


class PlatformQuotaOverview:
    def __init__(self, *, reader=None, usage=None):
        self.reader = reader or PlatformQuotaReader()
        self.usage = usage or TenantQuotaUsage()

    async def _blocking(self, phase, action, actor, context):
        return await run_blocking('platform-quota-' + phase, action, actor, context=context,
                                  lane='control-io', owner='management.knowledge_base')

    async def read(self, actor, *, context):
        snapshot = await self._blocking('inputs', self.reader.read, actor, context)
        tenants = []
        for tenant in snapshot['tenants']:
            context.remaining()
            tid, limit = tenant['tenant_id'], tenant['hard_limit_bytes']
            try:
                _, usage = await self.usage.read(tid, actor, force_refresh=True, context=context)
                actual = usage.get('total_bytes', 0)
                es_bytes = usage.get('es_physical_bytes', 0) or 0
                enabled = usage.get('warning_enabled', True)
                level = usage.get('tenant_warning_level', 'normal') if enabled else 'normal'
            except (TimeoutError, DeadlineExceeded, OperationCancelled, ScopeDenied, Conflict):
                raise
            except Exception as error:  # noqa: BLE001 - Preserve the existing per-tenant usage failure behavior.
                logger.warning('platform_quota_tenant_usage_unavailable operation_id=%s tenant_id=%s exception_type=%s',
                               context.operation_id, tid, type(error).__name__)
                actual, es_bytes, enabled, level = 0, 0, False, 'normal'
            tenants.append({
                **tenant, 'hard_limit_readable': bytes_to_readable(limit),
                'actual_bytes': actual, 'actual_readable': bytes_to_readable(actual),
                'es_physical_bytes': es_bytes, 'es_physical_readable': bytes_to_readable(es_bytes),
                'usage_pct': round(actual / limit * 100, 2) if limit and limit > 0 else None,
                'warning_level': level, 'warning_enabled': enabled,
            })
        await self._blocking('authorize', self.reader.authorize, actor, context)
        context.remaining()
        capacity = snapshot['capacity_bytes']
        allocated = sum(row['hard_limit_bytes'] for row in tenants if row['hard_limit_bytes'] is not None)
        unmanaged = sum(row['hard_limit_bytes'] is None for row in tenants)
        actual = sum(row['actual_bytes'] for row in tenants)
        es_bytes = sum(row['es_physical_bytes'] for row in tenants)
        remaining = max(capacity - allocated, 0) if capacity is not None else None
        return {
            'platform_capacity_bytes': capacity, 'platform_capacity_readable': bytes_to_readable(capacity),
            'tenants': tenants, 'total_allocated_bytes': allocated, 'total_allocated_readable': bytes_to_readable(allocated),
            'total_actual_bytes': actual, 'total_actual_readable': bytes_to_readable(actual),
            'total_es_physical_bytes': es_bytes, 'total_es_physical_readable': bytes_to_readable(es_bytes),
            'tenant_count': len(tenants), 'oversubscription_ratio': round(allocated / capacity, 4) if capacity and capacity > 0 else None,
            'remaining_allocatable_bytes': remaining, 'remaining_allocatable_readable': bytes_to_readable(remaining),
            'allocation_percentage': round(allocated / capacity * 100, 2) if capacity and capacity > 0 else None,
            'unmanaged_tenant_count': unmanaged, 'capacity_management_enforced': capacity is not None and unmanaged == 0,
        }
