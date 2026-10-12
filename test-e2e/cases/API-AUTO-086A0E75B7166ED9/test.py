'''D2 contract test for quota source-only metering and es_physical_* observability.

Verifies the serialization contract of tenant usage, platform overview and
personal KB capacity endpoints against frontend/types/quota.ts, and confirms
that es_physical_* fields are observability-only and never folded into quota
metering arithmetic.
'''

from __future__ import annotations

from typing import Any

import pytest

from shared.http import assert_status, client


def _optional_int(value: Any, field_path: str) -> None:
    assert value is None or type(value) is int, (
        f'{field_path} must be int or null, got {value!r}'
    )
    if type(value) is int:
        assert value >= 0, f'{field_path} must be non-negative, got {value!r}'


def _optional_str(value: Any, field_path: str) -> None:
    assert value is None or isinstance(value, str), (
        f'{field_path} must be str or null, got {value!r}'
    )


def _number_or_none(value: Any, field_path: str) -> None:
    assert value is None or (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    ), f'{field_path} must be number or null, got {value!r}'


@pytest.mark.stage('D2')
@pytest.mark.case_id('API-AUTO-086A0E75B7166ED9')
@pytest.mark.asyncio
async def test_quota_source_only_es_physical_observability_contract(
    super_admin,
    tenant_a_admin,
    tenant_a_user,
    tenant_b_admin,
):
    tenant_id = tenant_a_admin.tenant_id
    assert tenant_id

    async with client('config', token=tenant_a_admin.access_token) as api:
        usage_resp = await api.get(
            f'/tenants/{tenant_id}/quota/usage',
            params={'detail': 'true', 'force_refresh': 'true'},
        )
    assert_status(usage_resp, 200)
    usage = usage_resp.json()

    assert type(usage['total_bytes']) is int and usage['total_bytes'] >= 0
    _optional_str(usage['total_readable'], 'usage.total_readable')
    _optional_int(usage['es_physical_bytes'], 'usage.es_physical_bytes')
    _optional_str(usage['es_physical_readable'], 'usage.es_physical_readable')
    _optional_int(usage['hard_limit_bytes'], 'usage.hard_limit_bytes')
    _optional_str(usage['hard_limit_readable'], 'usage.hard_limit_readable')
    _optional_int(usage['available_bytes'], 'usage.available_bytes')
    _optional_str(usage['available_readable'], 'usage.available_readable')
    _number_or_none(usage['usage_pct'], 'usage.usage_pct')

    breakdown = usage['breakdown']
    assert isinstance(breakdown, list)
    for item in breakdown:
        assert type(item['actual_bytes']) is int and item['actual_bytes'] >= 0
        _optional_str(item['actual_readable'], 'breakdown.actual_readable')
        _optional_int(item['es_physical_bytes'], 'breakdown.es_physical_bytes')
        _optional_str(item['es_physical_readable'], 'breakdown.es_physical_readable')
        soft = item['soft_quota_bytes']
        _optional_int(soft, 'breakdown.soft_quota_bytes')
        if soft is not None and soft > 0:
            assert item['usage_pct'] == round(item['actual_bytes'] / soft * 100, 2)
        else:
            assert item['usage_pct'] is None

    hard = usage['hard_limit_bytes']
    total = usage['total_bytes']
    if hard is not None and hard > 0:
        assert usage['usage_pct'] == round(total / hard * 100, 2)
        assert usage['available_bytes'] == max(0, hard - total)
    else:
        assert usage['usage_pct'] is None
        assert usage['available_bytes'] is None

    async with client('config', token=super_admin.access_token) as api:
        overview_resp = await api.get('/platform/quota/overview')
    assert_status(overview_resp, 200)
    overview = overview_resp.json()

    _optional_int(overview['total_es_physical_bytes'], 'overview.total_es_physical_bytes')
    _optional_str(overview['total_es_physical_readable'], 'overview.total_es_physical_readable')
    assert type(overview['total_actual_bytes']) is int and overview['total_actual_bytes'] >= 0
    tenants = overview['tenants']
    assert isinstance(tenants, list)
    total_es = 0
    total_actual = 0
    for entry in tenants:
        _optional_int(entry['es_physical_bytes'], 'tenant.es_physical_bytes')
        _optional_str(entry['es_physical_readable'], 'tenant.es_physical_readable')
        assert type(entry['actual_bytes']) is int and entry['actual_bytes'] >= 0
        _optional_int(entry['hard_limit_bytes'], 'tenant.hard_limit_bytes')
        total_es += entry['es_physical_bytes'] or 0
        total_actual += entry['actual_bytes']
        tenant_hard = entry['hard_limit_bytes']
        if tenant_hard is not None and tenant_hard > 0:
            assert entry['usage_pct'] == round(entry['actual_bytes'] / tenant_hard * 100, 2)
        else:
            assert entry['usage_pct'] is None
    assert overview['total_es_physical_bytes'] == total_es
    assert overview['total_actual_bytes'] == total_actual

    async with client('config', token=tenant_a_admin.access_token) as api:
        me_resp = await api.get('/capacity/personal/me')
        users_resp = await api.get(
            '/capacity/personal/users', params={'page': 1, 'page_size': 20}
        )
        summary_resp = await api.get('/capacity/personal/summary')
    assert_status(me_resp, 200)
    assert_status(users_resp, 200)
    assert_status(summary_resp, 200)

    me = me_resp.json()
    assert type(me['used_bytes']) is int and me['used_bytes'] >= 0
    _optional_int(me['es_physical_bytes'], 'me.es_physical_bytes')
    _optional_str(me['es_physical_readable'], 'me.es_physical_readable')
    _optional_int(me['quota_bytes'], 'me.quota_bytes')
    quota = me['quota_bytes']
    used = me['used_bytes']
    if quota is not None:
        if quota <= 0 and used > 0:
            assert me['usage_rate'] == 100.0
        elif quota > 0:
            assert me['usage_rate'] == round(used / quota * 100, 2)
        else:
            assert me['usage_rate'] == 0.0
        assert me['is_over_quota'] == (used > quota)
    else:
        assert me['usage_rate'] is None
        assert me['is_over_quota'] is False

    users = users_resp.json()
    items = users['items']
    assert isinstance(items, list)
    for entry in items:
        assert type(entry['total_bytes']) is int and entry['total_bytes'] >= 0
        _optional_int(entry['es_physical_bytes'], 'users.items.es_physical_bytes')
        _optional_str(entry['es_physical_readable'], 'users.items.es_physical_readable')

    summary = summary_resp.json()
    assert type(summary['total_bytes']) is int and summary['total_bytes'] >= 0
    _optional_int(summary['total_es_physical_bytes'], 'summary.total_es_physical_bytes')
    _optional_str(summary['total_es_physical_readable'], 'summary.total_es_physical_readable')

    other_tenant_id = tenant_b_admin.tenant_id
    if other_tenant_id and other_tenant_id != tenant_id:
        async with client('config', token=tenant_a_user.access_token) as api:
            forbidden = await api.get(f'/tenants/{other_tenant_id}/quota/usage')
        assert_status(forbidden, 403)

    async with client('config', token=tenant_a_admin.access_token) as api:
        admin_overview = await api.get('/platform/quota/overview')
    assert_status(admin_overview, 403)
