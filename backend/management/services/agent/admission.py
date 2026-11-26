# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Own durable Creator reservations until their workers have exited."""

import asyncio
import logging
from concurrent.futures import Future
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from contracts.constants.environment import NEXENT_RECOVERY_MODE, RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS
from contracts.errors.exceptions import (
    AgentRunAlreadyActiveError, AgentRunConcurrencyExceededError, ForbiddenError,
    RuntimeCapacityExceededError, RuntimeCoordinationUnavailableError,
)
from infrastructure.rdb.agent_execution import (
    ActiveExecutionError, RunIdentity, begin_execution, finish_execution, mark_running, track_execution,
    untrack_execution,
)
from infrastructure.redis.run_state import creator_runtime_state_service as runtime_state_service
from nexent.core.concurrency import ManagedTaskSpec, ThreadCapacityExceeded
from management.thread_management import config_thread_manager

logger = logging.getLogger(__name__)
_coordination_tasks: set[asyncio.Task] = set()


def uses_durable_agent_admission() -> bool:
    return NEXENT_RECOVERY_MODE == "fixed_replicas"


async def _run_coordination(operation, *args, **kwargs):
    return await config_thread_manager.run(
        "control-io",
        ManagedTaskSpec(task_name="agent-execution-coordination", owner=__name__),
        operation,
        *args,
        **kwargs,
    )


def _track(task: asyncio.Task) -> asyncio.Task:
    _coordination_tasks.add(task)
    task.add_done_callback(_coordination_tasks.discard)
    return task


async def shutdown_creator_settlements(timeout: float) -> int:
    if not _coordination_tasks:
        return 0
    _, pending = await asyncio.wait(tuple(_coordination_tasks), timeout=max(0, timeout))
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    return len(pending)


class AgentExecutionReservation:
    def __init__(self, identity: RunIdentity, worker: Future):
        self.identity = identity
        self.worker = worker
        self.outcome = "failed"
        self.stream_claimed = False
        self._closed = False
        self._loop = asyncio.get_running_loop()

    @property
    def run_id(self) -> str:
        return self.identity.run_id

    async def running(self) -> None:
        try:
            if await _run_coordination(mark_running, self.identity, {}):
                return
        except SQLAlchemyError as exc:
            raise RuntimeCoordinationUnavailableError("Creator execution state is unavailable") from exc
        raise RuntimeCoordinationUnavailableError("Creator execution no longer owns the reservation")

    async def _finish(self) -> None:
        try:
            status = self.outcome
            if status == "completed" and (self.worker.cancelled() or self.worker.exception() is not None):
                status = "failed"
            if self.stream_claimed:
                while True:
                    worker = await runtime_state_service.creator_worker_state_async(
                        self.identity.user_id, self.identity.conversation_id, self.run_id, "seal",
                    )
                    if worker == "closed":
                        break
                    if worker != "running":
                        raise RuntimeCoordinationUnavailableError("Creator worker state is unavailable")
                    await asyncio.sleep(0.25)
            await _run_coordination(finish_execution, self.identity, status, repair_journal=False)
        except Exception:
            logger.exception("Could not settle Creator execution %s", self.run_id)
        finally:
            untrack_execution(self.identity)

    def close(self) -> None:
        """Release only after the producer and the actual worker have both exited."""
        if self._closed:
            return
        self._closed = True

        def schedule_finish():
            _track(asyncio.create_task(self._finish()))

        def worker_finished(_future):
            try:
                self._loop.call_soon_threadsafe(schedule_finish)
            except RuntimeError:
                logger.warning("Creator loop closed before settling execution %s", self.run_id)

        if self.worker.done():
            schedule_finish()
        else:
            self.worker.add_done_callback(worker_finished)


def _reserve(identity: RunIdentity, agent_scope: str) -> None:
    try:
        if not runtime_state_service.client.ping():
            raise RuntimeError("Runtime Redis rejected its readiness check")
    except Exception as exc:
        raise RuntimeCoordinationUnavailableError("Runtime stream coordination is unavailable") from exc

    begin_execution(identity, agent_scope=agent_scope, agent_limit=RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS)
    track_execution(identity)


async def reserve_agent_scope(agent_scope, identifier, user_id, tenant_id, worker, *, run_id=None) -> AgentExecutionReservation:
    identity = RunIdentity(tenant_id, user_id, int(identifier), run_id or uuid4().hex)

    async def reserve():
        await _run_coordination(_reserve, identity, agent_scope)
        return AgentExecutionReservation(identity, worker)

    def release_late_reservation(task):
        if not task.cancelled() and task.exception() is None:
            reservation = task.result()
            reservation.outcome = "stopped"
            reservation.close()

    task = _track(asyncio.create_task(reserve()))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        task.add_done_callback(release_late_reservation)
        raise
    except ActiveExecutionError as exc:
        raise AgentRunAlreadyActiveError("An agent run is already active for this conversation") from exc
    except (AgentRunConcurrencyExceededError, ThreadCapacityExceeded) as exc:
        raise RuntimeCapacityExceededError() from exc
    except PermissionError as exc:
        raise ForbiddenError("Conversation is not accessible to the current identity") from exc
    except SQLAlchemyError as exc:
        raise RuntimeCoordinationUnavailableError("Creator execution coordination is unavailable") from exc
