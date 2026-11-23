import asyncio
import json
import sys
import threading
import time
import types
from contextvars import ContextVar
from pathlib import Path

import pytest

# Keep this isolated SDK unit test independent from optional integrations that
# are eagerly imported by nexent.__init__.
_SDK_PACKAGE = Path(__file__).resolve().parents[4] / "sdk" / "nexent"
if "nexent" not in sys.modules:
    nexent_package = types.ModuleType("nexent")
    nexent_package.__path__ = [str(_SDK_PACKAGE)]
    sys.modules["nexent"] = nexent_package
if "nexent.core" not in sys.modules:
    core_package = types.ModuleType("nexent.core")
    core_package.__path__ = [str(_SDK_PACKAGE / "core")]
    sys.modules["nexent.core"] = core_package

from nexent.core.concurrency import (
    ExecutionState,
    LanePolicy,
    ManagedTaskSpec,
    ManagedThreadSpec,
    ManagerState,
    ThreadCapacityExceeded,
    ThreadManager,
    ThreadManagerDraining,
    ThreadQueueTimedOut,
    clear_default_thread_manager,
    get_current_thread_manager,
    run_blocking,
    set_default_thread_manager,
)


def _manager(*, workers=1, queue_size=1, cancel_grace=0.05, queue_timeout=0):
    manager = ThreadManager(
        service_name="test-runtime",
        lane_policies={
            "agent-run": LanePolicy(
                name="agent-run",
                max_workers=workers,
                max_queue_size=queue_size,
                queue_timeout_seconds=queue_timeout,
                cancel_grace_seconds=cancel_grace,
                shutdown_grace_seconds=0.2,
            ),
            "background-service": LanePolicy(
                name="background-service",
                max_workers=1,
                max_queue_size=0,
                queue_timeout_seconds=0,
                cancel_grace_seconds=cancel_grace,
                shutdown_grace_seconds=0.2,
            ),
            "model-tool-io": LanePolicy(
                name="model-tool-io",
                max_workers=1,
                max_queue_size=1,
                queue_timeout_seconds=0,
                cancel_grace_seconds=cancel_grace,
                shutdown_grace_seconds=0.2,
            ),
        },
    )
    manager.start()
    return manager


def _spec(name):
    return ManagedTaskSpec(task_name=name, owner="test")


def test_tc_tlm_001_successful_task_reaches_terminal_state_and_cleans_active_registry():
    manager = _manager()

    execution = manager.submit("agent-run", _spec("success"), lambda: "done")

    assert execution.future.result(timeout=1) == "done"
    assert execution.state is ExecutionState.SUCCEEDED
    assert manager.snapshot().active_count == 0
    assert manager.snapshot().completed_count == 1
    asyncio.run(manager.shutdown(timeout=1))


def test_snapshot_reports_lane_capacity_and_current_use():
    manager = _manager(workers=1, queue_size=1)
    release = threading.Event()
    started = threading.Event()
    execution = manager.submit(
        "agent-run",
        _spec("capacity-probe"),
        lambda: (started.set(), release.wait(1)),
    )
    assert started.wait(1)

    lane = next(item for item in manager.snapshot().lanes if item.name == "agent-run")
    assert lane.max_workers == 1
    assert lane.max_queue_size == 1
    assert lane.capacity == 2
    assert lane.active_count == 1
    assert lane.running_count == 1
    assert lane.available_count == 1

    release.set()
    execution.future.result(timeout=1)
    asyncio.run(manager.shutdown(timeout=1))


def test_tc_tlm_017_normal_lifecycle_and_snapshot_do_not_emit_logs(caplog):
    manager = _manager()
    with caplog.at_level("INFO", logger="thread_manager"):
        manager.snapshot()
        manager.snapshot()
        manager.metrics_snapshot()
        execution = manager.submit("agent-run", _spec("audit-counts"), lambda: "done")
        assert execution.future.result(timeout=1) == "done"
        asyncio.run(manager.shutdown(timeout=1))
        asyncio.run(manager.shutdown(timeout=1))

    assert [record for record in caplog.records if record.name == "thread_manager"] == []

