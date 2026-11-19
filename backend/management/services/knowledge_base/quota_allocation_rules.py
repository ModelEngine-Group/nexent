# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Finite quota decisions and their established public conflict details."""

from contracts.errors.exceptions import PlatformQuotaConflictError
from management.services.knowledge_base.quota_formatting import bytes_to_readable


def validate_tenant_allocation(tenant, limit, inputs):
    used = inputs['usage_bytes']
    if limit < used:
        raise PlatformQuotaConflictError(
            'Tenant hard quota cannot be lower than current usage', 'TenantQuotaBelowUsage',
            {'tenant_id': tenant, 'requested_limit_bytes': limit, 'requested_limit_readable': bytes_to_readable(limit),
             'actual_usage_bytes': used, 'actual_usage_readable': bytes_to_readable(used)},
        )
    capacity = inputs['capacity_bytes']
    if capacity is None:
        return
    allocated = inputs['total_allocated_bytes']
    if allocated - (inputs['current_limit_bytes'] or 0) + limit > capacity:
        remaining = max(capacity - allocated, 0)
        raise PlatformQuotaConflictError(
            'Tenant hard quota exceeds remaining platform capacity', 'PlatformCapacityExceeded',
            {'tenant_id': tenant, 'requested_limit_bytes': limit, 'requested_limit_readable': bytes_to_readable(limit),
             'platform_capacity_bytes': capacity, 'platform_capacity_readable': bytes_to_readable(capacity),
             'total_allocated_bytes': allocated, 'total_allocated_readable': bytes_to_readable(allocated),
             'remaining_allocatable_bytes': remaining, 'remaining_allocatable_readable': bytes_to_readable(remaining)},
        )


def validate_platform_capacity(capacity, allocated):
    if capacity < allocated:
        raise PlatformQuotaConflictError(
            'Platform capacity cannot be lower than existing tenant allocations', 'PlatformCapacityBelowAllocation',
            {'requested_capacity_bytes': capacity, 'requested_capacity_readable': bytes_to_readable(capacity),
             'total_allocated_bytes': allocated, 'total_allocated_readable': bytes_to_readable(allocated)},
        )
