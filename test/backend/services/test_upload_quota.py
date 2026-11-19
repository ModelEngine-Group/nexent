# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UPLOADER-QUOTA-01 covers the migrated pre/post upload policy."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, QuotaExceededError
from nexent.storage.errors import DeadlineExceeded, ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def quota(mocker):
    from management.services.file import upload_quota as module

    actor = ServicePrincipal('user', 'tenant')
    storage = SimpleNamespace(tenant_id='tenant', knowledge_id=1, index_name='kb', ingroup_permission='PRIVATE')
    row = {'tenant_id': 'tenant', 'knowledge_id': 1, 'index_name': 'kb', 'ingroup_permission': 'PRIVATE'}
    inputs = {'knowledge_bases': [row], 'tenant_source_bytes': 50, 'hard_limit_bytes': 100,
              'personal_bytes': 20, 'personal_limit': None, 'personal_source': 'unlimited'}
    reader = SimpleNamespace(read=Mock(return_value=inputs))
    usage = SimpleNamespace(read=AsyncMock(return_value=(('USER',), {
        'total_bytes': 50, 'total_readable': '50 B', 'hard_limit_bytes': 100,
        'hard_limit_readable': '100 B', 'usage_pct': 50, 'tenant_warning_level': 'normal',
        'warning_enabled': False, 'es_physical_bytes': 1000, 'es_physical_readable': '1000 B',
        'breakdown': [{'index_name': 'kb', 'usage_pct': 90, 'kb_warning_level': 'warning'}],
    })))
    contexts = []

    async def blocking(name, action, *args, **kwargs):
        assert kwargs.pop('lane') == 'control-io' and kwargs.pop('owner') == 'management.file'
        contexts.append(kwargs['context'])
        return action(*args, **kwargs)

    mocker.patch.object(module, 'run_blocking', side_effect=blocking)
    service = module.UploadQuota(actor, storage, reader=reader, usage=usage)
    return SimpleNamespace(**locals())


async def test_check_allows_when_no_hard_limit(quota):
    s = quota
    s.inputs['hard_limit_bytes'] = None
    assert 'quota_status' in await s.service.before(1000)


async def test_check_allows_when_space_available_and_projects_same_status(quota):
    s = quota
    result = (await s.service.before(10))['quota_status']
    assert result == {
        'warning_enabled': False,
        'tenant_level': {'usage_pct': 50, 'warning_level': 'normal', 'hard_limit_bytes': 100,
                         'hard_limit_readable': '100 B', 'total_bytes': 50, 'total_readable': '50 B',
                         'es_physical_bytes': 1000, 'es_physical_readable': '1000 B'},
        'kb_level': {'usage_pct': 90, 'warning_level': 'warning'},
    }
    assert s.usage.read.await_args.args == ('tenant', s.actor)
    assert s.usage.read.await_args.kwargs['force_refresh'] is True
    assert s.contexts[0].cancelled.is_set()


@pytest.mark.parametrize(('used', 'pending', 'exceeded'), [(95, 10, 5), (100, 1, 1), (0, 101, 1)])
async def test_check_raises_when_exceeded_with_original_details(quota, used, pending, exceeded):
    s = quota
    s.inputs['tenant_source_bytes'] = used
    with pytest.raises(QuotaExceededError) as error:
        await s.service.before(pending)
    assert (error.value.usage_bytes, error.value.hard_limit_bytes, error.value.exceeded_by_bytes) == (used, 100, exceeded)
    assert 'Tenant storage full:' in str(error.value)
    s.usage.read.assert_not_awaited()


async def test_post_write_check_allows_when_ok_without_adding_pending_again(quota):
    assert 'quota_status' in await quota.service.after()


async def test_post_write_check_raises_on_race_condition(quota):
    s = quota
    s.inputs['tenant_source_bytes'] = 105
    with pytest.raises(QuotaExceededError) as error:
        await s.service.after()
    assert str(error.value) == 'Tenant storage limit exceeded after write'
    assert error.value.exceeded_by_bytes == 5


@pytest.mark.parametrize('limit', [0, 20])
async def test_private_user_capacity_is_enforced_before_storage(quota, limit):
    s = quota
    s.inputs['personal_limit'] = limit
    s.inputs['personal_source'] = 'default'
    with pytest.raises(AppException) as error:
        await s.service.before(1)
    assert error.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED
    s.usage.read.assert_not_awaited()


async def test_zero_personal_limit_allows_zero_byte_upload(quota):
    s = quota
    s.inputs['personal_limit'] = s.inputs['personal_bytes'] = 0
    await s.service.before(0)


async def test_shared_upload_and_post_write_do_not_add_personal_rejection(quota):
    s = quota
    s.inputs['personal_limit'] = 0
    s.row['ingroup_permission'] = 'EDIT'
    await s.service.before(1)
    s.row['ingroup_permission'] = 'PRIVATE'
    await s.service.after()


async def test_actual_actor_must_match_storage_tenant_and_current_binding(quota):
    s = quota
    s.storage.tenant_id = 'foreign'
    with pytest.raises(ScopeDenied):
        await s.service.before(1)
    s.reader.read.assert_not_called()
    s.storage.tenant_id = 'tenant'
    s.row['index_name'] = 'rebound'
    with pytest.raises(ScopeDenied):
        await s.service.before(1)
    s.usage.read.assert_not_awaited()


async def test_stage_deadline_cancels_statistics_and_logs_once(quota, mocker, caplog):
    from time import monotonic

    from nexent.storage.models import OperationContext

    s = quota
    closed = []

    async def stalled(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    s.usage.read.side_effect = stalled
    mocker.patch.object(s.module, 'OperationContext', side_effect=lambda operation_id, deadline, **kwargs:
        OperationContext(operation_id, monotonic() + .02, **kwargs))
    with pytest.raises(DeadlineExceeded):
        await s.service.before(1)
    assert closed == [True] and s.contexts[0].cancelled.is_set()
    assert sum('upload_quota_timeout' in record.message for record in caplog.records) == 1
    assert not any(record.levelname == 'ERROR' for record in caplog.records)


async def test_personal_usage_strict_allows_missing_es_index(quota):
    s = quota
    s.usage.read.return_value[1]['es_physical_bytes'] = 0
    s.usage.read.return_value[1]['breakdown'] = []
    result = (await s.service.before(1))['quota_status']
    assert result['tenant_level']['total_bytes'] == 50
    assert result['kb_level'] == {'usage_pct': None, 'warning_level': 'normal'}


async def test_ledger_read_failure_is_not_retried_or_treated_as_free_capacity(quota):
    from nexent.storage.errors import Unavailable

    s = quota
    s.reader.read.side_effect = Unavailable()
    with pytest.raises(Unavailable):
        await s.service.before(1)
    assert s.reader.read.call_count == 1
    s.usage.read.assert_not_awaited()