def test_tc_tlm_002_queued_task_can_be_cancelled_without_running():
    manager = _manager()
    release = threading.Event()
    started = threading.Event()
    second_ran = threading.Event()

    first = manager.submit(
        "agent-run",
        _spec("blocker"),
        lambda: (started.set(), release.wait(1)),
    )
    assert started.wait(1)
    second = manager.submit(
        "agent-run",
        _spec("queued"),
        lambda: second_ran.set(),
    )

    result = manager.cancel(second.execution_id, reason="test cancellation")

    assert result.cancelled is True
    assert second.state is ExecutionState.CANCELLED
    assert second_ran.is_set() is False
    release.set()
    first.future.result(timeout=1)
    asyncio.run(manager.shutdown(timeout=1))


def test_tc_tlm_003_running_task_receives_cancel_event_and_close_hook_once():
    manager = _manager(cancel_grace=0.5)
    started = threading.Event()
    close_calls = []

    def target(cancel_event):
        started.set()
        assert cancel_event.wait(1)

    execution = manager.submit(
        "agent-run",
        ManagedTaskSpec(
            task_name="cooperative",
            owner="test",
            pass_cancel_event=True,
            close_hook=lambda: close_calls.append("closed"),
        ),
        target,
    )
    assert started.wait(1)

    result = manager.cancel(execution.execution_id, reason="requested")

    assert result.cancelled is True
    execution.future.result(timeout=1)
    assert execution.state is ExecutionState.CANCELLED
    assert close_calls == ["closed"]
    assert manager.snapshot().active_count == 0
    asyncio.run(manager.shutdown(timeout=1))


def test_tc_tlm_004_uncooperative_task_is_reported_stuck_until_it_really_exits():
    manager = _manager(cancel_grace=0.01)
    started = threading.Event()
    release = threading.Event()

    def target():
        started.set()
        release.wait(1)

    execution = manager.submit("agent-run", _spec("stuck"), target)
    assert started.wait(1)

    result = manager.cancel(execution.execution_id, reason="requested")

    assert result.stuck is True
    assert execution.state is ExecutionState.STUCK
    assert manager.snapshot().stuck_count == 1
    assert manager.snapshot().active_count == 1
    release.set()
    execution.future.result(timeout=1)
    assert execution.state is ExecutionState.CANCELLED
    assert manager.snapshot().active_count == 0
    asyncio.run(manager.shutdown(timeout=1))


def test_tc_tlm_005_worker_and_queue_capacity_rejects_extra_task(caplog):
    manager = _manager(workers=1, queue_size=1)
    release = threading.Event()
    started = threading.Event()
    first = manager.submit(
        "agent-run",
        _spec("first"),
        lambda: (started.set(), release.wait(1)),
    )
    assert started.wait(1)
    second = manager.submit("agent-run", _spec("second"), lambda: None)

    with (
        caplog.at_level("INFO", logger="thread_manager"),
        pytest.raises(ThreadCapacityExceeded) as exc_info,
    ):
        manager.submit("agent-run", _spec("rejected"), lambda: None)

    assert exc_info.value.lane == "agent-run"
    assert manager.snapshot().rejected_count == 1
    assert manager.snapshot().active_count == 2
    rejected_event = next(
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "thread_manager"
        and json.loads(record.getMessage())["event"] == "thread_task_rejected"
        and json.loads(record.getMessage())["execution"]["task_name"] == "rejected"
    )
    assert rejected_event["reason"] == "capacity"
    assert rejected_event["counts"]["managed_active"] == 2
    assert not any(
        json.loads(record.getMessage())["event"] == "managed_execution_released"
        and json.loads(record.getMessage())["execution"]["execution_id"]
        == rejected_event["execution"]["execution_id"]
        for record in caplog.records
        if record.name == "thread_manager"
    )
    release.set()
    first.future.result(timeout=1)
    second.future.result(timeout=1)
    asyncio.run(manager.shutdown(timeout=1))


def test_ut_sdk_tlm_025_capacity_rejection_is_immediate_and_never_runs_target():
    manager = _manager(workers=1, queue_size=1, queue_timeout=0.5)
    release = threading.Event()
    started = threading.Event()
    rejected_target_ran = threading.Event()
    first = manager.submit(
        "agent-run",
        _spec("capacity-blocker"),
        lambda: (started.set(), release.wait(1)),
    )
    assert started.wait(1)
    second = manager.submit("agent-run", _spec("capacity-queued"), lambda: None)

    began = time.monotonic()
    with pytest.raises(ThreadCapacityExceeded):
        manager.submit(
            "agent-run",
            _spec("capacity-rejected"),
            rejected_target_ran.set,
        )

    assert time.monotonic() - began < 0.1
    assert rejected_target_ran.is_set() is False
    assert manager.snapshot().active_count == 2
    release.set()
    first.future.result(timeout=1)
    second.future.result(timeout=1)
    asyncio.run(manager.shutdown(timeout=1))


