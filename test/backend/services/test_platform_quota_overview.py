# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PLATFORM-QUOTA-OVERVIEW-01 preserves the four original overview scenarios."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal
from test.backend.services.test_cleanse_jobs import context

GB = 1024 ** 3


@pytest.fixture
def overview(mocker):
    from management.services.knowledge_base import platform_quota as module

    snapshot = {'capacity_bytes': 100 * GB, 'tenants': [
        {'tenant_id': 'managed', 'tenant_name': 'Managed', 'hard_limit_bytes': 40 * GB},
        {'tenant_id': 'legacy', 'tenant_name': 'legacy', 'hard_limit_bytes': None},
    ]}
    reader = SimpleNamespace(read=Mock(return_value=snapshot), authorize=Mock(return_value=('SU',)))
    usage = SimpleNamespace(read=AsyncMock(return_value=(('SU',), {
        'total_bytes': 10 * GB, 'warning_enabled': True, 'tenant_warning_level': 'normal'})))

    async def blocking(name, action, *args, **kwargs):
        assert kwargs.pop('lane') == 'control-io' and kwargs.pop('owner') == 'management.knowledge_base'
        return action(*args, **kwargs)

    mocker.patch.object(module, 'run_blocking', side_effect=blocking)
    service = module.PlatformQuotaOverview(reader=reader, usage=usage)
    actor = ServicePrincipal('actual-admin', 'actual-tenant')
    return SimpleNamespace(**locals())


async def test_platform_overview_marks_legacy_unmanaged_tenants(overview):
    s = overview
    result = await s.service.read(s.actor, context=context())
    assert result['remaining_allocatable_bytes'] == 60 * GB
    assert result['allocation_percentage'] == 40
    assert result['unmanaged_tenant_count'] == 1
    assert result['capacity_management_enforced'] is False
    assert [row['tenant_id'] for row in result['tenants']] == ['managed', 'legacy']
    assert all(c.args[1] == s.actor and c.kwargs['force_refresh'] is True for c in s.usage.read.await_args_list)
    s.reader.authorize.assert_called_once()


async def test_platform_overview_respects_tenant_warning_switch(overview):
    s = overview
    s.snapshot['capacity_bytes'] = None
    s.snapshot['tenants'][:] = [{'tenant_id': 'managed', 'tenant_name': 'Managed', 'hard_limit_bytes': 100 * GB}]
    s.usage.read.return_value = (('SU',), {'total_bytes': 90 * GB, 'warning_enabled': False,
                                        'tenant_warning_level': 'critical'})
    result = await s.service.read(s.actor, context=context())
    assert result['tenants'][0]['warning_enabled'] is False
    assert result['tenants'][0]['warning_level'] == 'normal'


async def test_platform_overview_tolerates_tenant_usage_failure(overview):
    s = overview
    s.usage.read.side_effect = [RuntimeError('usage failed'), (('SU',), {'total_bytes': 5})]
    result = await s.service.read(s.actor, context=context())
    assert result['tenants'][0]['actual_bytes'] == 0
    assert result['tenants'][0]['warning_enabled'] is False
    assert result['tenants'][0]['warning_level'] == 'normal'
    assert result['tenants'][1]['actual_bytes'] == 5 and s.usage.read.await_count == 2


async def test_platform_overview_aggregates_available_es_physical_usage(overview):
    s = overview
    s.usage.read.side_effect = [
        (('SU',), {'total_bytes': 10 * GB, 'es_physical_bytes': 2 * GB}),
        (('SU',), {'total_bytes': 5 * GB, 'es_physical_bytes': 3 * GB}),
    ]
    result = await s.service.read(s.actor, context=context())
    assert result['total_es_physical_bytes'] == 5 * GB
    assert [row['es_physical_bytes'] for row in result['tenants']] == [2 * GB, 3 * GB]
    assert result['total_actual_bytes'] == 15 * GB


@pytest.mark.parametrize('error', [ScopeDenied(), Conflict(), DeadlineExceeded()])
async def test_refusal_and_deadline_are_never_reported_as_zero_usage(overview, error):
    s = overview
    s.usage.read.side_effect = error
    with pytest.raises(type(error)):
        await s.service.read(s.actor, context=context())
    assert s.usage.read.await_count == 1


async def test_revocation_before_response_is_rejected(overview):
    s = overview
    s.reader.authorize.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        await s.service.read(s.actor, context=context())


async def test_cancellation_closes_pending_tenant_read(overview):
    s = overview
    closed = []

    async def stalled(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    s.usage.read.side_effect = stalled
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(.02):
            await s.service.read(s.actor, context=context())
    assert closed == [True] and s.usage.read.await_count == 1


@pytest.mark.parametrize('capacity', [None, 0])
async def test_capacity_missing_and_zero_preserve_nullable_percentages(overview, capacity):
    s = overview
    s.snapshot['capacity_bytes'] = capacity
    result = await s.service.read(s.actor, context=context())
    assert result['oversubscription_ratio'] is result['allocation_percentage'] is None
    assert result['remaining_allocatable_bytes'] == (None if capacity is None else 0)
