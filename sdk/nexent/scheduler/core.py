"""Reusable high-availability scheduler built on persistent leases."""

import asyncio
import logging
import socket
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Generic, Hashable, Protocol, Sequence, TypeVar


JobPayload = TypeVar("JobPayload")
logger = logging.getLogger("nexent.scheduler")


@dataclass(frozen=True)
class SchedulerConfig:
    """Runtime controls for a :class:`LeaseScheduler`."""

    poll_interval_seconds: float = 5.0
    lease_seconds: float = 120.0
    max_concurrency: int = 2
    shutdown_grace_seconds: float = 30.0
    error_backoff_seconds: float = 1.0
    max_error_backoff_seconds: float = 30.0

    def __post_init__(self) -> None:
        positive_values = {
            "poll_interval_seconds": self.poll_interval_seconds,
            "lease_seconds": self.lease_seconds,
            "max_concurrency": self.max_concurrency,
            "shutdown_grace_seconds": self.shutdown_grace_seconds,
            "error_backoff_seconds": self.error_backoff_seconds,
            "max_error_backoff_seconds": self.max_error_backoff_seconds,
        }
        invalid = [name for name, value in positive_values.items() if value <= 0]
        if invalid:
            raise ValueError(f"Scheduler configuration must be positive: {', '.join(invalid)}")


@dataclass(frozen=True)
class ClaimedJob(Generic[JobPayload]):
    """A job payload protected by a lease owned by this scheduler instance."""

    job_id: Hashable
    payload: JobPayload


@dataclass
class ExecutionLease:
    """Lease identity exposed to an executor for fencing persistent writes."""

    job_id: Hashable
    owner_id: str
    lost: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def is_valid(self) -> bool:
        return not self.lost.is_set()


class LeaseStore(Protocol[JobPayload]):
    """Persistence contract required by the scheduler core."""

    async def recover(self) -> None:
        """Recover orphaned execution state without stealing live leases."""

    async def claim_due(
        self,
        owner_id: str,
        limit: int,
        lease_seconds: float,
    ) -> Sequence[ClaimedJob[JobPayload]]:
        """Atomically claim due jobs and return their persisted payloads."""

    async def renew(self, job_id: Hashable, owner_id: str, lease_seconds: float) -> bool:
        """Renew a lease only when ``owner_id`` still owns it."""

    async def release(self, job_id: Hashable, owner_id: str) -> bool:
        """Release a lease only when ``owner_id`` still owns it."""


class JobExecutor(Protocol[JobPayload]):
    async def __call__(self, job: ClaimedJob[JobPayload], lease: ExecutionLease) -> None:
        """Execute one claimed job."""


class LeaseScheduler(Generic[JobPayload]):
    """Poll, claim, renew, and execute durable jobs across service replicas.

    Availability and correctness come from the store's atomic claim operation.
    The scheduler adds bounded concurrency, lease renewal, stale-worker fencing
    signals, retry backoff, and bounded graceful shutdown.
    """

    def __init__(
        self,
        store: LeaseStore[JobPayload],
        executor: JobExecutor[JobPayload] | Callable[
            [ClaimedJob[JobPayload], ExecutionLease], Awaitable[None]
        ],
        config: SchedulerConfig,
        owner_id: str | None = None,
    ) -> None:
        self.store = store
        self.executor = executor
        self.config = config
        self.owner_id = owner_id or f"{socket.gethostname()}-{uuid.uuid4()}"
        self._loop_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._running: set[asyncio.Task[None]] = set()
        self._recovery_pending = True

    @property
    def is_running(self) -> bool:
        return self._loop_task is not None and not self._loop_task.done()

    @property
    def active_count(self) -> int:
        return len(self._running)

    async def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._recovery_pending = True
        self._loop_task = asyncio.create_task(self._run_loop(), name=f"lease-scheduler-{self.owner_id}")
        logger.info("Lease scheduler started: owner_id=%s", self.owner_id)

    async def stop(self) -> None:
        self._stop_event.set()
        loop_task = self._loop_task
        self._loop_task = None
        if loop_task is not None:
            loop_task.cancel()
            await asyncio.gather(loop_task, return_exceptions=True)

        running = set(self._running)
        if running:
            _, pending = await asyncio.wait(running, timeout=self.config.shutdown_grace_seconds)
            if pending:
                logger.warning("Canceling %s jobs after shutdown grace period", len(pending))
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        logger.info("Lease scheduler stopped: owner_id=%s", self.owner_id)

    async def _run_loop(self) -> None:
        failure_count = 0
        while not self._stop_event.is_set():
            delay = self.config.poll_interval_seconds
            try:
                if self._recovery_pending:
                    await self.store.recover()
                    self._recovery_pending = False
                capacity = max(0, self.config.max_concurrency - len(self._running))
                if capacity:
                    claimed = await self.store.claim_due(
                        self.owner_id,
                        capacity,
                        self.config.lease_seconds,
                    )
                    for job in claimed[:capacity]:
                        task = asyncio.create_task(
                            self._run_claimed(job),
                            name=f"lease-job-{job.job_id}",
                        )
                        self._running.add(task)
                        task.add_done_callback(self._running.discard)
                failure_count = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                failure_count += 1
                delay = min(
                    self.config.max_error_backoff_seconds,
                    self.config.error_backoff_seconds * (2 ** (failure_count - 1)),
                )
                logger.exception("Scheduler poll failed; retrying in %.2f seconds", delay)
            await self._wait_or_stop(delay)

    async def _wait_or_stop(self, delay: float) -> None:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass

    async def _run_claimed(self, job: ClaimedJob[JobPayload]) -> None:
        lease = ExecutionLease(job_id=job.job_id, owner_id=self.owner_id)
        execution = asyncio.create_task(self.executor(job, lease), name=f"lease-executor-{job.job_id}")
        renewal = asyncio.create_task(
            self._renew_lease(job, lease, execution),
            name=f"lease-renewal-{job.job_id}",
        )
        try:
            await execution
        except asyncio.CancelledError:
            if not execution.done():
                execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
            if not lease.lost.is_set():
                raise
        except Exception:
            logger.exception("Scheduled job failed: job_id=%s", job.job_id)
        finally:
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)
            try:
                await self.store.release(job.job_id, self.owner_id)
            except Exception:
                logger.exception("Failed to release job lease: job_id=%s", job.job_id)

    async def _renew_lease(
        self,
        job: ClaimedJob[JobPayload],
        lease: ExecutionLease,
        execution: asyncio.Task[None],
    ) -> None:
        renew_interval = max(0.05, self.config.lease_seconds / 3)
        retry_interval = max(0.05, min(1.0, self.config.lease_seconds / 6))
        lease_deadline = time.monotonic() + self.config.lease_seconds
        while not execution.done():
            await asyncio.sleep(renew_interval)
            if execution.done():
                return
            try:
                renewed = await self.store.renew(
                    job.job_id,
                    self.owner_id,
                    self.config.lease_seconds,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Lease renewal failed: job_id=%s", job.job_id)
                if time.monotonic() + retry_interval < lease_deadline:
                    renew_interval = retry_interval
                    continue
                renewed = False

            if renewed:
                lease_deadline = time.monotonic() + self.config.lease_seconds
                renew_interval = max(0.05, self.config.lease_seconds / 3)
                continue

            lease.lost.set()
            logger.warning("Job lease lost; canceling stale executor: job_id=%s", job.job_id)
            execution.cancel()
            return