@pytest.mark.asyncio
async def test_ut_sdk_tlm_026_queued_deadline_cancels_before_target_starts():
    manager = _manager(workers=1, queue_size=1, queue_timeout=0.05)
    release = threading.Event()
    started = threading.Event()
    queued_target_ran = threading.Event()
    first = manager.submit(
        "agent-run",
        _spec("deadline-blocker"),
        lambda: (started.set(), release.wait(1)),
    )
    assert started.wait(1)
    queued = manager.submit(
        "agent-run",
        _spec("deadline-queued"),
        queued_target_ran.set,
    )

    with pytest.raises(ThreadQueueTimedOut):
        await manager.wait_until_started(queued)

    assert queued.state is ExecutionState.TIMED_OUT
    assert queued_target_ran.is_set() is False
    assert queued.execution_id not in manager.snapshot().active_execution_ids
    record = next(
        item for item in manager.metrics_snapshot() if item.task_name == "deadline-queued"
    )
    assert record.timed_out_count == 1
    release.set()
    first.future.result(timeout=1)
    await manager.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_ut_sdk_tlm_026_worker_start_wins_queue_deadline_race():
    manager = _manager(workers=1, queue_size=1, queue_timeout=0.2)
    release = threading.Event()
    started = threading.Event()
    queued_started = threading.Event()
    queued_release = threading.Event()
    first = manager.submit(
        "agent-run",
        _spec("race-blocker"),
        lambda: (started.set(), release.wait(1)),
    )
    assert started.wait(1)
    queued = manager.submit(
        "agent-run",
        _spec("race-queued"),
        lambda: (queued_started.set(), queued_release.wait(1)),
    )

    release.set()
    await manager.wait_until_started(queued)

    assert queued_started.wait(1)
    assert queued.state is ExecutionState.RUNNING
    queued_release.set()
    first.future.result(timeout=1)
    queued.future.result(timeout=1)
    await manager.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_tc_tlm_011_drain_rejects_new_work_and_cancels_queued_work():
    manager = _manager(cancel_grace=0.5)
    release = threading.Event()
    started = threading.Event()

    def cooperative(cancel_event):
        started.set()
        cancel_event.wait(1)
        release.set()

    running = manager.submit(
        "agent-run",
        ManagedTaskSpec(
            task_name="running",
            owner="test",
            pass_cancel_event=True,
        ),
        cooperative,
    )
    assert started.wait(1)
    queued = manager.submit("agent-run", _spec("queued"), lambda: None)

    result = await manager.drain(timeout=1)

    assert result.stuck_execution_ids == ()
    assert running.state is ExecutionState.CANCELLED
    assert queued.state is ExecutionState.CANCELLED
    assert manager.state is ManagerState.DRAINING
    with pytest.raises(ThreadManagerDraining):
        manager.submit("agent-run", _spec("late"), lambda: None)
    await manager.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_tc_tlm_001_async_run_preserves_contextvars():
    manager = _manager()
    request_id = ContextVar("request_id", default="missing")
    request_id.set("request-123")

    value = await manager.run(
        "agent-run",
        _spec("context"),
        request_id.get,
    )

    assert value == "request-123"
    await manager.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_async_caller_cancellation_does_not_block_event_loop_or_mark_stuck():
    manager = _manager(cancel_grace=0.5)
    started = threading.Event()
    release = threading.Event()

    def target(cancel_event):
        started.set()
        cancel_event.wait(1)
        release.wait(1)

    task = asyncio.create_task(
        manager.run(
            "agent-run",
            ManagedTaskSpec(
                task_name="async-cancel",
                owner="test",
                pass_cancel_event=True,
            ),
            target,
        )
    )
    assert await asyncio.to_thread(started.wait, 1)
    began = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert time.monotonic() - began < 0.2
    assert manager.snapshot().stuck_count == 0
    release.set()
    await manager.shutdown(timeout=1)


