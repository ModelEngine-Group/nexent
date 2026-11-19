# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PERSONAL-SOURCE-01 reads subject usage with the real actor and scoped SI."""

from contextlib import contextmanager

import pytest
from nexent.storage.errors import (
    DeadlineExceeded,
    OperationCancelled,
    ScopeDenied,
    Unavailable,
)

from infrastructure import tenant_quota_read as records_module
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_personal_quota_configuration import (
    personal,  # noqa: F401
)
from test.backend.services.test_tenant_quota_read import quota  # noqa: F401
from test.backend.services.test_tenant_quota_usage_read import usage  # noqa: F401


@pytest.fixture
def capacity(personal, usage):  # noqa: F811
    from management.services.knowledge_base.personal_capacity_read import (
        PersonalCapacityReader,
    )

    s = usage
    catalog = s.tables['cleanse_knowledge']
    with s.engine.begin() as conn:
        conn.execute(catalog.update().where(catalog.c.knowledge_id == 1).values(ingroup_permission='PRIVATE'))

    @contextmanager
    def ports(actor, *, context, writable=False):
        assert not writable
        with s.configuration.ports(actor, context=context, writable=False) as (identity, permissions, _):
            handles = []

            def records(tenant):
                s.opened.append((actor, tenant))
                port = records_module.bind_tenant_quota_records(actor, tenant, s.engine, usage=True)
                handles.append(port)
                return port

            try:
                yield identity, permissions, records
            finally:
                for port in handles:
                    port.close()

    s.reader = PersonalCapacityReader(ports=ports)
    return s


def test_subject_filter_excludes_orphans_and_other_private_creators(capacity):
    s = capacity
    assert s.reader.read('tenant-a', s.actor, 'user-a', context=context())['personal_bytes'] == 5
    assert s.reader.read('tenant-a', s.actor, 'other', context=context())['personal_bytes'] == 7
    assert s.reader.read('tenant-a', s.actor, 'missing', context=context())['personal_bytes'] == 0
    assert all(actor == s.actor for actor, _ in s.opened)


def test_foreign_su_keeps_actual_actor(capacity):
    s = capacity
    result = s.reader.read('tenant-b', s.actor, 'other', context=context())
    assert result['personal_bytes'] == 100 and s.actor.tenant_id == 'tenant-a'
    assert s.opened == [(s.actor, 'tenant-b')]


def test_shared_and_deleted_catalog_never_count_as_private(capacity):
    s = capacity
    s.update('cleanse_knowledge', ingroup_permission='EDIT')
    assert s.reader.read('tenant-a', s.actor, 'user-a', context=context())['personal_bytes'] == 0


@pytest.mark.parametrize(('error', 'allowed'), [(Unavailable(), True), (ScopeDenied(), False),
    (DeadlineExceeded(), False), (OperationCancelled(), False)])
def test_original_non_strict_ledger_failure_only(capacity, mocker, error, allowed):
    s = capacity
    mocker.patch('infrastructure.rdb.record_store.SQLRecordStore.sum_by', side_effect=error)
    if allowed:
        assert s.reader.read('tenant-a', s.actor, 'user-a', strict=False, context=context())['personal_bytes'] == 0
    else:
        with pytest.raises(type(error)):
            s.reader.read('tenant-a', s.actor, 'user-a', strict=False, context=context())


def test_strict_ledger_failure_preserves_unavailable_app_code(capacity, mocker):
    from contracts.errors.codes import ErrorCode
    from contracts.errors.exceptions import AppException

    s = capacity
    mocker.patch('infrastructure.rdb.record_store.SQLRecordStore.sum_by', side_effect=Unavailable())
    with pytest.raises(AppException) as raised:
        s.reader.read('tenant-a', s.actor, 'user-a', context=context())
    assert raised.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE


def test_current_permission_revocation_blocks_metadata(capacity):
    from infrastructure.knowledge_collection_metadata import permissions_table

    s = capacity
    with s.engine.begin() as conn:
        conn.execute(permissions_table.delete())
    with pytest.raises(ScopeDenied):
        s.reader.read('tenant-a', s.actor, 'user-a', context=context())
    assert not s.opened


def test_historical_same_index_keeps_last_value_per_catalog_entry(capacity):
    s = capacity
    catalog = s.tables['cleanse_knowledge']
    with s.engine.begin() as conn:
        conn.execute(catalog.update().where(catalog.c.knowledge_id == 2).values(created_by='user-a', index_name='kb-one'))
    result = s.reader.read('tenant-a', s.actor, 'user-a', context=context())
    assert result['source_bytes_by_kb'] == {1: 5, 2: 7}
    assert result['personal_bytes'] == 14


def test_catalog_failure_never_becomes_zero(capacity, mocker):
    mocker.patch('infrastructure.rdb.record_store.SQLRecordStore.query', side_effect=Unavailable())
    with pytest.raises(Unavailable):
        capacity.reader.read('tenant-a', capacity.actor, 'user-a', strict=False, context=context())
