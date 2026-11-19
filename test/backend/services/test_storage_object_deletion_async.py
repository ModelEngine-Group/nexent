# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SOURCE-OBJECT-03 owns the full deletion budget and preserves upload cleanup failure."""

import asyncio

import pytest
from management.services.file import object_deletion as module
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal


async def test_delete_uses_actual_actor_managed_lane_and_finally_cancel(mocker):
    captured = []

    async def work(name, action, object_name, actor, **kwargs):
        assert name == 'storage-object-delete' and object_name == 'attachments/user/one'
        assert actor == ServicePrincipal('user', 'actual')
        assert kwargs['lane'] == 'control-io' and kwargs['owner'] == 'management.file'
        captured.append(kwargs['context'])
        assert 0 < kwargs['context'].remaining() <= 30
        return {'success': True}

    mocker.patch.object(module, 'run_blocking', side_effect=work)
    assert await module.delete_file_impl('attachments/user/one', tenant_id='actual', updated_by='user') == {'success': True}
    assert captured[0].cancelled.is_set()


@pytest.mark.parametrize(('phase', 'suppressed'), [('delete', False), ('compensate', True)])
async def test_deadline_cancels_work_and_warns_once(mocker, caplog, phase, suppressed):
    captured, exited = [], []

    async def work(*args, **kwargs):
        captured.append(kwargs['context'])
        try:
            await asyncio.Event().wait()
        finally:
            exited.append(True)

    mocker.patch.object(module, 'run_blocking', side_effect=work)
    mocker.patch.object(module, 'OperationContext', side_effect=lambda name, deadline, **kwargs:
        OperationContext(name, module.monotonic() + .02, **kwargs))
    if suppressed:
        assert await module.compensate_uploaded_objects(None, [], ServicePrincipal('user', 'actual')) is None
    else:
        with pytest.raises(DeadlineExceeded):
            await module.delete_file_impl('attachments/user/one', tenant_id='actual', updated_by='user')
    assert exited == [True] and captured[0].cancelled.is_set()
    assert len([r for r in caplog.records if 'storage_object_timeout' in r.message]) == 1
    assert not [r for r in caplog.records if r.levelname == 'ERROR']
