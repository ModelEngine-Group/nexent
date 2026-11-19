# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""ALLOCATION-READ-01 prepares allocation decisions using real scoped SI."""

from contextlib import contextmanager

import pytest
from nexent.storage.errors import ScopeDenied

from infrastructure import tenant_quota_read as records_module
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_platform_quota_read import platform  # noqa: F401
from test.backend.services.test_tenant_quota_read import quota  # noqa: F401
from test.backend.services.test_tenant_quota_usage_read import usage  # noqa: F401


@pytest.fixture
def allocation(platform, usage):  # noqa: F811
    from management.services.knowledge_base.quota_allocation_read import (
        QuotaAllocationReader,
    )

    s = usage

    @contextmanager
    def ports(actor, *, context, usage_tenant):
        with s.platform_reader.ports(actor, context=context) as (identity, discover, _):
            handles = []

            def records(tenant):
                s.opened.append((actor, tenant))
                port = records_module.bind_tenant_quota_records(actor, tenant, s.engine, usage=tenant == usage_tenant)
                handles.append(port)
                return port

            try:
                yield identity, discover, records
            finally:
                for port in handles:
                    port.close()

    s.allocation = QuotaAllocationReader(ports=ports)
    return s


def test_orphans_counted_first_config_and_virtual_exclusion(allocation):
    s = allocation
    result = s.allocation.read('tenant-a', s.actor, context=context())
    assert result == {'usage_bytes': 36, 'capacity_bytes': 100, 'current_limit_bytes': 20,
                      'total_allocated_bytes': 70, 'hard_limit_editable': False}
    assert all(actor == s.actor for actor, _ in s.opened) and s.closed == [True]


@pytest.mark.parametrize('role', ['SU', 'ASSET_OWNER'])
def test_foreign_scope_keeps_real_actor(allocation, role):
    s = allocation
    s.update('cleanse_accounts', user_roles=[role])
    result = s.allocation.read('tenant-b', s.actor, context=context())
    assert result['usage_bytes'] == 100 and result['current_limit_bytes'] == 50
    assert s.opened[0] == (s.actor, 'tenant-b') and s.actor.tenant_id == 'tenant-a'


def test_admin_can_prepare_own_tenant_but_not_foreign(allocation):
    s = allocation
    s.update('cleanse_accounts', user_roles=['ADMIN'])
    assert s.allocation.read('tenant-a', s.actor, context=context())['usage_bytes'] == 36
    s.opened.clear()
    with pytest.raises(ScopeDenied):
        s.allocation.read('tenant-b', s.actor, context=context())
    assert not s.opened


@pytest.mark.parametrize('role', ['DEV', 'USER', 'OPS'])
def test_non_managers_never_open_catalog_or_discovery(allocation, role):
    s = allocation
    s.update('cleanse_accounts', user_roles=[role])
    with pytest.raises(ScopeDenied):
        s.allocation.read('tenant-a', s.actor, context=context())
    assert not s.opened and not s.discovery_opened


@pytest.mark.parametrize('target', ['cleanse_accounts', 'cleanse_memberships'])
def test_inactive_identity_denied_before_metadata(allocation, target):
    s = allocation
    s.update(target, delete_flag='Y')
    with pytest.raises(ScopeDenied):
        s.allocation.read('tenant-a', s.actor, context=context())
    assert not s.opened


def test_revocation_before_response_refuses_result(allocation, mocker):
    s = allocation
    original, calls = s.allocation._authorize, []

    def authorize(*args):
        calls.append(True)
        if len(calls) == 2:
            s.update('cleanse_memberships', delete_flag='Y')
        return original(*args)

    mocker.patch.object(s.allocation, '_authorize', side_effect=authorize)
    with pytest.raises(ScopeDenied):
        s.allocation.read('tenant-a', s.actor, context=context())


def test_no_capacity_or_invalid_config_is_unlimited(allocation):
    s = allocation
    table = records_module.config_table
    with s.engine.begin() as conn:
        conn.execute(table.update().where(table.c.tenant_config_id.in_([1, 13])).values(config_value='broken'))
    result = s.allocation.read('tenant-a', s.actor, context=context())
    assert result['capacity_bytes'] is None and result['current_limit_bytes'] is None
    assert result['total_allocated_bytes'] == 50
