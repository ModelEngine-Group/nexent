# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PERSONAL-SELF-01 reads only the actor's PRIVATE usage and quota via SI."""

import pytest
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
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


def test_self_uses_actual_subject_without_capacity_permission(capacity):  # noqa: F811
    s = capacity
    s.update('cleanse_accounts', user_roles=['DEV'])
    with s.engine.begin() as conn:
        conn.execute(permissions_table.delete())
    result = s.reader.read_self(s.actor, context=context())
    assert result['personal_bytes'] == 5 and result['quota_bytes'] is None
    assert result['quota_source'] == 'unlimited'
    assert [r['knowledge_id'] for r in result['knowledge_bases']] == [1]
    assert s.opened == [(s.actor, s.actor.tenant_id)]


@pytest.mark.parametrize(('individual', 'default', 'value', 'source'), [
    ('8', '9', 8, 'individual'), (None, '9', 9, 'default'),
    ('broken', '9', 0, 'individual'), ('-2', '9', -2, 'individual'),
])
def test_self_quota_precedence_and_original_parse(capacity, individual, default, value, source):  # noqa: F811
    s = capacity
    with s.engine.begin() as conn:
        for key, raw in [('PERSONAL_KB_QUOTA_user-a', individual), ('PERSONAL_KB_QUOTA_DEFAULT', default)]:
            if raw is not None:
                conn.execute(module.config_table.insert(), {'tenant_id': 'tenant-a', 'config_key': key, 'config_value': raw, 'delete_flag': 'N'})
    result = s.reader.read_self(s.actor, context=context())
    assert (result['quota_bytes'], result['quota_source']) == (value, source)


def test_disabled_membership_refuses_before_metadata(capacity):  # noqa: F811
    s = capacity
    s.update('cleanse_memberships', delete_flag='Y')
    with pytest.raises(ScopeDenied):
        s.reader.read_self(s.actor, context=context())
    assert not s.opened


def test_self_source_failure_keeps_strict_app_error(capacity, mocker):  # noqa: F811
    mocker.patch('infrastructure.rdb.record_store.SQLRecordStore.sum_by', side_effect=Unavailable())
    with pytest.raises(AppException) as raised:
        capacity.reader.read_self(capacity.actor, context=context())
    assert raised.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE
