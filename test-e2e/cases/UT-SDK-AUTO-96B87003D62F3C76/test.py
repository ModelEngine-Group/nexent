from __future__ import annotations

import pytest

from nexent.core.concurrency.metrics import ThreadMetricRecord, ThreadMetrics
from nexent.core.concurrency.models import (
    ExecutionState,
    ManagedExecution,
    ManagedTaskSpec,
)


def _execution(lane, task_name, state=ExecutionState.QUEUED):
    return ManagedExecution(
        lane=lane,
        spec=ManagedTaskSpec(task_name=task_name, owner='test-owner'),
        state=state,
    )


def _rows(metrics):
    return {(r.lane, r.task_name): r for r in metrics.snapshot()}


@pytest.mark.case_id('UT-SDK-AUTO-96B87003D62F3C76')
@pytest.mark.stage('D1')
def test_thread_metrics_stable_labels_counts_and_duration_aggregation():
    metrics = ThreadMetrics()

    assert metrics.snapshot() == ()

    metrics.queued('lane_b', 'task_x')
    metrics.rejected('lane_b', 'task_x')

    positive = _execution('lane_a', 'task_x')
    positive.created_at_monotonic = 100.0
    positive.started_at_monotonic = 101.5
    metrics.started(positive)

    negative = _execution('lane_a', 'task_x')
    negative.created_at_monotonic = 100.0
    negative.started_at_monotonic = 99.0
    metrics.started(negative)

    metrics.stuck(positive)

    failed = _execution('lane_f', 'task_f', ExecutionState.FAILED)
    failed.created_at_monotonic = 0.0
    failed.started_at_monotonic = 2.0
    failed.finished_at_monotonic = 5.0
    metrics.finished(failed)

    cancelled = _execution('lane_c', 'task_c', ExecutionState.CANCELLED)
    cancelled.created_at_monotonic = 0.0
    cancelled.started_at_monotonic = 2.0
    cancelled.finished_at_monotonic = 4.0
    metrics.finished(cancelled)

    timed_out = _execution('lane_t', 'task_t', ExecutionState.TIMED_OUT)
    timed_out.created_at_monotonic = 0.0
    timed_out.started_at_monotonic = 1.0
    timed_out.finished_at_monotonic = 3.5
    metrics.finished(timed_out)

    metrics.queued('lane_b', 'task_x')

    rows = _rows(metrics)

    q = rows[('lane_b', 'task_x')]
    assert q.queued_count == 2
    assert q.rejected_count == 1
    assert q.started_count == 0
    assert q.completed_count == 0
    assert q.failed_count == 0
    assert q.cancelled_count == 0
    assert q.timed_out_count == 0
    assert q.stuck_count == 0
    assert q.total_queue_wait_ms == 0.0
    assert q.total_run_ms == 0.0

    a = rows[('lane_a', 'task_x')]
    assert a.started_count == 2
    assert a.stuck_count == 1
    assert a.total_queue_wait_ms == 1500.0
    assert a.queued_count == 0
    assert a.rejected_count == 0
    assert a.completed_count == 0
    assert a.failed_count == 0
    assert a.cancelled_count == 0
    assert a.timed_out_count == 0
    assert a.total_run_ms == 0.0

    f = rows[('lane_f', 'task_f')]
    assert f.completed_count == 1
    assert f.failed_count == 1
    assert f.cancelled_count == 0
    assert f.timed_out_count == 0
    assert f.total_run_ms == 3000.0

    c = rows[('lane_c', 'task_c')]
    assert c.completed_count == 1
    assert c.failed_count == 0
    assert c.cancelled_count == 1
    assert c.timed_out_count == 0
    assert c.total_run_ms == 2000.0

    t = rows[('lane_t', 'task_t')]
    assert t.completed_count == 1
    assert t.failed_count == 0
    assert t.cancelled_count == 1
    assert t.timed_out_count == 1
    assert t.total_run_ms == 2500.0

    ordered = metrics.snapshot()
    assert [r.lane for r in ordered] == ['lane_a', 'lane_b', 'lane_c', 'lane_f', 'lane_t']
    assert [r.task_name for r in ordered] == ['task_x', 'task_x', 'task_c', 'task_f', 'task_t']
    assert all(isinstance(r, ThreadMetricRecord) for r in ordered)

    for record in ordered:
        assert record.total_queue_wait_ms >= 0.0
        assert record.total_run_ms >= 0.0

    clamp_metrics = ThreadMetrics()
    clamp_exec = _execution('lane_neg', 'task_neg')
    clamp_exec.created_at_monotonic = 50.0
    clamp_exec.started_at_monotonic = 40.0
    clamp_metrics.started(clamp_exec)
    clamp_row = _rows(clamp_metrics)[('lane_neg', 'task_neg')]
    assert clamp_row.started_count == 1
    assert clamp_row.total_queue_wait_ms == 0.0
