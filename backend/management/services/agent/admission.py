# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Connect a root Agent turn's durable reservation to its local worker."""

import asyncio
import logging
from concurrent.futures import Future

from contracts.constants.environment import NEXENT_MAINTENANCE_EPOCH, NEXENT_RECOVERY_MODE, RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS
from contracts.errors.exceptions import RuntimeCapacityExceededError
from infrastructure.redis.run_state import runtime_state_service
from management.services.execution_coordination import (
    RUNTIME_OWNER_INSTANCE_ID,
    ExecutionAlreadyActiveError,
    ExecutionQuotaExceededError,
    RuntimeCoordinationUnavailableError,
    reserve_runtime_execution,
    transition_runtime_execution,
)
from nexent.core.concurrency import ManagedTaskSpec, ThreadCapacityExceeded
from runtime.executions import AgentRunAlreadyActiveError
from runtime.thread_management import runtime_thread_manager

logger = logging.getLogger(__name__)
_coordination_tasks: set[asyncio.Task] = set()


def uses_durable_agent_admission() -> bool:
    return NEXENT_RECOVERY_MODE == "maintenance"


async def _run_coordination(operation, *args, **kwargs):
    return await runtime_thread_manager.run(
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


class AgentExecutionReservation:
    def __init__(self, execution_id: int, worker: Future):
        self.execution_id = execution_id
        self.worker = worker
        self.outcome = "failed"
        self._closed = False
        self._loop = asyncio.get_running_loop()

    async def _transition(self, status: str) -> None:
        updated = await _run_coordination(
            transition_runtime_execution, self.execution_id, RUNTIME_OWNER_INSTANCE_ID, status,
        )
        if not updated:
            raise RuntimeCoordinationUnavailableError("Runtime execution no longer owns the reservation")

    async def running(self) -> None:
        await self._transition("RUNNING")

    async def finalizing(self) -> None:
        await self._transition("FINALIZING")

    async def _finish(self) -> None:
        try:
            status = self.outcome.upper()
            if status == "COMPLETED" and (self.worker.cancelled() or self.worker.exception() is not None):
                status = "FAILED"
            await self._transition(status)
        except Exception:
            logger.exception("Could not settle Runtime execution %s; maintenance will recover it", self.execution_id)

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
                logger.warning("Runtime loop closed before settling execution %s", self.execution_id)

        self.worker.add_done_callback(worker_finished)


def _reserve(agent_scope: str, identifier: int | str, user_id: str, tenant_id: str) -> int:
    try:
        if not runtime_state_service.client.ping():
            raise RuntimeError("Runtime Redis rejected its readiness check")
    except Exception as exc:
        raise RuntimeCoordinationUnavailableError("Runtime stream coordination is unavailable") from exc

    return reserve_runtime_execution(
        tenant_id=tenant_id,
        user_id=user_id,
        execution_kind="agent",
        execution_key=f"conversation:{identifier}",
        agent_scope=agent_scope,
        agent_limit=RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS,
        owner_instance_id=RUNTIME_OWNER_INSTANCE_ID,
        maintenance_epoch=NEXENT_MAINTENANCE_EPOCH,
    )


async def reserve_agent_execution(request, identifier, user_id, tenant_id, worker) -> AgentExecutionReservation | None:
    if not uses_durable_agent_admission():
        return None
    scope = "workbench_main" if request.entrypoint == "workbench" else f"agent:{request.agent_id}"
    return await reserve_agent_scope(scope, identifier, user_id, tenant_id, worker)


async def reserve_agent_scope(agent_scope, identifier, user_id, tenant_id, worker) -> AgentExecutionReservation:
    async def reserve():
        execution_id = await _run_coordination(_reserve, agent_scope, identifier, user_id, tenant_id)
        return AgentExecutionReservation(execution_id, worker)

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
    except ExecutionAlreadyActiveError as exc:
        raise AgentRunAlreadyActiveError("An agent run is already active for this conversation") from exc
    except (ExecutionQuotaExceededError, ThreadCapacityExceeded) as exc:
        raise RuntimeCapacityExceededError() from exc


async def reset_agent_stream(user_id, conversation_id, generation, *, execution_id=None) -> None:
    if execution_id is None:
        await runtime_state_service.reset_stream_async(user_id, conversation_id, generation=generation)
        return
    task = _track(asyncio.create_task(runtime_state_service.reset_stream_async(
        user_id, conversation_id, generation=generation, required=True, execution_id=execution_id,
    )))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            task.exception()
        raise
    except Exception as exc:
        raise RuntimeCoordinationUnavailableError("Runtime stream coordination is unavailable") from exc
