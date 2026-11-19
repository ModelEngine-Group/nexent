# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UPLOAD-CONTEXT-02 keeps metadata reads owned, cancellable and bounded."""

import asyncio
from time import monotonic

import pytest
from nexent.storage.errors import DeadlineExceeded, ScopeDenied
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal


async def test_actual_actor_passed_to_managed_read_and_context_closed(mocker):
    from management.services.file import upload_context as module

    actor, contexts = ServicePrincipal('reader', 'actual-tenant'), []

    async def work(name, action, index, principal, **kwargs):
        assert index == 'kb' and principal == actor
        assert kwargs['lane'] == 'control-io' and kwargs['owner'] == 'management.file'
        contexts.append(kwargs['context'])
        return 'result'

    runner = mocker.patch.object(module, 'run_blocking', side_effect=work)
    assert await module.resolve_upload_context('kb', actor) == 'result'
    assert runner.await_count == 1 and contexts[0].cancelled.is_set()


async def test_metadata_timeout_cancels_pending_work_and_warns_once(mocker, caplog):
    from management.services.file import upload_context as module

    contexts, closed = [], []

    async def work(*args, **kwargs):
        contexts.append(kwargs['context'])
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    mocker.patch.object(module, 'run_blocking', side_effect=work)
    mocker.patch.object(module, 'OperationContext', side_effect=lambda name, deadline, **kwargs:
        OperationContext(name, monotonic() + .02, **kwargs))
    with pytest.raises(DeadlineExceeded):
        await module.resolve_upload_context('kb', ServicePrincipal('u', 't'))
    assert closed == [True] and contexts[0].cancelled.is_set()
    assert sum('upload_context_timeout' in record.message for record in caplog.records) == 1
    assert not any(record.levelname == 'ERROR' for record in caplog.records)


async def test_refusal_is_not_converted_to_generic_upload_or_retried(mocker):
    from management.services.file import upload_context as module

    runner = mocker.patch.object(module, 'run_blocking', side_effect=ScopeDenied())
    with pytest.raises(ScopeDenied):
        await module.resolve_upload_context('kb', ServicePrincipal('u', 't'))
    assert runner.await_count == 1
