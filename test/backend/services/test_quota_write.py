# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""QUOTA-WRITE-01 preserves quota mutations through actual scoped SI."""

from contextlib import contextmanager

import pytest
from contracts.errors.exceptions import PlatformQuotaConflictError

from infrastructure import tenant_quota_read as records_module
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_platform_quota_read import platform  # noqa: F401
from test.backend.services.test_quota_allocation_read import allocation  # noqa: F401
from test.backend.services.test_tenant_quota_read import quota  # noqa: F401
from test.backend.services.test_tenant_quota_usage_read import usage  # noqa: F401

MB = 1024 * 1024


@pytest.fixture
def writing(allocation):  # noqa: F811
    from management.services.knowledge_base.quota_write import QuotaWriter

    from infrastructure.quota_write import bind_quota_write_records

    s = allocation
    table = records_module.config_table
    with s.engine.begin() as conn:
        conn.execute(table.update().where(table.c.tenant_config_id == 13).values(config_value=str(100 * MB)))

    @contextmanager
    def ports(actor, *, context):
        with s.ports(actor, context=context) as (identity, _):
            handles = []

            def records(tenant):
                s.opened.append((actor, tenant))
                port = bind_quota_write_records(actor, tenant, s.engine)
                handles.append(port)
                return port

            try:
                yield identity, records
            finally:
                for port in handles:
                    port.close()

    s.writer = QuotaWriter(ports=ports, allocation=s.allocation, platform=s.platform_reader)

    def value(tenant, key):
        with s.engine.connect() as conn:
            return conn.execute(table.select().where(table.c.tenant_id == tenant,
                table.c.config_key == key, table.c.delete_flag == 'N').order_by(table.c.tenant_config_id)).mappings().all()

    s.value = value
    return s


def test_hard_update_keeps_first_row_and_marks_platform_owned(writing):
    s = writing
    result = s.writer.run('hard', 'tenant-b', s.actor, {'hard_limit_mb': 1}, context=context())
    assert result == {'hard_limit_bytes': MB, 'hard_limit_readable': '1.0 MB'}
    rows = s.value('tenant-b', 'KB_QUOTA_TENANT_HARD_LIMIT_BYTES')
    assert [r['config_value'] for r in rows] == [str(MB), '999']
    assert rows[0]['updated_by'] == s.actor.user_id
    editable = s.value('tenant-b', 'KB_QUOTA_HARD_LIMIT_EDITABLE')[0]
    assert editable['config_value'] == 'false' and editable['created_by'] == s.actor.user_id
    assert editable['user_id'] == s.actor.user_id and s.actor.tenant_id == 'tenant-a'


def test_hard_none_soft_deletes_only_first_and_removes_editable(writing):
    s = writing
    result = s.writer.run('hard', 'tenant-b', s.actor, {}, context=context())
    assert result == {'hard_limit_bytes': None, 'hard_limit_readable': None}
    assert [r['config_value'] for r in s.value('tenant-b', 'KB_QUOTA_TENANT_HARD_LIMIT_BYTES')] == ['999']
    assert not s.value('tenant-b', 'KB_QUOTA_HARD_LIMIT_EDITABLE')


def test_admin_editable_rule_and_existing_delete_semantics(writing):
    from management.services.knowledge_base.quota_write import QuotaWriteDenied

    s = writing
    s.update('cleanse_accounts', user_roles=['ADMIN'])
    with pytest.raises(QuotaWriteDenied, match='managed by the platform administrator'):
        s.writer.run('update', 'tenant-a', s.actor, {'hard_limit_mb': 1}, context=context())
    s.writer.run('remove', 'tenant-a', s.actor, {}, context=context())
    result = s.writer.run('update', 'tenant-a', s.actor, {'hard_limit_mb': 1}, context=context())
    assert result['hard_limit_bytes'] == MB and result['hard_limit_editable'] is True


@pytest.mark.parametrize(('action', 'tenant'), [('hard', 'tenant-a'), ('capacity', 'tenant-a'), ('update', 'tenant-b')])
def test_admin_scope_denied_before_metadata(writing, action, tenant):
    from management.services.knowledge_base.quota_write import QuotaWriteDenied

    s = writing
    s.update('cleanse_accounts', user_roles=['ADMIN'])
    with pytest.raises(QuotaWriteDenied):
        s.writer.run(action, tenant, s.actor, {}, context=context())
    assert not s.opened


