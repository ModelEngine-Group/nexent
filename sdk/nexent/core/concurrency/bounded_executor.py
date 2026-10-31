import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

from .errors import ThreadCapacityExceeded
from .models import LanePolicy


class BoundedExecutor:
    """ThreadPoolExecutor wrapper with a hard running-plus-queued limit."""

    def __init__(self, service_name: str, policy: LanePolicy):
        self.policy = policy
        self._capacity = policy.max_workers + policy.max_queue_size
        self._permits = threading.BoundedSemaphore(self._capacity)
        self._executor = ThreadPoolExecutor(
            max_workers=policy.max_workers,
            thread_name_prefix=f"nexent-{service_name}-{policy.name}",
        )
        self._lock = threading.Lock()
        self._submitted = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def submitted(self) -> int:
        with self._lock:
            return self._submitted

    @property
    def queued(self) -> int:
        return max(0, self.submitted - self.policy.max_workers)

    def submit(self, fn: Callable, *args, **kwargs) -> Future:
        acquired = self._permits.acquire(blocking=False)
        if not acquired:
            raise ThreadCapacityExceeded(
                lane=self.policy.name,
                capacity=self.capacity,
                queued=self.queued,
            )

        with self._lock:
            self._submitted += 1
        try:
            future = self._executor.submit(fn, *args, **kwargs)
        except BaseException:
            self._release_permit()
            raise
        future.add_done_callback(lambda _future: self._release_permit())
        return future

    def _release_permit(self):
        with self._lock:
            self._submitted -= 1
        self._permits.release()

    def shutdown(self, *, wait: bool, cancel_futures: bool):
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
