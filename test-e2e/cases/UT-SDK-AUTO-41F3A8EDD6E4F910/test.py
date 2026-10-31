from __future__ import annotations

import asyncio
import threading
import time

import pytest

from nexent.core.concurrency.bounded_executor import BoundedExecutor
from nexent.core.concurrency.manager import ThreadManager
from nexent.core.concurrency.models import (
    DrainResult,
    ExecutionState,
    LanePolicy,
    ManagedTaskSpec,
    ManagerState,
)


def _wait_until(predicate, timeout=10.0, interval=0.005):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError('condition not satisfied within timeout')


def _spec(task_name):
    return ManagedTaskSpec(task_name=task_name, owner='sdk-ut')


@pytest.mark.case_id('UT-SDK-AUTO-41F3A8EDD6E4F910')
@pytest.mark.stage('D1')
def test_thread_manager_lane_isolation_and_fifo_ordering():
    manager = ThreadManager(
        service_name='sdk-ut',
        lane_policies={
            'a': LanePolicy(name='a', max_workers=1, max_queue_size=8, queue_timeout_seconds=None),
            'b': LanePolicy(name='b', max_workers=2, max_queue_size=8, queue_timeout_seconds=None),
        },
    )
    manager.start()

    a1_release = threading.Event()
    b1_release = threading.Event()
    b1_running = threading.Event()
    order = []

    def a1_fn():
        order.append('A1')
        a1_release.wait()

    def a2_fn():
        order.append('A2')

    def b1_fn():
        b1_running.set()
        b1_release.wait()

    try:
        assert manager.state == ManagerState.RUNNING
        assert set(manager._executors) == {'a', 'b'}
        assert all(isinstance(executor, BoundedExecutor) for executor in manager._executors.values())
        assert manager._executors['a'] is not manager._executors['b']

        a1 = manager.submit('a', _spec('a1'), a1_fn)
        _wait_until(lambda: a1.state == ExecutionState.RUNNING)
        assert order == ['A1']

        a2 = manager.submit('a', _spec('a2'), a2_fn)
        assert a2.state == ExecutionState.QUEUED
        assert order == ['A1']

        b1 = manager.submit('b', _spec('b1'), b1_fn)
        _wait_until(lambda: b1.state == ExecutionState.RUNNING)
        assert b1.state == ExecutionState.RUNNING
        assert b1_running.is_set()
        assert a2.state == ExecutionState.QUEUED

        a1_release.set()
        _wait_until(lambda: a2.state == ExecutionState.SUCCEEDED)
        assert order == ['A1', 'A2']

        b1_release.set()
        _wait_until(lambda: b1.state == ExecutionState.SUCCEEDED)

        result = asyncio.run(manager.shutdown(5))
        assert isinstance(result, DrainResult)
        assert result.stuck_execution_ids == ()
        assert manager.state == ManagerState.CLOSED
    finally:
        a1_release.set()
        b1_release.set()
        if manager.state not in {ManagerState.CLOSED, ManagerState.CLOSED_WITH_STUCK}:
            try:
                asyncio.run(manager.shutdown(5))
            except BaseException:
                pass
