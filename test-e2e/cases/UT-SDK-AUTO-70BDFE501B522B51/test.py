import asyncio
import threading

import pytest

from nexent.core.concurrency.errors import ThreadQueueTimedOut
from nexent.core.concurrency.manager import ThreadManager
from nexent.core.concurrency.models import ExecutionState, LanePolicy, ManagedTaskSpec


QUEUE_TIMEOUT = 0.05
CANCEL_GRACE = 0.2


def _policy(name, queue_timeout_seconds):
    return LanePolicy(
        name=name,
        max_workers=1,
        max_queue_size=2,
        queue_timeout_seconds=queue_timeout_seconds,
        cancel_grace_seconds=CANCEL_GRACE,
    )


def _spec(task_name):
    return ManagedTaskSpec(task_name=task_name, owner='ut')


def _occupy(release):
    release.wait(timeout=10)


@pytest.mark.asyncio
@pytest.mark.case_id('UT-SDK-AUTO-70BDFE501B522B51')
@pytest.mark.stage('D1')
async def test_wait_until_started_queue_timeout_and_short_circuit():
    manager = ThreadManager(
        'ut-sdk-auto-70bdfe501b522b51-cpu',
        {'cpu': _policy('cpu', QUEUE_TIMEOUT)},
    )
    manager.start()
    release = threading.Event()
    try:
        blocker_exec = manager.submit('cpu', _spec('blocker'), _occupy, release)
        assert blocker_exec.started_event.wait(timeout=2)

        queued_exec = manager.submit('cpu', _spec('queued'), lambda: None)
        assert queued_exec.state is ExecutionState.QUEUED
        assert queued_exec.queue_deadline_monotonic is not None

        with pytest.raises(ThreadQueueTimedOut) as exc_info:
            await manager.wait_until_started(queued_exec)

        error = exc_info.value
        assert error.lane == 'cpu'
        assert error.timeout_seconds == QUEUE_TIMEOUT
        assert queued_exec.state is ExecutionState.TIMED_OUT
        assert queued_exec.terminal_reason == 'queue deadline exceeded before start'
        snapshot = manager.snapshot()
        assert queued_exec.execution_id not in snapshot.active_execution_ids

        returned = await manager.wait_until_started(blocker_exec)
        assert returned is blocker_exec
        assert blocker_exec.state is ExecutionState.RUNNING
        assert blocker_exec.started_event.is_set()
    finally:
        release.set()
        await manager.shutdown(timeout=1)

    quick_manager = ThreadManager(
        'ut-sdk-auto-70bdfe501b522b51-quick',
        {'quick': _policy('quick', QUEUE_TIMEOUT)},
    )
    quick_manager.start()
    try:
        quick_exec = quick_manager.submit('quick', _spec('quick'), lambda: 'ok')
        assert quick_exec.future.result(timeout=2) == 'ok'
        assert quick_exec.state is ExecutionState.SUCCEEDED
        returned = await quick_manager.wait_until_started(quick_exec)
        assert returned is quick_exec
        assert quick_exec.state is ExecutionState.SUCCEEDED
    finally:
        await quick_manager.shutdown(timeout=1)

    no_timeout_manager = ThreadManager(
        'ut-sdk-auto-70bdfe501b522b51-null',
        {'null': _policy('null', None)},
    )
    no_timeout_manager.start()
    release_null = threading.Event()
    try:
        blocker_null = no_timeout_manager.submit('null', _spec('blocker'), _occupy, release_null)
        assert blocker_null.started_event.wait(timeout=2)

        queued_null = no_timeout_manager.submit('null', _spec('queued'), lambda: None)
        assert queued_null.state is ExecutionState.QUEUED
        assert queued_null.queue_deadline_monotonic is None

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(no_timeout_manager.wait_until_started(queued_null), timeout=0.15)

        assert queued_null.state is ExecutionState.QUEUED
    finally:
        release_null.set()
        await no_timeout_manager.shutdown(timeout=1)
