# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime joins its prepared worker before recording the durable terminal."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from redis.exceptions import RedisError

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.agent_execution import RunIdentity
from runtime.agentos import prepared_run

ACTOR = ServicePrincipal("user", "tenant")
IDENTITY = RunIdentity("tenant", "user", 42, "a" * 32)


@pytest.fixture
def terminal(mocker):
    async def inline(_name, fn, *args):
        return fn(*args)

    mocker.patch.object(prepared_run, "_control_io", side_effect=inline)

    async def monitor(_identity):
        await asyncio.Event().wait()

    mocker.patch.object(prepared_run, "_wait_for_stop", side_effect=monitor)
    return SimpleNamespace(
        finish=mocker.patch.object(prepared_run, "finish_execution", return_value=True),
        journal=SimpleNamespace(repair_terminal=Mock()),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_fails", [False, True])
@pytest.mark.parametrize("cancellations", [1, 2])
async def test_cancellation_joins_worker_and_records_stopped(mocker, terminal, worker_fails, cancellations):
    entered = asyncio.Event()
    finalizing = asyncio.Event()
    release = asyncio.Event()
    settled = Mock()

    async def run(*_args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finalizing.set()
            await release.wait()
            settled()
            if worker_fails:
                raise RuntimeError("worker cleanup failed")

    mocker.patch.object(prepared_run, "_run_snapshot", side_effect=run)
    producer = asyncio.create_task(prepared_run._produce(object(), ACTOR, IDENTITY, terminal.journal))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        producer.cancel()
        await asyncio.wait_for(finalizing.wait(), timeout=2)
        for _ in range(cancellations - 1):
            producer.cancel()
            await asyncio.sleep(0)
        assert not producer.done()
        terminal.finish.assert_not_called()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(producer), timeout=2)
    finally:
        release.set()
        await asyncio.gather(producer, return_exceptions=True)

    settled.assert_called_once_with()
    terminal.finish.assert_called_once_with(IDENTITY, "stopped")
    terminal.journal.repair_terminal.assert_called_once_with("stopped")


@pytest.mark.asyncio
@pytest.mark.parametrize("result", ["completed", "failed"])
async def test_worker_result_drives_execution_and_journal_terminal(mocker, terminal, result):
    async def run(*_args):
        if result == "failed":
            raise RuntimeError("execution failed")
        return result

    mocker.patch.object(prepared_run, "_run_snapshot", side_effect=run)
    await prepared_run._produce(object(), ACTOR, IDENTITY, terminal.journal)
    terminal.finish.assert_called_once_with(IDENTITY, result)
    terminal.journal.repair_terminal.assert_called_once_with(result)


@pytest.mark.asyncio
async def test_journal_write_failure_leaves_execution_terminal_for_reconciliation(mocker, terminal, caplog):
    mocker.patch.object(prepared_run, "_run_snapshot", return_value="completed")
    terminal.journal.repair_terminal.side_effect = RedisError("journal unavailable")

    await prepared_run._produce(object(), ACTOR, IDENTITY, terminal.journal)

    terminal.finish.assert_called_once_with(IDENTITY, "completed")
    terminal.journal.repair_terminal.assert_called_once_with("completed")
    assert "terminal will be reconciled" in caplog.text
