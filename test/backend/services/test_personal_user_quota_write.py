# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PERSONAL-USER-WRITE-01 preserves subject quota errors and source-only writes."""

import pytest
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from nexent.storage.errors import Unavailable

from infrastructure import tenant_quota_read as records_module
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_personal_capacity_read import capacity  # noqa: F401
from test.backend.services.test_personal_quota_configuration import (
    personal,  # noqa: F401
)
from test.backend.services.test_tenant_quota_read import quota  # noqa: F401
from test.backend.services.test_tenant_quota_usage_read import usage  # noqa: F401


@pytest.fixture
def user_quota(capacity):  # noqa: F811
    from management.services.knowledge_base.personal_quota_configuration import (
        PersonalQuotaConfiguration,
    )

    s = capacity
    s.user_writer = PersonalQuotaConfiguration(ports=s.configuration.ports, usage_reader=s.reader)
    return s


def test_limit_below_subject_usage_preserves_code_text_and_details(user_quota):
    s = user_quota
    with pytest.raises(AppException) as raised:
        s.user_writer.run('user-write', 'tenant-a', s.actor,
            {'subject_user_id': 'user-a', 'quota_limit_bytes': 4}, context=context())
    assert raised.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_BELOW_USAGE
    assert str(raised.value) == 'Personal KB quota 4 B is below current usage 5 B'
    assert raised.value.details == {'quota_limit_bytes': 4, 'usage_bytes': 5}


def test_exact_usage_boundary_and_actual_actor_audit(user_quota):
    s = user_quota
    result = s.user_writer.run('user-write', 'tenant-a', s.actor,
        {'subject_user_id': 'other', 'quota_limit_bytes': 7}, context=context())
    assert result == {'user_id': 'other', 'quota_limit_bytes': 7, 'quota_limit_readable': '7 B'}
    table = records_module.config_table
    with s.engine.connect() as conn:
        row = conn.execute(table.select().where(table.c.config_key == 'PERSONAL_KB_QUOTA_other')).mappings().one()
    assert row['created_by'] == row['user_id'] == s.actor.user_id and row['tenant_id'] == 'tenant-a'


def test_unlimited_does_not_read_source_usage(user_quota, mocker):
    s = user_quota
    read = mocker.patch.object(s.reader, 'read', side_effect=AssertionError('No source read for unlimited'))
    result = s.user_writer.run('user-write', 'tenant-a', s.actor,
        {'subject_user_id': 'other', 'quota_limit_bytes': 0, 'unlimited': True}, context=context())
    assert result == {'user_id': 'other', 'quota_limit_bytes': None, 'quota_limit_readable': None}
    read.assert_not_called()


def test_existing_non_strict_ledger_failure_remains_zero_for_setting(user_quota, mocker):
    s = user_quota
    mocker.patch('infrastructure.rdb.record_store.SQLRecordStore.sum_by', side_effect=Unavailable())
    read = mocker.patch.object(s.reader, 'read', wraps=s.reader.read)
    result = s.user_writer.run('user-write', 'tenant-a', s.actor,
        {'subject_user_id': 'user-a', 'quota_limit_bytes': 1}, context=context())
    assert result['quota_limit_bytes'] == 1 and read.call_args.kwargs['strict'] is False
