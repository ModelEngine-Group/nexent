# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""ALLOCATION-RULE-01 preserves finite allocation conflicts and boundaries."""

import pytest
from contracts.errors.exceptions import PlatformQuotaConflictError


def test_tenant_below_usage_preserves_complete_error():
    from management.services.knowledge_base.quota_allocation_rules import (
        validate_tenant_allocation,
    )

    with pytest.raises(PlatformQuotaConflictError) as raised:
        validate_tenant_allocation('target', 10, {'usage_bytes': 20})
    assert str(raised.value) == 'Tenant hard quota cannot be lower than current usage'
    assert raised.value.error == 'TenantQuotaBelowUsage'
    assert raised.value.details == {'tenant_id': 'target', 'requested_limit_bytes': 10,
        'requested_limit_readable': '10 B', 'actual_usage_bytes': 20, 'actual_usage_readable': '20 B'}


def test_current_limit_is_replaced_and_capacity_conflict_preserves_details():
    from management.services.knowledge_base.quota_allocation_rules import (
        validate_tenant_allocation,
    )

    inputs = {'usage_bytes': 20, 'capacity_bytes': 100, 'total_allocated_bytes': 90, 'current_limit_bytes': 50}
    validate_tenant_allocation('target', 60, inputs)
    with pytest.raises(PlatformQuotaConflictError) as raised:
        validate_tenant_allocation('target', 70, inputs)
    assert raised.value.error == 'PlatformCapacityExceeded'
    assert str(raised.value) == 'Tenant hard quota exceeds remaining platform capacity'
    assert raised.value.details == {'tenant_id': 'target', 'requested_limit_bytes': 70,
        'requested_limit_readable': '70 B', 'platform_capacity_bytes': 100, 'platform_capacity_readable': '100 B',
        'total_allocated_bytes': 90, 'total_allocated_readable': '90 B',
        'remaining_allocatable_bytes': 10, 'remaining_allocatable_readable': '10 B'}


@pytest.mark.parametrize('current', [None, 0])
def test_unlimited_platform_and_exact_usage_boundary(current):
    from management.services.knowledge_base.quota_allocation_rules import (
        validate_tenant_allocation,
    )

    validate_tenant_allocation('target', 20, {'usage_bytes': 20, 'capacity_bytes': None,
                                           'current_limit_bytes': current, 'total_allocated_bytes': 999})


def test_platform_capacity_preserves_conflict_details_and_boundary():
    from management.services.knowledge_base.quota_allocation_rules import (
        validate_platform_capacity,
    )

    validate_platform_capacity(20, 20)
    with pytest.raises(PlatformQuotaConflictError) as raised:
        validate_platform_capacity(10, 20)
    assert str(raised.value) == 'Platform capacity cannot be lower than existing tenant allocations'
    assert raised.value.error == 'PlatformCapacityBelowAllocation'
    assert raised.value.details == {'requested_capacity_bytes': 10, 'requested_capacity_readable': '10 B',
                                   'total_allocated_bytes': 20, 'total_allocated_readable': '20 B'}
