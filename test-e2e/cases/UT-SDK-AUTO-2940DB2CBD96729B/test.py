from __future__ import annotations

import threading

import pytest

from nexent.core.concurrency.errors import (
    ThreadManagerDraining,
    ThreadManagerNotRunning,
)
from nexent.core.concurrency.manager import ThreadManager
from nexent.core.concurrency.models import (
    ExecutionState,
    LanePolicy,
    ManagedTaskSpec,
    ManagedThreadSpec,
    ManagerState,
)


def _lane_policy() -> LanePolicy:
    return LanePolicy(
        name="model-tool-io",
        max_workers=1,
        max_queue_size=2,
        queue_timeout_seconds=0,
        cancel_grace_seconds=0.1,
    )


@pytest.mark.case_id("UT-SDK-AUTO-2940DB2CBD96729B")
@pytest.mark.stage("D1")
@pytest.mark.asyncio
async def test_drain_shutdown_reports_stuck_and_transitions_state() -> None:
    release_event = threading.Event()

    def blocking_task(cancel_event: threading.Event) -> str:  # noqa: ARG001
        release_event.wait()
        return "done"

    def normal_task() -> str:
        return "done"

    manager = ThreadManager("nexent-test-service", {"model-tool-io": _lane_policy()})
    manager.start()
    assert manager.state is ManagerState.RUNNING

    execution_a = manager.submit(
        "model-tool-io",
        ManagedTaskSpec(task_name="blocking", owner="ut", pass_cancel_event=True),
        blocking_task,
    )
    assert execution_a.started_event.wait(timeout=5)

    execution_b = manager.submit(
        "model-tool-io",
        ManagedTaskSpec(task_name="queued", owner="ut"),
        normal_task,
    )
    assert execution_b.state is ExecutionState.QUEUED

    drain_result = await manager.drain(timeout=0.05)
    assert manager.state is ManagerState.DRAINING
    assert drain_result.stuck_execution_ids == (execution_a.execution_id,)
    assert execution_a.state is ExecutionState.STUCK
    assert execution_b.state is ExecutionState.CANCELLED

    with pytest.raises(ThreadManagerDraining):
        manager.submit(
            "model-tool-io",
            ManagedTaskSpec(task_name="late", owner="ut"),
            normal_task,
        )

    shutdown_result = await manager.shutdown(timeout=0.05)
    assert manager.state is ManagerState.CLOSED_WITH_STUCK
    assert shutdown_result.stuck_execution_ids == (execution_a.execution_id,)
    assert shutdown_result.stuck_execution_ids == drain_result.stuck_execution_ids

    assert (await manager.shutdown(timeout=0.05)).stuck_execution_ids == (
        execution_a.execution_id,
    )
    assert (await manager.drain(timeout=0.05)).stuck_execution_ids == (
        execution_a.execution_id,
    )

    with pytest.raises(ThreadManagerNotRunning):
        manager.submit(
            "model-tool-io",
            ManagedTaskSpec(task_name="after-close", owner="ut"),
            normal_task,
        )
    with pytest.raises(ThreadManagerNotRunning):
        manager.register_service(
            ManagedThreadSpec(task_name="svc", owner="ut", lane="model-tool-io"),
            normal_task,
        )

    snapshot = manager.snapshot()
    assert execution_b.execution_id not in snapshot.active_execution_ids

    release_event.set()
