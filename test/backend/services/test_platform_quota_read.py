# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PLATFORM-QUOTA-READ-01 proves bounded privileged SI discovery."""

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from contracts.constants.constants import ASSET_OWNER_TENANT_ID, DEFAULT_TENANT_ID
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import FieldPatch

from infrastructure import tenant_quota_read as quota_records
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_tenant_quota_read import quota  # noqa: F401


@pytest.fixture
def platform(quota):  # noqa: F811
    from management.services.knowledge_base.platform_quota_read import (
        PlatformQuotaReader,
    )

    from infrastructure.platform_quota_read import bind_platform_quota_discovery

    s = quota
    s.update('cleanse_accounts', user_roles=['SU'])
    s.discovery_opened = []
    table = quota_records.config_table
    with s.engine.begin() as conn:
        conn.execute(table.update().values(create_time=datetime(2025, 1, 1, tzinfo=timezone.utc)))
        conn.execute(table.insert(), [
            {'tenant_config_id': i, 'tenant_id': tenant, 'config_key': key,
             'config_value': value, 'delete_flag': deleted, 'create_time': datetime(2026, 1, day, tzinfo=timezone.utc)}
            for i, tenant, key, value, deleted, day in (
                (10, 'tenant-b', 'KB_QUOTA_TENANT_HARD_LIMIT_BYTES', '50', 'N', 3),
                (11, 'tenant-b', 'TENANT_NAME', 'Bee', 'N', 3),
                (12, 'tenant-c', 'arbitrary', 'present', 'N', 2),
                (13, ASSET_OWNER_TENANT_ID, 'PLATFORM_KB_STORAGE_CAPACITY_BYTES', '100', 'N', 4),
                (14, DEFAULT_TENANT_ID, 'arbitrary', 'excluded', 'N', 4),
                (15, ' ', 'arbitrary', 'excluded', 'N', 4),
                (16, None, 'arbitrary', 'excluded', 'N', 4),
                (17, 'deleted-tenant', 'arbitrary', 'excluded', 'Y', 4),
                (18, 'tenant-b', 'KB_QUOTA_TENANT_HARD_LIMIT_BYTES', '999', 'N', 3),
                (19, '\t\n', 'arbitrary', 'excluded', 'N', 4),
                (20, '\u2003', 'arbitrary', 'excluded', 'N', 4),
            )
        ])

    @contextmanager
    def ports(actor, *, context):
        with s.ports(actor, context=context) as (identity, records):
            handles = []

            def discover():
                s.discovery_opened.append(actor)
                port = bind_platform_quota_discovery(actor, s.engine)
                handles.append(port)
                return port

            try:
                yield identity, discover, records
            finally:
                for port in handles:
                    port.close()

    s.platform_reader = PlatformQuotaReader(ports=ports)
    return s


def test_discovery_order_exclusion_first_config_and_capacity(platform):
    s = platform
    result = s.platform_reader.read(s.actor, context=context())
    assert result['capacity_bytes'] == 100
    assert result['tenants'] == [
        {'tenant_id': 'tenant-b', 'tenant_name': 'Bee', 'hard_limit_bytes': 50},
        {'tenant_id': 'tenant-c', 'tenant_name': 'tenant-c', 'hard_limit_bytes': None},
        {'tenant_id': 'tenant-a', 'tenant_name': 'tenant-a', 'hard_limit_bytes': 20},
    ]
    assert s.discovery_opened == [s.actor]
    assert all(actor == s.actor for actor, tenant in s.opened)
    assert s.closed == [True]


@pytest.mark.parametrize('role', ['USER', 'DEV', 'ADMIN', 'OPS'])
def test_ordinary_roles_never_open_discovery_or_target_records(platform, role):
    s = platform
    s.update('cleanse_accounts', user_roles=[role])
    with pytest.raises(ScopeDenied):
        s.platform_reader.read(s.actor, context=context())
    assert not s.discovery_opened and not s.opened


def test_platform_read_revocation_refuses_response(platform, mocker):
    s = platform
    original, calls = s.platform_reader._authorize, []

    def authorize(*args):
        calls.append(True)
        if len(calls) == 2:
            s.update('cleanse_accounts', user_roles=['DEV'])
        return original(*args)

    mocker.patch.object(s.platform_reader, '_authorize', side_effect=authorize)
    with pytest.raises(ScopeDenied):
        s.platform_reader.read(s.actor, context=context())
    assert s.closed == [True] and len(calls) == 2


def test_discovery_is_read_only(platform):
    from infrastructure.platform_quota_read import (
        DISCOVERY,
        bind_platform_quota_discovery,
    )

    s = platform
    port = bind_platform_quota_discovery(s.actor, s.engine)
    try:
        with pytest.raises(ScopeDenied):
            port.patch(DISCOVERY, 'tenant-a', FieldPatch(set_values={'tenant_id': 'other'}), expected=None, context=context())
    finally:
        port.close()


@pytest.mark.parametrize('dataset', ['cleanse_accounts', 'cleanse_memberships'])
def test_disabled_platform_actor_is_refused_before_discovery(platform, dataset):
    s = platform
    s.update(dataset, delete_flag='Y')
    with pytest.raises(ScopeDenied):
        s.platform_reader.read(s.actor, context=context())
    assert not s.discovery_opened and not s.opened


def test_asset_owner_role_retains_actual_discovery_actor(platform):
    s = platform
    s.update('cleanse_accounts', user_roles=['ASSET_OWNER'])
    assert len(s.platform_reader.read(s.actor, context=context())['tenants']) == 3
    assert s.discovery_opened == [s.actor]


def test_discovery_reads_all_pages(platform):
    s = platform
    with s.engine.begin() as conn:
        conn.execute(quota_records.config_table.insert(), [
            {'tenant_config_id': i, 'tenant_id': 'tenant-' + str(i), 'config_key': 'arbitrary',
             'config_value': '', 'delete_flag': 'N', 'create_time': datetime(2027, 1, 1, tzinfo=timezone.utc)}
            for i in range(1000, 1501)
        ])
    result = s.platform_reader.read(s.actor, context=context())
    assert len(result['tenants']) == 504
    assert result['tenants'][0]['tenant_id'] == 'tenant-1000'
    assert result['tenants'][500]['tenant_id'] == 'tenant-1500'
    assert result['tenants'][-1]['tenant_id'] == 'tenant-a'
