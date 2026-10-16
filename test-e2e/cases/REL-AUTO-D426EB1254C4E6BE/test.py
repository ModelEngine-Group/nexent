from __future__ import annotations

import asyncio
import threading
import time

import pytest

from nexent.core.concurrency import (
    ExecutionState,
    LanePolicy,
    ManagedThreadSpec,
    ManagerState,
    ThreadCapacityExceeded,
    ThreadManager,
)


def _make_manager(service_name='api-to-mcp', max_workers=2, cancel_grace=1.0):
    return ThreadManager(
        service_name=service_name,
        lane_policies={
            'background-service': LanePolicy(
                name='background-service',
                max_workers=max_workers,
                max_queue_size=4,
                queue_timeout_seconds=0,
                cancel_grace_seconds=cancel_grace,
                shutdown_grace_seconds=5.0,
            ),
        },
    )


def _blocking_worker(started=None):
    def worker(cancel_event):
        if started is not None:
            started.set()
        while not cancel_event.is_set():
            time.sleep(0.005)
    return worker


@pytest.mark.stage('D5')
@pytest.mark.case_id("REL-AUTO-D426EB1254C4E6BE")
def _check_management_api_register_and_start_enters_running_state():
    manager = _make_manager()
    manager.start()
    started = threading.Event()

    execution = manager.register_service(
        ManagedThreadSpec(
            task_name='mcp-management-api',
            owner='api-to-mcp',
            lane='background-service',
        ),
        _blocking_worker(started),
    )
    assert execution.state is ExecutionState.REGISTERED

    manager.start_service(execution.execution_id)
    assert started.wait(timeout=5)

    snapshot = manager.snapshot()
    match = [e for e in snapshot.executions if e.execution_id == execution.execution_id]
    assert len(match) == 1
    assert match[0].task_name == 'mcp-management-api'
    assert match[0].thread_alive is True

    result = manager.cancel(execution.execution_id, reason='teardown', wait_timeout=5)
    assert result.cancelled is True


@pytest.mark.stage('D5')
def _check_cancel_invokes_close_hook_and_sets_should_exit():
    manager = _make_manager()
    manager.start()

    class FakeServer:
        should_exit = False

    server = FakeServer()

    execution = manager.register_service(
        ManagedThreadSpec(
            task_name='mcp-management-api',
            owner='api-to-mcp',
            lane='background-service',
            close_hook=lambda: setattr(server, 'should_exit', True),
        ),
        _blocking_worker(),
    )
    manager.start_service(execution.execution_id)

    result = manager.cancel(
        execution.execution_id,
        reason='MCP server stopping',
        wait_timeout=5,
    )
    assert result.cancelled is True
    assert server.should_exit is True


@pytest.mark.stage('D5')
def _check_shutdown_calls_log_stream_close_hook_and_leaves_no_stuck_threads():
    manager = _make_manager()
    manager.start()

    closed = threading.Event()

    class FakeStream:
        def close(self):
            closed.set()

    stream = FakeStream()

    execution = manager.register_service(
        ManagedThreadSpec(
            task_name='docker-mcp-log-stream',
            owner='config',
            lane='background-service',
            close_hook=stream.close,
        ),
        _blocking_worker(),
    )
    manager.start_service(execution.execution_id)

    result = asyncio.run(manager.shutdown(timeout=5))
    assert result.stuck_execution_ids == ()
    assert closed.wait(timeout=5) is True
    assert manager.state is ManagerState.CLOSED


@pytest.mark.stage('D5')
def _check_log_stream_thread_exception_is_isolated_and_finalized():
    manager = _make_manager()
    manager.start()

    def failing_worker(cancel_event):
        raise RuntimeError('simulated log stream read failure')

    execution = manager.register_service(
        ManagedThreadSpec(
            task_name='docker-mcp-log-stream',
            owner='config',
            lane='background-service',
        ),
        failing_worker,
    )
    manager.start_service(execution.execution_id)

    with pytest.raises(RuntimeError, match='log stream read failure'):
        execution.future.result(timeout=5)

    snapshot = manager.snapshot()
    assert snapshot.active_count == 0


@pytest.mark.stage('D5')
def _check_rebuild_manager_after_shutdown_has_no_stale_threads():
    first = _make_manager()
    first.start()
    first_seen = threading.Event()

    execution = first.register_service(
        ManagedThreadSpec(
            task_name='mcp-management-api',
            owner='api-to-mcp',
            lane='background-service',
        ),
        _blocking_worker(first_seen),
    )
    first.start_service(execution.execution_id)
    assert first_seen.wait(timeout=5)

    stale_thread_name = None
    for snap in first.snapshot().executions:
        if snap.execution_id == execution.execution_id:
            stale_thread_name = snap.thread_name
    assert stale_thread_name is not None

    asyncio.run(first.shutdown(timeout=5))
    assert first.state is ManagerState.CLOSED

    second = _make_manager()
    second.start()
    second_seen = threading.Event()

    execution2 = second.register_service(
        ManagedThreadSpec(
            task_name='mcp-management-api-rebuilt',
            owner='api-to-mcp',
            lane='background-service',
        ),
        _blocking_worker(second_seen),
    )
    second.start_service(execution2.execution_id)
    assert second_seen.wait(timeout=5)

    alive_names = {t.name for t in threading.enumerate()}
    assert stale_thread_name not in alive_names
    assert any('mcp-management-api-rebuilt' in name for name in alive_names)

    asyncio.run(second.shutdown(timeout=5))


@pytest.mark.stage('D5')
def _check_register_service_rejects_duplicate_dedicated_threads():
    manager = _make_manager(max_workers=1)
    manager.start()

    execution = manager.register_service(
        ManagedThreadSpec(
            task_name='mcp-management-api',
            owner='api-to-mcp',
            lane='background-service',
        ),
        _blocking_worker(),
    )
    manager.start_service(execution.execution_id)

    with pytest.raises(ThreadCapacityExceeded):
        manager.register_service(
            ManagedThreadSpec(
                task_name='duplicate-mcp-management-api',
                owner='api-to-mcp',
                lane='background-service',
            ),
            _blocking_worker(),
        )

    manager.cancel(execution.execution_id, reason='teardown', wait_timeout=5)
    asyncio.run(manager.shutdown(timeout=5))


@pytest.mark.stage('D5')
@pytest.mark.case_id("REL-AUTO-D426EB1254C4E6BE")
def test_mcp_managed_thread_lifecycle_contract():
    _check_management_api_register_and_start_enters_running_state()
    _check_cancel_invokes_close_hook_and_sets_should_exit()
    _check_shutdown_calls_log_stream_close_hook_and_leaves_no_stuck_threads()
    _check_log_stream_thread_exception_is_isolated_and_finalized()
    _check_rebuild_manager_after_shutdown_has_no_stale_threads()
    _check_register_service_rejects_duplicate_dedicated_threads()
