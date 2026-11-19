# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""QUOTA-WRITE-02 binds configuration mutations to managed request lifetime."""

import asyncio
from time import monotonic

import pytest
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal


async def test_managed_write_receives_actual_actor_and_closes_context(mocker):
    from management.services.knowledge_base import quota_write as module

    actor, contexts = ServicePrincipal('su', 'actual'), []

    async def work(name, callback, action, tenant, principal, payload, **kwargs):
        assert (action, tenant, principal, payload) == ('hard', 'foreign', actor, {'hard_limit_mb': 1})
        assert kwargs['lane'] == 'control-io' and kwargs['owner'] == 'management.quota'
        contexts.append(kwargs['context'])
        return {'hard_limit_bytes': 1}

    mocker.patch.object(module, 'run_blocking', side_effect=work)
    assert await module.write_quota('hard', 'foreign', actor, {'hard_limit_mb': 1}) == {'hard_limit_bytes': 1}
    assert len(contexts) == 1 and contexts[0].cancelled.is_set()


async def test_deadline_cancels_and_warns_once(mocker, caplog):
    from management.services.knowledge_base import quota_write as module

    contexts, closed = [], []

    async def work(*args, **kwargs):
        contexts.append(kwargs['context'])
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    mocker.patch.object(module, 'run_blocking', side_effect=work)
    mocker.patch.object(module, 'OperationContext', side_effect=lambda name, deadline, **kw:
        OperationContext(name, monotonic() + .02, **kw))
    with pytest.raises(DeadlineExceeded):
        await module.write_quota('remove', 'tenant', ServicePrincipal('u', 'tenant'), {})
    assert closed == [True] and contexts[0].cancelled.is_set()
    assert sum('quota_write_timeout' in r.message for r in caplog.records) == 1
    assert not any(r.levelname == 'ERROR' for r in caplog.records)
