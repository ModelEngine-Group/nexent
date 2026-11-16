# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""An attempt can close future writes and retain unknown or active write obligations."""

import asyncio

import pytest
from nexent.storage.errors import OperationCancelled, OutcomeUnknown, PartialFailure
from nexent.storage.models import WriteOutcome, WriteReceipt

from test.backend.services.test_knowledge_ingestion import (
    setup as setup,  # noqa: PLC0414 - Shared pytest fixture.
)


async def test_stopped_ingestor_cannot_start_another_execution(setup):
    s = setup
    assert s.service.stop_writes()
    with pytest.raises(OperationCancelled):
        await s.service.execute(s.request, **s.arguments)
    s.models.get.assert_not_awaited()
    s.vectors.upsert.assert_not_called()


async def test_confirmed_partial_failure_has_no_late_writer(setup):
    s = setup
    s.vectors.upsert.side_effect = PartialFailure(
        results=(WriteReceipt("failed", False, outcome=WriteOutcome.FAILED),)
    )
    with pytest.raises(PartialFailure):
        await s.service.execute(s.request, **s.arguments)
    assert s.service.stop_writes()


async def test_unknown_write_keeps_its_obligation_after_call_returns(setup):
    s = setup
    s.vectors.upsert.side_effect = OutcomeUnknown()
    with pytest.raises(OutcomeUnknown):
        await s.service.execute(s.request, **s.arguments)
    assert not s.service.stop_writes()


async def test_cancelled_queued_callback_cannot_write_later(setup, mocker):
    s = setup
    entered = asyncio.Event()
    pending = []

    async def queued(_name, action, *args, lane, owner, **kwargs):
        if getattr(action, "__name__", None) == "_upsert":
            pending.append(lambda: action(*args, **kwargs))
            entered.set()
            await asyncio.Event().wait()
        return action(*args, **kwargs)

    mocker.patch("runtime.knowledge_base.ingestion.run_blocking", side_effect=queued)
    task = asyncio.create_task(s.service.execute(s.request, **s.arguments))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert s.service.stop_writes()
    with pytest.raises(OperationCancelled):
        pending[0]()
    s.vectors.upsert.assert_not_called()
