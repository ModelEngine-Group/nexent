# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB-ADMIT-02: a timed-out queued upload admission must not write later."""

import asyncio
from contextlib import contextmanager
from time import monotonic
from types import SimpleNamespace

import pytest
from management.services.file import upload_admission as module
from nexent.storage.errors import DeadlineExceeded, OperationCancelled


async def test_total_deadline_cancels_the_owned_scope_and_late_queue_start(monkeypatch, caplog):
    queued = []
    opened = []
    monkeypatch.setattr(module, 'monotonic', lambda: monotonic() - 9.97)

    async def wait_for_start(name, callback, **kwargs):
        queued.append(callback)
        assert kwargs == {'lane': 'control-io', 'owner': 'management.file'}
        await asyncio.Event().wait()

    @contextmanager
    def ports(actor, *, context):
        context.remaining()
        opened.append(actor)
        yield None, None

    monkeypatch.setattr(module, 'run_blocking', wait_for_start)
    monkeypatch.setattr(module, 'knowledge_admission_ports', ports)
    started = monotonic()
    with pytest.raises(DeadlineExceeded):
        await module.admit_knowledge_uploads([{'private_filename': 'do-not-log'}],
                                            actor=SimpleNamespace(user_id='u', tenant_id='t'))
    assert monotonic() - started < 1 and len(queued) == 1
    with pytest.raises(OperationCancelled):
        queued[0]()
    assert not opened
    warnings = [record for record in caplog.records if record.name == module.__name__]
    assert len(warnings) == 1 and warnings[0].levelname == 'WARNING'
    assert 'threshold_seconds=10' in warnings[0].getMessage()
    assert 'do-not-log' not in warnings[0].getMessage()


async def test_empty_batch_does_not_schedule_or_open_storage(monkeypatch):
    async def reject(*args, **kwargs):
        raise AssertionError('Empty batch must not enter the queue')

    monkeypatch.setattr(module, 'run_blocking', reject)
    assert await module.admit_knowledge_uploads([], actor=SimpleNamespace(user_id='u', tenant_id='t')) == []