def test_warning_validation_preserves_hard_commit_order(writing):
    from management.services.knowledge_base.quota_write import InvalidQuotaWarning

    s = writing
    with pytest.raises(InvalidQuotaWarning, match='warning_pct must be 1-100'):
        s.writer.run('update', 'tenant-a', s.actor, {'hard_limit_mb': 1, 'warning_threshold_pct': 150}, context=context())
    assert s.value('tenant-a', 'KB_QUOTA_TENANT_HARD_LIMIT_BYTES')[0]['config_value'] == str(MB)


def test_warning_update_response_and_effective_thresholds(writing):
    s = writing
    result = s.writer.run('update', 'tenant-a', s.actor, {'warning_threshold_pct': 70,
        'critical_threshold_pct': 90, 'warning_enabled': True}, context=context())
    assert result == {'hard_limit_bytes': 20, 'hard_limit_readable': '20 B', 'hard_limit_editable': False,
        'warning_enabled': True, 'warning_threshold_pct': 70, 'critical_threshold_pct': 90}


def test_pair_failure_rolls_back_without_retry(writing, mocker):
    s = writing
    original, keys = s.writer._set, []

    def set_value(records, key, value, actor, context):
        keys.append(key)
        if len(keys) == 2:
            raise RuntimeError('write failed')
        return original(records, key, value, actor, context)

    mocker.patch.object(s.writer, '_set', side_effect=set_value)
    with pytest.raises(RuntimeError, match='write failed'):
        s.writer.run('hard', 'tenant-b', s.actor, {'hard_limit_mb': 1}, context=context())
    assert s.value('tenant-b', 'KB_QUOTA_TENANT_HARD_LIMIT_BYTES')[0]['config_value'] == '50'
    assert len(keys) == 2


def test_capacity_conflict_and_unlimited_removal(writing):
    s = writing
    with pytest.raises(PlatformQuotaConflictError) as raised:
        s.writer.run('capacity', None, s.actor, {'capacity_gb': 0}, context=context())
    assert raised.value.error == 'PlatformCapacityBelowAllocation'
    assert s.writer.run('capacity', None, s.actor, {}, context=context())['capacity_bytes'] is None


def test_capacity_never_reads_usage_ledger(writing, mocker):
    s = writing
    mocker.patch.object(s.allocation, 'read', side_effect=AssertionError('ledger not required'))
    assert s.writer.run('capacity', None, s.actor, {'capacity_gb': 1}, context=context())['capacity_bytes'] == 1024**3


def test_disabled_actor_never_writes(writing):
    from nexent.storage.errors import ScopeDenied

    s = writing
    s.update('cleanse_accounts', delete_flag='Y')
    with pytest.raises(ScopeDenied):
        s.writer.run('remove', 'tenant-a', s.actor, {}, context=context())
    assert not s.opened


def test_platform_delete_cannot_be_used_by_own_tenant_admin(writing):
    from management.services.knowledge_base.quota_write import QuotaWriteDenied

    s = writing
    s.update('cleanse_accounts', user_roles=['ADMIN'])
    with pytest.raises(QuotaWriteDenied):
        s.writer.run('remove-platform', 'tenant-a', s.actor, {}, context=context())
    assert not s.opened


def test_revocation_before_pair_commit_rolls_back(writing, mocker):
    from nexent.storage.errors import ScopeDenied

    s = writing
    original, calls = s.writer._authorize, []

    def authorize(*args):
        calls.append(True)
        if len(calls) == 3:
            raise ScopeDenied()
        return original(*args)

    mocker.patch.object(s.writer, '_authorize', side_effect=authorize)
    with pytest.raises(ScopeDenied):
        s.writer.run('hard', 'tenant-b', s.actor, {'hard_limit_mb': 1}, context=context())
    assert s.value('tenant-b', 'KB_QUOTA_TENANT_HARD_LIMIT_BYTES')[0]['config_value'] == '50'
    assert not s.value('tenant-b', 'KB_QUOTA_HARD_LIMIT_EDITABLE')


def test_lock_wait_has_request_budget_and_never_opens_target(writing, mocker):
    from management.services.knowledge_base import quota_write as module
    from nexent.storage.errors import DeadlineExceeded

    s = writing
    lock = mocker.patch.object(module, 'allocation_lock')
    lock.acquire.return_value = False
    with pytest.raises(DeadlineExceeded):
        s.writer.run('remove', 'tenant-a', s.actor, {}, context=context())
    assert lock.acquire.call_count == 1 and 0 < lock.acquire.call_args.kwargs['timeout'] <= 30
    lock.release.assert_not_called()
    assert not s.opened