def test_lane_policy_rejects_invalid_values():
    with pytest.raises(ValueError, match="max_workers"):
        LanePolicy(name="bad", max_workers=0, max_queue_size=0)


def test_shutdown_completes_with_no_managed_threads_left():
    manager = _manager()
    execution = manager.submit("agent-run", _spec("short"), time.monotonic)
    execution.future.result(timeout=1)

    result = asyncio.run(manager.shutdown(timeout=1))

    assert result.stuck_execution_ids == ()
    assert manager.state is ManagerState.CLOSED
    assert manager.snapshot().active_count == 0


def test_tc_tlm_012_registered_service_thread_stops_and_joins():
    manager = _manager(cancel_grace=0.5)
    started = threading.Event()
    close_calls = []

    def service(cancel_event):
        started.set()
        cancel_event.wait(1)

    execution = manager.register_service(
        ManagedThreadSpec(
            task_name="maintenance-loop",
            owner="test",
            close_hook=lambda: close_calls.append("closed"),
        ),
        service,
    )
    assert execution.state is ExecutionState.REGISTERED

    manager.start_service(execution.execution_id)
    assert started.wait(1)
    service_thread = execution.thread_ref()
    result = manager.cancel(execution.execution_id, reason="service shutdown")

    assert result.cancelled is True
    assert execution.state is ExecutionState.CANCELLED
    assert close_calls == ["closed"]
    assert service_thread is not None
    assert service_thread.is_alive() is False
    asyncio.run(manager.shutdown(timeout=1))


def test_tc_tlm_006_nested_sync_work_uses_separate_lane_and_current_manager():
    manager = _manager()

    def agent_target():
        assert get_current_thread_manager() is manager
        return manager.run_sync(
            "model-tool-io",
            _spec("nested-tool"),
            lambda: "tool-result",
            timeout=1,
        )

    execution = manager.submit("agent-run", _spec("agent"), agent_target)

    assert execution.future.result(timeout=1) == "tool-result"
    asyncio.run(manager.shutdown(timeout=1))


@pytest.mark.asyncio
async def test_process_default_manager_handles_async_blocking_offload():
    manager = _manager()
    set_default_thread_manager(manager)
    try:
        result = await run_blocking("default-offload", lambda: "done")
    finally:
        clear_default_thread_manager(manager)

    assert result == "done"
    await manager.shutdown(timeout=1)


def test_dedicated_services_respect_lane_worker_limit():
    manager = _manager()
    first = manager.register_service(
        ManagedThreadSpec(task_name="service-one", owner="test"),
        lambda cancel_event: cancel_event.wait(1),
    )

    with pytest.raises(ThreadCapacityExceeded):
        manager.register_service(
            ManagedThreadSpec(task_name="service-two", owner="test"),
            lambda cancel_event: cancel_event.wait(1),
        )

    manager.cancel(first.execution_id, reason="test cleanup")
    asyncio.run(manager.shutdown(timeout=1))


def test_tc_tlm_017_metrics_use_stable_labels_and_record_lifecycle():
    manager = _manager()
    execution = manager.submit("agent-run", _spec("measured-task"), lambda: "ok")
    assert execution.future.result(timeout=1) == "ok"

    record = next(
        item for item in manager.metrics_snapshot() if item.task_name == "measured-task"
    )
    assert record.lane == "agent-run"
    assert record.queued_count == 1
    assert record.started_count == 1
    assert record.completed_count == 1
    assert record.failed_count == 0
    assert record.total_queue_wait_ms >= 0
    assert record.total_run_ms >= 0
    assert "execution" not in record.__dict__
    asyncio.run(manager.shutdown(timeout=1))


def test_expired_deadline_never_runs_target_and_records_timed_out_state():
    manager = _manager()
    target = pytest.fail
    execution = manager.submit(
        "agent-run",
        ManagedTaskSpec(
            task_name="expired",
            owner="test",
            deadline_monotonic=time.monotonic() - 1,
        ),
        target,
        "expired target must not run",
    )

    with pytest.raises(TimeoutError):
        execution.future.result(timeout=1)
    assert execution.state is ExecutionState.TIMED_OUT
    record = next(
        item for item in manager.metrics_snapshot() if item.task_name == "expired"
    )
    assert record.cancelled_count == 1
    asyncio.run(manager.shutdown(timeout=1))
