# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PERSONAL-DEFAULT-02 owns managed storage work and a finite root deadline."""

import asyncio
from time import monotonic

import pytest
from nexent.storage.errors import DeadlineExceeded, ScopeDenied
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal


async def test_configuration_receives_actual_actor_and_cancels_owned_context(mocker):
    from management.services.knowledge_base import (
        personal_quota_configuration as module,
    )

    contexts, actor = [], ServicePrincipal('su', 'actual')

    async def work(name, callback, operation, tenant, principal, payload, **kwargs):
        assert (operation, tenant, principal, payload) == ('write', 'target', actor, {'quota_limit_bytes': 5})
        assert kwargs['lane'] == 'control-io' and kwargs['owner'] == 'management.quota'
        contexts.append(kwargs['context'])
        return {'quota_limit_bytes': 5}

    mocker.patch.object(module, 'run_blocking', side_effect=work)
    assert await module.personal_quota_configuration('write', 'target', actor, {'quota_limit_bytes': 5}) == {'quota_limit_bytes': 5}
    assert len(contexts) == 1 and contexts[0].cancelled.is_set()


async def test_root_deadline_exits_once_and_warns_without_error(mocker, caplog):
    from management.services.knowledge_base import (
        personal_quota_configuration as module,
    )

    contexts, exited = [], []

    async def work(*args, **kwargs):
        contexts.append(kwargs['context'])
        try:
            await asyncio.Event().wait()
        finally:
            exited.append(True)

    mocker.patch.object(module, 'run_blocking', side_effect=work)
    mocker.patch.object(module, 'OperationContext', side_effect=lambda name, deadline, **kw:
        OperationContext(name, monotonic() + .02, **kw))
    with pytest.raises(DeadlineExceeded):
        await module.personal_quota_configuration('read', 'target', ServicePrincipal('u', 'actual'))
    assert exited == [True] and contexts[0].cancelled.is_set()
    assert sum('personal_quota_config_timeout' in r.message for r in caplog.records) == 1
    assert not any(r.levelname == 'ERROR' for r in caplog.records)


async def test_permission_refusal_has_no_retry_or_unlimited_fallback(mocker):
    from management.services.knowledge_base import (
        personal_quota_configuration as module,
    )

    work = mocker.patch.object(module, 'run_blocking', side_effect=ScopeDenied())
    with pytest.raises(ScopeDenied):
        await module.personal_quota_configuration('read', 'target', ServicePrincipal('u', 'actual'))
    assert work.await_count == 1
