"""Backend adapter for the SDK's durable lease scheduler."""

import asyncio
import logging
from datetime import datetime, timezone
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

from .models import ScheduleTrigger
from .runner import agent_automation_runner
from .schedule_engine import compute_next_fire_at


logger = logging.getLogger("agent_automation.scheduler")
_MISFIRE_POLICY_SKIP = "SKIP"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentAutomationLeaseStore:
    """Adapt synchronous PostgreSQL operations to the async scheduler contract."""

    def __init__(self) -> None:
        self._recovery_time: datetime | None = None

    async def recover(self) -> None:
        recovery_time = _utcnow()
        await asyncio.to_thread(agent_automation_db.recover_orphaned_runs)
        await asyncio.to_thread(agent_automation_db.release_expired_locks)
        self._recovery_time = recovery_time

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
        runnable_tasks = []
        for task in tasks:
            if await self._skip_claimed_misfire(task, owner_id):
                continue
            runnable_tasks.append(task)
        return [ClaimedJob(job_id=task["task_id"], payload=task) for task in runnable_tasks]

    async def _skip_claimed_misfire(self, task: Dict[str, Any], owner_id: str) -> bool:
        """Advance a pre-restart recurring fire without invoking its executor."""
        if self._recovery_time is None or task.get("schedule_mode") != "RECURRING":
            return False

        scheduled_fire_at = task.get("next_fire_at")
        if isinstance(scheduled_fire_at, str):
            scheduled_fire_at = datetime.fromisoformat(scheduled_fire_at.replace("Z", "+00:00"))
        if scheduled_fire_at.tzinfo is None:
            scheduled_fire_at = scheduled_fire_at.replace(tzinfo=timezone.utc)
        if scheduled_fire_at >= self._recovery_time:
            return False

        task_status = "ACTIVE"
        last_error = None
        try:
            trigger = ScheduleTrigger.model_validate(task["schedule_config"])
            next_fire_at = compute_next_fire_at(
                trigger,
                self._recovery_time,
                int(task.get("fire_count") or 0),
            )
            if next_fire_at is None:
                task_status = "COMPLETED"
        except Exception:
            task_status = "PAUSED_BY_SYSTEM"
            last_error = "Invalid schedule configuration during restart recovery."
            next_fire_at = None
            logger.exception(
                "Failed to compute post-restart schedule; pausing task: task_id=%s",
                task["task_id"],
            )

        task_values = {
            "status": task_status,
            "next_fire_at": next_fire_at,
            "misfire_policy": _MISFIRE_POLICY_SKIP,
            "lock_owner": None,
            "lock_until": None,
        }
        if last_error is not None:
            task_values["last_error"] = last_error

        updated = await asyncio.to_thread(
            agent_automation_db.update_task_if_lock_owner,
            task["task_id"],
            task["tenant_id"],
            task["user_id"],
            owner_id,
            task_values,
        )
        if not updated:
            logger.warning(
                "Discarded missed-fire recovery after lease loss: task_id=%s owner=%s",
                task["task_id"],
                owner_id,
            )
        return True

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
