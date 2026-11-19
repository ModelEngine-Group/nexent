# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""QUOTA-USAGE-READ-01 checks actual scoped SI accounting inputs."""

from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import FieldPatch

from infrastructure import tenant_quota_read as records_module
from infrastructure.rdb.storage_ledger import LEDGER, ledger_catalog
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_tenant_quota_read import quota  # noqa: F401


@pytest.fixture
def usage(quota, mocker):  # noqa: F811
    s = quota
    # The old configuration fixture intentionally has no display-name column.
    catalog = s.tables['cleanse_knowledge']
    view = sa.select(*catalog.c, sa.literal('Display name').label('knowledge_name')).subquery()
    mocker.patch.object(records_module, 'knowledge_table', view)
    _, ledger, _ = ledger_catalog()
    ledger.create(s.engine)
    with s.engine.begin() as conn:
        conn.execute(ledger.insert(), [
            {'storage_object_id': i, 'tenant_id': tenant, 'knowledge_id': kb,
                 'index_name': 'kb-' + str(kb), 'bucket_name': 'test', 'object_name': str(i),
                 'raw_bytes': size, 'status': status, 'delete_flag': deleted}
            for i, tenant, kb, size, status, deleted in (
                (1, 'tenant-a', 1, 5, 'COMMITTED', 'N'),
                (2, 'tenant-a', 2, 7, 'COMMITTED', 'N'),
                (3, 'tenant-a', 999, 11, 'COMMITTED', 'N'),
                (4, 'tenant-a', 4, 13, 'COMMITTED', 'N'),
                (5, 'tenant-b', 5, 100, 'COMMITTED', 'N'),
                (6, 'tenant-a', 1, 200, 'DELETED', 'N'),
                (7, 'tenant-a', 1, 300, 'COMMITTED', 'Y'),
            )
        ])

    @contextmanager
    def ports(actor, *, context):
        with s.ports(actor, context=context) as (identity, _):
            handles = []

            def open_records(tenant):
                s.opened.append((actor, tenant))
                port = records_module.bind_tenant_quota_records(actor, tenant, s.engine, usage=True)
                handles.append(port)
                return port

            try:
                yield identity, open_records
            finally:
                for port in handles:
                    port.close()

    from management.services.knowledge_base.quota_usage_read import (
        TenantQuotaUsageReader,
    )

    s.usage_service = TenantQuotaUsageReader(ports=ports)
    return s


def test_usage_counts_orphan_and_deleted_kb_ledger_but_not_foreign_or_deleted_objects(usage):
    s = usage
    result = s.usage_service.read('tenant-a', s.actor, context=context())
    assert result['tenant_source_bytes'] == 36
    assert result['source_bytes_by_kb'] == {1: 5, 2: 7, 4: 13, 999: 11}
    rows = result['knowledge_bases']
    assert [row['knowledge_id'] for row in rows] == [1, 2, 3]
    assert rows[1]['ingroup_permission'] == 'PRIVATE' and rows[2]['knowledge_sources'] == 'datamate'
    assert rows[0]['knowledge_name'] == 'Display name'
    assert result['hard_limit_bytes'] == 20 and result['summary']['soft_allocated_total_bytes'] == 10
    assert s.opened == [(s.actor, 'tenant-a')] and s.closed == [True]


def test_foreign_ordinary_denied_before_records_open(usage):
    s = usage
    with pytest.raises(ScopeDenied):
        s.usage_service.read('tenant-b', s.actor, context=context())
    assert not s.opened


@pytest.mark.parametrize('role', ['SU', 'ASSET_OWNER'])
def test_foreign_privileged_uses_target_namespace_and_actual_actor(usage, role):
    s = usage
    s.update('cleanse_accounts', user_roles=[role])
    result = s.usage_service.read('tenant-b', s.actor, context=context())
    assert result['tenant_source_bytes'] == 100 and result['source_bytes_by_kb'] == {5: 100}
    assert s.opened == [(s.actor, 'tenant-b')] and s.actor.tenant_id == 'tenant-a'


def test_usage_ledger_cannot_be_written(usage):
    s = usage
    port = records_module.bind_tenant_quota_records(s.actor, 'tenant-a', s.engine, usage=True)
    try:
        with pytest.raises(ScopeDenied):
            port.patch(LEDGER, 1, FieldPatch(set_values={'raw_bytes': 999}), expected=None, context=context())
    finally:
        port.close()


def test_usage_read_revocation_refuses_result(usage, mocker):
    s = usage
    original, calls = s.usage_service._authorize, []

    def authorize(*args):
        calls.append(True)
        if len(calls) == 2:
            s.update('cleanse_memberships', delete_flag='Y')
        return original(*args)

    mocker.patch.object(s.usage_service, '_authorize', side_effect=authorize)
    with pytest.raises(ScopeDenied):
        s.usage_service.read('tenant-a', s.actor, context=context())
    assert len(calls) == 2 and s.closed == [True]


def test_usage_catalog_reads_every_page(usage):
    s = usage
    with s.engine.begin() as conn:
        conn.execute(s.tables['cleanse_knowledge'].insert(), [
            {'knowledge_id': i, 'tenant_id': 'tenant-a', 'index_name': 'kb-' + str(i),
                 'created_by': 'other', 'ingroup_permission': 'PRIVATE',
                 'knowledge_sources': 'elasticsearch', 'quota_limit_bytes': 1, 'delete_flag': 'N'}
            for i in range(1000, 1501)
        ])
    result = s.usage_service.read('tenant-a', s.actor, context=context())
    assert len(result['knowledge_bases']) == result['summary']['kb_count'] == 504
    assert result['summary']['soft_allocated_total_bytes'] == 511
    assert result['knowledge_bases'][-1]['knowledge_id'] == 1500
    assert result['tenant_source_bytes'] == 36


@pytest.mark.parametrize('dataset', ['cleanse_accounts', 'cleanse_memberships'])
def test_disabled_actual_actor_never_opens_usage_records(usage, dataset):
    s = usage
    s.update(dataset, delete_flag='Y')
    with pytest.raises(ScopeDenied):
        s.usage_service.read('tenant-a', s.actor, context=context())
    assert not s.opened
