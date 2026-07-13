"""Backend adapter for the SDK's durable lease scheduler."""

import asyncio
import logging
from typing import Any, Dict, Hashable

from consts.const import (
    AGENT_AUTOMATION_ENABLED,
    AGENT_AUTOMATION_LEASE_SECONDS,
    AGENT_AUTOMATION_MAX_CONCURRENT_RUNS,
    AGENT_AUTOMATION_POLL_INTERVAL_SECONDS,
    AGENT_AUTOMATION_SHUTDOWN_GRACE_SECONDS,
)
from database import agent_automation_db
from nexent.scheduler import ClaimedJob, ExecutionLease, LeaseScheduler, SchedulerConfig

from .runner import agent_automation_runner


logger = logging.getLogger("agent_automation.scheduler")


class AgentAutomationLeaseStore:
    """Adapt synchronous PostgreSQL operations to the async scheduler contract."""

    async def recover(self) -> None:
        await asyncio.to_thread(agent_automation_db.recover_orphaned_runs)
        await asyncio.to_thread(agent_automation_db.release_expired_locks)

    async def claim_due(
        self,
        owner_id: str,
        limit: int,
        lease_seconds: float,
    ) -> list[ClaimedJob[Dict[str, Any]]]:
        tasks = await asyncio.to_thread(
            agent_automation_db.claim_due_tasks,
            owner_id,
            limit,
            lease_seconds,
        )
        return [ClaimedJob(job_id=task["task_id"], payload=task) for task in tasks]

    async def renew(self, job_id: Hashable, owner_id: str, lease_seconds: float) -> bool:
        return await asyncio.to_thread(
            agent_automation_db.renew_task_lock,
            int(job_id),
            owner_id,
            lease_seconds,
        )

    async def release(self, job_id: Hashable, owner_id: str) -> bool:
        return await asyncio.to_thread(
            agent_automation_db.release_task_lock,
            int(job_id),
            owner_id,
        )


async def execute_agent_automation(
    job: ClaimedJob[Dict[str, Any]],
    lease: ExecutionLease,
) -> None:
    await agent_automation_runner.execute_task(
        job.payload,
        trigger_type="SCHEDULED",
        lease_owner=lease.owner_id,
    )


class AgentAutomationScheduler:
    """Application lifecycle wrapper around the reusable SDK scheduler."""

    def __init__(self) -> None:
        self._scheduler = LeaseScheduler(
            store=AgentAutomationLeaseStore(),
            executor=execute_agent_automation,
            config=SchedulerConfig(
                poll_interval_seconds=AGENT_AUTOMATION_POLL_INTERVAL_SECONDS,
                lease_seconds=AGENT_AUTOMATION_LEASE_SECONDS,
                max_concurrency=AGENT_AUTOMATION_MAX_CONCURRENT_RUNS,
                shutdown_grace_seconds=AGENT_AUTOMATION_SHUTDOWN_GRACE_SECONDS,
            ),
        )

    @property
    def instance_id(self) -> str:
        return self._scheduler.owner_id

    @property
    def is_running(self) -> bool:
        return self._scheduler.is_running

    async def start(self) -> None:
        if not AGENT_AUTOMATION_ENABLED:
            logger.info("Agent automation scheduler disabled")
            return
        await self._scheduler.start()

    async def stop(self) -> None:
        await self._scheduler.stop()


agent_automation_scheduler = AgentAutomationScheduler()
