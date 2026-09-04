"""Backend adapter for the SDK's durable lease scheduler — dreaming jobs."""

import asyncio
import logging
from typing import Any, Dict, Hashable

from consts.const import (
    DREAMING_SCHEDULER_ENABLED,
    DREAMING_SCHEDULER_LEASE_SECONDS,
    DREAMING_SCHEDULER_MAX_CONCURRENCY,
    DREAMING_SCHEDULER_POLL_SECONDS,
)
from database import memory_dreaming_db
from nexent.scheduler import ClaimedJob, ExecutionLease, LeaseScheduler, SchedulerConfig


logger = logging.getLogger("memory_dreaming.scheduler")


class DreamingLeaseStore:
    """Adapt synchronous PostgreSQL operations to the async scheduler contract."""

    @staticmethod
    def _materialize_and_claim(
        owner_id: str, limit: int, lease_seconds: float
    ) -> Dict[str, Any] | None:
        memory_dreaming_db.materialize_due_schedules(limit)
        return memory_dreaming_db.claim_queued(owner_id, lease_seconds)

    async def recover(self) -> None:
        await asyncio.to_thread(memory_dreaming_db.recover_stale, True)

    async def claim_due(
        self,
        owner_id: str,
        limit: int,
        lease_seconds: float,
    ) -> list[ClaimedJob[Dict[str, Any]]]:
        row = await asyncio.to_thread(
            self._materialize_and_claim,
            owner_id,
            limit,
            lease_seconds,
        )
        if row is None:
            return []
        return [ClaimedJob(job_id=row["run_id"], payload=row)]

    async def renew(self, job_id: Hashable, owner_id: str, lease_seconds: float) -> bool:
        return await asyncio.to_thread(
            memory_dreaming_db.renew_lease,
            int(job_id),
            owner_id,
            lease_seconds,
        )

    async def release(self, job_id: Hashable, owner_id: str) -> bool:
        return await asyncio.to_thread(
            memory_dreaming_db.release_lease,
            int(job_id),
            owner_id,
        )


async def execute_dreaming(
    job: ClaimedJob[Dict[str, Any]],
    lease: ExecutionLease,
) -> None:
    """Executor callback invoked by the SDK scheduler for each claimed dreaming job."""
    # Lazy import to avoid circular dependencies at module load time.
    from services.memory_dreaming_service import get_memory_dreaming_service

    payload = job.payload
    tenant_id = payload["tenant_id"]
    user_id = payload["user_id"]
    agent_id = payload["agent_id"]
    trigger_source = payload.get("trigger_source", "scheduler")

    try:
        await asyncio.to_thread(
            get_memory_dreaming_service().run,
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            run_id=int(job.job_id),
            trigger_source=trigger_source,
        )
        logger.info(
            "Dreaming job completed: run_id=%s tenant=%s user=%s agent=%s",
            job.job_id,
            tenant_id,
            user_id,
            agent_id,
        )
    except Exception:
        logger.exception(
            "Dreaming job failed: run_id=%s tenant=%s user=%s agent=%s",
            job.job_id,
            tenant_id,
            user_id,
            agent_id,
        )
        raise


class DreamingScheduler:
    """Application lifecycle wrapper around the reusable SDK scheduler."""

    def __init__(self) -> None:
        self._scheduler = LeaseScheduler(
            store=DreamingLeaseStore(),
            executor=execute_dreaming,
            config=SchedulerConfig(
                poll_interval_seconds=DREAMING_SCHEDULER_POLL_SECONDS,
                lease_seconds=DREAMING_SCHEDULER_LEASE_SECONDS,
                max_concurrency=DREAMING_SCHEDULER_MAX_CONCURRENCY,
            ),
        )

    @property
    def instance_id(self) -> str:
        return self._scheduler.owner_id

    @property
    def is_running(self) -> bool:
        return self._scheduler.is_running

    async def start(self) -> None:
        if not DREAMING_SCHEDULER_ENABLED:
            logger.info("Dreaming scheduler disabled")
            return
        await self._scheduler.start()

    async def stop(self) -> None:
        await self._scheduler.stop()


dreaming_scheduler = DreamingScheduler()
