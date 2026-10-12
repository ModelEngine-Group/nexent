"""UT-SDK-AUTO-B1AEA91199BFAD48

BoundedExecutor 运行+排队达到容量上限时非阻塞拒绝提交并抛出 ThreadCapacityExceeded，
且 permit 在任务完成或取消后被正确释放。
"""

import threading

import pytest

from nexent.core.concurrency.bounded_executor import BoundedExecutor
from nexent.core.concurrency.errors import ThreadCapacityExceeded
from nexent.core.concurrency.models import LanePolicy


@pytest.mark.case_id("UT-SDK-AUTO-B1AEA91199BFAD48")
@pytest.mark.stage("D1")
def test_bounded_executor_capacity_rejection_and_permit_release():
    policy = LanePolicy(name="model-tool-io", max_workers=2, max_queue_size=3)
    executor = BoundedExecutor(service_name="test", policy=policy)

    def submit_blocking_tasks(n, release_event):
        state = {"entered": 0, "cond": threading.Condition()}

        def blocking_task():
            with state["cond"]:
                state["entered"] += 1
                state["cond"].notify_all()
            release_event.wait(timeout=30)
            return "ok"

        futures = [executor.submit(blocking_task) for _ in range(n)]
        with state["cond"]:
            state["cond"].wait_for(lambda: state["entered"] >= n, timeout=10)
        return futures

    release = threading.Event()

    try:
        assert executor.capacity == policy.max_workers + policy.max_queue_size
        assert executor.policy.name == "model-tool-io"
        assert executor.submitted == 0

        running_futures = submit_blocking_tasks(policy.max_workers, release)
        assert executor.submitted == policy.max_workers
        assert executor.queued == 0

        def queued_task():
            release.wait(timeout=30)
            return "ok"

        queued_futures = [
            executor.submit(queued_task) for _ in range(policy.max_queue_size)
        ]
        assert executor.submitted == policy.max_workers + policy.max_queue_size
        assert executor.queued == policy.max_queue_size

        with pytest.raises(ThreadCapacityExceeded) as exc_info:
            executor.submit(lambda: "overflow")
        assert exc_info.value.lane == policy.name
        assert exc_info.value.capacity == policy.max_workers + policy.max_queue_size
        assert exc_info.value.queued == policy.max_queue_size
        assert executor.submitted == policy.max_workers + policy.max_queue_size
        assert executor.queued == policy.max_queue_size

        release.set()
        for fut in running_futures + queued_futures:
            assert fut.result(timeout=30) == "ok"
        assert executor.submitted == 0

        follow_up = executor.submit(lambda: "again")
        assert follow_up.result(timeout=10) == "again"
        assert executor.submitted == 0

        release2 = threading.Event()
        blocking_futures = submit_blocking_tasks(policy.max_workers, release2)
        assert executor.submitted == policy.max_workers

        cancellable = executor.submit(lambda: "should-not-run")
        assert executor.submitted == policy.max_workers + 1
        assert cancellable.cancel() is True
        assert executor.submitted == policy.max_workers

        resubmit = executor.submit(lambda: "ok-after-cancel")
        assert executor.submitted == policy.max_workers + 1

        release2.set()
        for fut in blocking_futures:
            assert fut.result(timeout=30) == "ok"
        assert resubmit.result(timeout=30) == "ok-after-cancel"
        assert executor.submitted == 0
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
