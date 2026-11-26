# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime.identity import reserve_runtime_run


@pytest.fixture
def admission(monkeypatch):
    future = Future()
    execution = SimpleNamespace(future=future)
    threads = SimpleNamespace(submit=Mock(return_value=execution))
    monkeypatch.setattr('runtime.thread_management.runtime_thread_manager', threads)
    manager = Mock()
    return future, threads, manager


@pytest.mark.asyncio
async def test_local_admission_keeps_existing_sync_call_shape(admission):
    _, threads, manager = admission
    manager.reserve_agent_run.return_value = 'local-token'
    assert await reserve_runtime_run(manager, 1, 'user') == 'local-token'
    manager.reserve_agent_run.assert_called_once_with(1, 'user')
    threads.submit.assert_not_called()


@pytest.mark.asyncio
async def test_distributed_reservation_uses_bounded_managed_control_lane(admission):
    future, threads, manager = admission
    future.set_result('distributed-token')
    result = await reserve_runtime_run(manager, 1, 'user', tenant_id='tenant', execution_run_id='a' * 32)
    assert result == 'distributed-token'
    assert threads.submit.call_args.args[0] == 'control-io'
    assert threads.submit.call_args.kwargs == {'tenant_id': 'tenant', 'execution_run_id': 'a' * 32}
    manager.release_agent_run_reservation.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_wait_releases_only_its_late_successful_reservation(admission):
    future, _, manager = admission
    task = asyncio.create_task(reserve_runtime_run(manager, 1, 'user', tenant_id='tenant'))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not future.cancelled()
    future.set_result('late-owned-token')
    await asyncio.sleep(0)
    manager.release_agent_run_reservation.assert_called_once_with(1, 'user', 'late-owned-token')


@pytest.mark.asyncio
async def test_cancelled_wait_does_not_release_someone_else_on_failure(admission):
    future, _, manager = admission
    task = asyncio.create_task(reserve_runtime_run(manager, 1, 'user', tenant_id='tenant'))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    future.set_exception(RuntimeError('not admitted'))
    await asyncio.sleep(0)
    manager.release_agent_run_reservation.assert_not_called()
