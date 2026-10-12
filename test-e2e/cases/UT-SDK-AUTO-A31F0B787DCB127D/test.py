import asyncio
import logging
import threading
import time

import pytest

try:
    from sdk.nexent.core.concurrency.manager import ThreadManager
    from sdk.nexent.core.concurrency.models import (
        ExecutionState,
        LanePolicy,
        ManagedTaskSpec,
        ManagedThreadSpec,
    )
except ImportError:  # pragma: no cover - repository layout compatibility
    from nexent.core.concurrency.manager import ThreadManager
    from nexent.core.concurrency.models import (
        ExecutionState,
        LanePolicy,
        ManagedTaskSpec,
        ManagedThreadSpec,
    )


@pytest.mark.case_id('UT-SDK-AUTO-A31F0B787DCB127D')
@pytest.mark.stage('D1')
def test_managed_task_cancellation_contract(caplog):
    caplog.set_level(logging.ERROR, logger='thread_manager')

    policy = LanePolicy(
        name='test-lane',
        max_workers=1,
        max_queue_size=1,
        queue_timeout_seconds=None,
        cancel_grace_seconds=0.5,
    )
    manager = ThreadManager(service_name='ut-cancel', lane_policies={'test-lane': policy})
    manager.start()

    release_first = threading.Event()
    release_stuck = threading.Event()

    def wait_running(execution, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if execution.state is ExecutionState.RUNNING:
                return
            time.sleep(0.001)
        raise AssertionError('execution never reached RUNNING')

    try:
        def first_fn():
            release_first.wait(timeout=10)
            return 'first'

        first = manager.submit('test-lane', ManagedTaskSpec(task_name='first', owner='ut'), first_fn)
        wait_running(first)

        def queued_fn():
            return 'queued'

        queued = manager.submit('test-lane', ManagedTaskSpec(task_name='queued', owner='ut'), queued_fn)
        assert queued.state is ExecutionState.QUEUED
        queued_result = manager.cancel(queued.execution_id, reason='test-cancel-queued')
        assert queued_result.cancelled is True
        assert queued_result.stuck is False
        assert queued.state is ExecutionState.CANCELLED

        release_first.set()
        assert first.future.result(timeout=5) == 'first'

        running_observed = {}
        running_holder = {}

        def running_fn(stop_event):
            stop_event.wait(timeout=5)
            execution = running_holder['execution']
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and execution.state is not ExecutionState.STOP_REQUESTED:
                time.sleep(0.001)
            running_observed['state'] = execution.state
            running_observed['reason'] = execution.terminal_reason
            return 'coop-done'

        running = manager.submit(
            'test-lane',
            ManagedTaskSpec(task_name='running', owner='ut', pass_cancel_event=True),
            running_fn,
        )
        running_holder['execution'] = running
        wait_running(running)

        running_result = manager.cancel(running.execution_id, reason='test-cancel-running')
        assert running_result.cancelled is True
        assert running_result.stuck is False
        assert running_observed['state'] is ExecutionState.STOP_REQUESTED
        assert running_observed['reason'] == 'test-cancel-running'
        assert running.state is ExecutionState.CANCELLED

        hook_calls = []

        def hook_increment():
            hook_calls.append(1)

        def hook_fn(stop_event):
            stop_event.wait(timeout=5)
            return 'hook-done'

        hook_exec = manager.submit(
            'test-lane',
            ManagedTaskSpec(task_name='hook', owner='ut', pass_cancel_event=True, close_hook=hook_increment),
            hook_fn,
        )
        wait_running(hook_exec)
        hook_result = manager.cancel(hook_exec.execution_id, reason='test-cancel-hook')
        assert hook_result.cancelled is True
        assert len(hook_calls) == 1
        assert hook_exec.state is ExecutionState.CANCELLED

        def raising_hook():
            raise RuntimeError('hook boom')

        def raising_fn(stop_event):
            stop_event.wait(timeout=5)
            return 'raise-done'

        raise_exec = manager.submit(
            'test-lane',
            ManagedTaskSpec(task_name='raise-hook', owner='ut', pass_cancel_event=True, close_hook=raising_hook),
            raising_fn,
        )
        wait_running(raise_exec)
        raise_result = manager.cancel(raise_exec.execution_id, reason='test-cancel-raise-hook')
        assert raise_result.cancelled is True
        assert 'thread_close_hook_failed' in caplog.text

        registered_called = {'called': False}

        def svc_fn():
            registered_called['called'] = True

        registered = manager.register_service(
            ManagedThreadSpec(task_name='svc', owner='ut', lane='test-lane', close_hook=None, daemon=True),
            svc_fn,
        )
        assert registered.state is ExecutionState.REGISTERED
        reg_result = manager.cancel(registered.execution_id, reason='test-cancel-registered')
        assert reg_result.cancelled is True
        assert reg_result.stuck is False
        assert registered.state is ExecutionState.CANCELLED
        assert registered.cancel_event.is_set() is True
        assert registered.execution_id not in manager.snapshot().active_execution_ids
        assert registered_called['called'] is False

        def stuck_fn(stop_event):
            release_stuck.wait(timeout=10)
            return 'stuck-done'

        stuck_exec = manager.submit(
            'test-lane',
            ManagedTaskSpec(task_name='stuck-task', owner='ut', pass_cancel_event=True),
            stuck_fn,
        )
        wait_running(stuck_exec)
        stuck_result = manager.cancel(stuck_exec.execution_id, reason='test-cancel-stuck')
        assert stuck_result.cancelled is False
        assert stuck_result.stuck is True
        assert stuck_result.already_terminal is False
        assert stuck_exec.state is ExecutionState.STUCK
        stuck_records = [
            record
            for record in manager.metrics_snapshot()
            if record.lane == 'test-lane' and record.task_name == 'stuck-task'
        ]
        assert stuck_records and stuck_records[0].stuck_count >= 1

        release_stuck.set()
        assert stuck_exec.future.result(timeout=5) == 'stuck-done'

        unknown_result = manager.cancel('does-not-exist', reason='test-cancel-unknown')
        assert unknown_result.cancelled is False
        assert unknown_result.already_terminal is True
        assert unknown_result.stuck is False

        dup_calls = []

        def dup_hook():
            dup_calls.append(1)

        def dup_fn(stop_event):
            stop_event.wait(timeout=5)
            return 'dup-done'

        dup_exec = manager.submit(
            'test-lane',
            ManagedTaskSpec(task_name='dup', owner='ut', pass_cancel_event=True, close_hook=dup_hook),
            dup_fn,
        )
        wait_running(dup_exec)
        first_cancel = manager.cancel(dup_exec.execution_id, reason='test-cancel-dup-1')
        assert first_cancel.cancelled is True
        assert len(dup_calls) == 1
        second_cancel = manager.cancel(dup_exec.execution_id, reason='test-cancel-dup-2')
        assert second_cancel.cancelled is False
        assert second_cancel.already_terminal is True
        assert second_cancel.stuck is False
        assert len(dup_calls) == 1
    finally:
        release_first.set()
        release_stuck.set()
        asyncio.run(manager.shutdown(timeout=2))
