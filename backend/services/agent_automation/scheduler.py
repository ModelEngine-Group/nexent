import asyncio
import logging
import socket
import uuid
from typing import Optional, Set

from consts.const import (
    AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS,
    AGENT_AUTOMATION_ENABLED,
    AGENT_AUTOMATION_LEASE_SECONDS,
    AGENT_AUTOMATION_MAX_CONCURRENT_RUNS,
    AGENT_AUTOMATION_POLL_INTERVAL_SECONDS,
)
from database import agent_automation_db

from .runner import agent_automation_runner

logger = logging.getLogger("agent_automation.scheduler")


class AgentAutomationScheduler:
    def __init__(self):
        self.instance_id = f"{socket.gethostname()}-{uuid.uuid4()}"
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._semaphore = asyncio.Semaphore(AGENT_AUTOMATION_MAX_CONCURRENT_RUNS)
        self._running_tasks: Set[asyncio.Task] = set()

    async def start(self):
        if not AGENT_AUTOMATION_ENABLED:
            logger.info("Agent automation scheduler disabled")
            return
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        agent_automation_db.recover_stale_runs(AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS)
        agent_automation_db.release_expired_locks()
        self._task = asyncio.create_task(self._loop(), name="agent-automation-scheduler")
        logger.info("Agent automation scheduler started: %s", self.instance_id)

    async def stop(self):
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._running_tasks:
            await asyncio.gather(*self._running_tasks, return_exceptions=True)
        logger.info("Agent automation scheduler stopped")

    async def _loop(self):
        while not self._stop_event.is_set():
            try:
                capacity = self._available_capacity()
                if capacity > 0:
                    due_tasks = agent_automation_db.claim_due_tasks(
                        instance_id=self.instance_id,
                        batch_size=capacity,
                        lease_seconds=AGENT_AUTOMATION_LEASE_SECONDS,
                    )
                    for task in due_tasks:
                        running_task = asyncio.create_task(self._execute_claimed_task(task))
                        self._running_tasks.add(running_task)
                        running_task.add_done_callback(self._running_tasks.discard)
            except Exception as exc:
                logger.error("Agent automation scheduler tick failed: %s", exc, exc_info=True)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=AGENT_AUTOMATION_POLL_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                pass

    def _available_capacity(self) -> int:
        return max(0, getattr(self._semaphore, "_value", 0))

    async def _execute_claimed_task(self, task: dict):
        async with self._semaphore:
            lease_stop = asyncio.Event()
            lease_task = asyncio.create_task(
                self._renew_task_lease(task["task_id"], lease_stop),
                name=f"agent-automation-lease-{task['task_id']}",
            )
            try:
                await agent_automation_runner.execute_task(task, trigger_type="SCHEDULED")
            except Exception as exc:
                logger.error(
                    "Automation task execution failed: task_id=%s error=%s",
                    task.get("task_id"),
                    exc,
                    exc_info=True,
                )
                agent_automation_db.release_task_lock(task["task_id"], self.instance_id)
            finally:
                lease_stop.set()
                lease_task.cancel()
                try:
                    await lease_task
                except asyncio.CancelledError:
                    pass

    async def _renew_task_lease(self, task_id: int, stop_event: asyncio.Event):
        renew_interval = max(0.1, AGENT_AUTOMATION_LEASE_SECONDS / 3)
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=renew_interval)
                return
            except asyncio.TimeoutError:
                renewed = agent_automation_db.renew_task_lock(
                    task_id,
                    self.instance_id,
                    AGENT_AUTOMATION_LEASE_SECONDS,
                )
                if not renewed:
                    logger.warning("Automation task lease was lost: task_id=%s", task_id)
                    return


agent_automation_scheduler = AgentAutomationScheduler()
