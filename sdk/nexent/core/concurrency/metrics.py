from __future__ import annotations

import threading
from dataclasses import dataclass

from .models import ExecutionState, ManagedExecution


@dataclass(frozen=True)
class ThreadMetricRecord:
    lane: str
    task_name: str
    queued_count: int
    started_count: int
    completed_count: int
    failed_count: int
    cancelled_count: int
    timed_out_count: int
    rejected_count: int
    stuck_count: int
    total_queue_wait_ms: float
    total_run_ms: float


class ThreadMetrics:
    """Small dependency-free metric store keyed only by stable labels."""

    def __init__(self):
        self._lock = threading.Lock()
        self._values: dict[tuple[str, str], dict[str, float | int]] = {}

    def _row(self, lane: str, task_name: str) -> dict[str, float | int]:
        return self._values.setdefault(
            (lane, task_name),
            {
                "queued_count": 0,
                "started_count": 0,
                "completed_count": 0,
                "failed_count": 0,
                "cancelled_count": 0,
                "timed_out_count": 0,
                "rejected_count": 0,
                "stuck_count": 0,
                "total_queue_wait_ms": 0.0,
                "total_run_ms": 0.0,
            },
        )

    def queued(self, lane: str, task_name: str) -> None:
        with self._lock:
            self._row(lane, task_name)["queued_count"] += 1

    def rejected(self, lane: str, task_name: str) -> None:
        with self._lock:
            self._row(lane, task_name)["rejected_count"] += 1

    def started(self, execution: ManagedExecution) -> None:
        with self._lock:
            row = self._row(execution.lane, execution.spec.task_name)
            row["started_count"] += 1
            if execution.started_at_monotonic is not None:
                row["total_queue_wait_ms"] += max(
                    0.0,
                    (execution.started_at_monotonic - execution.created_at_monotonic) * 1000,
                )

    def stuck(self, execution: ManagedExecution) -> None:
        with self._lock:
            self._row(execution.lane, execution.spec.task_name)["stuck_count"] += 1

    def finished(self, execution: ManagedExecution) -> None:
        with self._lock:
            row = self._row(execution.lane, execution.spec.task_name)
            row["completed_count"] += 1
            if execution.state is ExecutionState.FAILED:
                row["failed_count"] += 1
            elif execution.state in {
                ExecutionState.CANCELLED,
                ExecutionState.TIMED_OUT,
            }:
                row["cancelled_count"] += 1
                if execution.state is ExecutionState.TIMED_OUT:
                    row["timed_out_count"] += 1
            if execution.started_at_monotonic is not None and execution.finished_at_monotonic is not None:
                row["total_run_ms"] += max(
                    0.0,
                    (execution.finished_at_monotonic - execution.started_at_monotonic) * 1000,
                )

    def snapshot(self) -> tuple[ThreadMetricRecord, ...]:
        with self._lock:
            return tuple(
                ThreadMetricRecord(lane=lane, task_name=task_name, **values)
                for (lane, task_name), values in sorted(self._values.items())
            )
