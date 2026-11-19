# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PERSONAL-MGMT-01 keeps current permissions, subject and batch quota semantics."""

import pytest
from nexent.storage.errors import ScopeDenied, Unavailable

from infrastructure import tenant_quota_read as module
from infrastructure.knowledge_collection_metadata import permissions_table
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_personal_capacity_read import capacity  # noqa: F401
from test.backend.services.test_personal_quota_configuration import (
    personal,  # noqa: F401
)
from test.backend.services.test_tenant_quota_read import quota  # noqa: F401
from test.backend.services.test_tenant_quota_usage_read import usage  # noqa: F401


def test_inventory_reader_sees_all_private_creators_via_readonly_si(capacity):  # noqa: F811
    s = capacity
    s.update('cleanse_accounts', user_roles=['OPS'])
    result = s.reader.read_management('tenant-a', s.actor, context=context())
    assert [r['knowledge_id'] for r in result['knowledge_bases']] == [1, 2, 3]
    assert result['source_bytes_by_kb'] == {1: 5, 2: 7}
    assert result['quotas'] == {'other': (None, 'unlimited'), 'user-a': (None, 'unlimited')}
    assert result['default_quota'] is None
    assert s.opened == [(s.actor, 'tenant-a')]


def test_management_subject_does_not_replace_actual_actor(capacity):  # noqa: F811
    s = capacity
    result = s.reader.read_management('tenant-a', s.actor, subject='other', context=context())
    assert [r['knowledge_id'] for r in result['knowledge_bases']] == [2, 3]
    assert s.opened == [(s.actor, 'tenant-a')] and s.actor.user_id == 'user-a'


def test_management_batch_last_config_preserves_self_first_config(capacity):  # noqa: F811
    s = capacity
    with s.engine.begin() as conn:
        for key, value in [('PERSONAL_KB_QUOTA_DEFAULT', '9'), ('PERSONAL_KB_QUOTA_DEFAULT', '11'),
            ('PERSONAL_KB_QUOTA_user-a', '3'), ('PERSONAL_KB_QUOTA_user-a', '4')]:
            conn.execute(module.config_table.insert(), {'tenant_id': 'tenant-a', 'config_key': key,
                'config_value': value, 'delete_flag': 'N'})
    result = s.reader.read_management('tenant-a', s.actor, context=context())
    assert result['quotas'] == {'user-a': (4, 'individual'), 'other': (11, 'default')}
    assert result['default_quota'] == 11
    assert s.reader.read_self(s.actor, context=context())['quota_bytes'] == 3


@pytest.mark.parametrize('role', ['ADMIN', 'ASSET_OWNER'])
def test_foreign_management_requires_su(capacity, role):  # noqa: F811
    s = capacity
    s.update('cleanse_accounts', user_roles=[role])
    with pytest.raises(ScopeDenied):
        s.reader.read_management('tenant-b', s.actor, context=context())
    assert not s.opened


def test_foreign_su_keeps_actual_home_tenant(capacity):  # noqa: F811
    s = capacity
    result = s.reader.read_management('tenant-b', s.actor, context=context())
    assert result['personal_bytes'] == 100 and s.actor.tenant_id == 'tenant-a'
    assert s.opened == [(s.actor, 'tenant-b')]


def test_management_revoked_permission_never_opens_records(capacity):  # noqa: F811
    s = capacity
    with s.engine.begin() as conn:
        conn.execute(permissions_table.delete())
    with pytest.raises(ScopeDenied):
        s.reader.read_management('tenant-a', s.actor, context=context())
    assert not s.opened


def test_original_non_strict_ledger_error_keeps_config_and_directory(capacity, mocker):  # noqa: F811
    mocker.patch('infrastructure.rdb.record_store.SQLRecordStore.sum_by', side_effect=Unavailable())
    result = capacity.reader.read_management('tenant-a', capacity.actor, context=context())
    assert result['personal_bytes'] == 0 and len(result['knowledge_bases']) == 3


def test_management_config_error_is_not_source_zero(capacity, mocker):  # noqa: F811
    from nexent.storage.errors import Conflict

    mocker.patch.object(capacity.reader, '_configuration', side_effect=Conflict())
    with pytest.raises(Conflict):
        capacity.reader.read_management('tenant-a', capacity.actor, context=context())
