# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Admit an evaluation only from a running Runtime worker."""

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import Future
from threading import Event

from sqlalchemy.exc import SQLAlchemyError

from contracts.constants.environment import NEXENT_MAINTENANCE_EPOCH, NEXENT_RECOVERY_MODE
from contracts.evaluation import EvalRunStatus
from infrastructure.rdb.client import get_db_session
from management.db.evaluation.runs import (
    claim_agent_evaluation_run,
    get_agent_evaluation,
    update_agent_evaluation_status,
)
from management.services.execution_coordination import (
    RUNTIME_OWNER_INSTANCE_ID,
    ExecutionAlreadyActiveError,
    RuntimeCoordinationUnavailableError,
    reserve_runtime_execution,
    transition_runtime_execution,
)
from nexent.core.concurrency import ManagedTaskSpec
from runtime.thread_management import runtime_thread_manager

logger = logging.getLogger(__name__)
_settlement_tasks: set[asyncio.Task] = set()


async def read_evaluation_for_dispatch(evaluation_id: int, tenant_id: str) -> dict:
    try:
        return await runtime_thread_manager.run(
            "control-io", ManagedTaskSpec(task_name="evaluation-dispatch-read", owner=__name__),
            get_agent_evaluation, agent_evaluation_id=evaluation_id, tenant_id=tenant_id,
        )
    except SQLAlchemyError as exc:
        raise RuntimeCoordinationUnavailableError("Evaluation state is unavailable") from exc


def _claim_evaluation(evaluation_id: int, tenant_id: str, user_id: str) -> int | None:
    try:
        with get_db_session() as session:
            execution_id = None
            if NEXENT_RECOVERY_MODE == "maintenance":
                execution_id = reserve_runtime_execution(
                    tenant_id=tenant_id, user_id=user_id, execution_kind="evaluation",
                    execution_key=f"evaluation:{evaluation_id}", agent_scope=None, agent_limit=None,
                    owner_instance_id=RUNTIME_OWNER_INSTANCE_ID, maintenance_epoch=NEXENT_MAINTENANCE_EPOCH,
                    db_session=session,
                )
            if not claim_agent_evaluation_run(evaluation_id, tenant_id, user_id, db_session=session):
                raise ExecutionAlreadyActiveError("Evaluation is no longer pending")
            if execution_id is not None and not transition_runtime_execution(
                execution_id, RUNTIME_OWNER_INSTANCE_ID, "RUNNING", db_session=session,
            ):
                raise RuntimeCoordinationUnavailableError("Evaluation could not acquire its reservation")
        return execution_id
    except SQLAlchemyError as exc:
        raise RuntimeCoordinationUnavailableError("Evaluation admission is unavailable") from exc


def _begin_finalizing(execution_id: int) -> None:
    if not transition_runtime_execution(execution_id, RUNTIME_OWNER_INSTANCE_ID, "FINALIZING"):
        raise RuntimeCoordinationUnavailableError("Evaluation no longer owns its reservation")


def _settle_evaluation(
    execution_id: int | None, evaluation_id: int, tenant_id: str, user_id: str, status: str,
) -> None:
    with get_db_session() as session:
        if execution_id is not None and not transition_runtime_execution(
            execution_id, RUNTIME_OWNER_INSTANCE_ID, status, db_session=session,
        ):
            return
        if status == EvalRunStatus.FAILED:
            update_agent_evaluation_status(
                evaluation_id, tenant_id, EvalRunStatus.FAILED, updated_by=user_id,
                error_message="Evaluation execution did not finish", expected_status=EvalRunStatus.RUNNING,
                db_session=session,
            )


async def _finish_evaluation(execution_id: int | None, evaluation_id: int, tenant_id: str, user_id: str, status: str) -> None:
    try:
        await runtime_thread_manager.run(
            "control-io", ManagedTaskSpec(task_name="evaluation-dispatch-settle", owner=__name__),
            _settle_evaluation, execution_id, evaluation_id, tenant_id, user_id, status,
        )
    except Exception:
        logger.exception("Could not settle evaluation %s; maintenance will recover it", evaluation_id)


async def start_pending_evaluation(
    evaluation_id: int, tenant_id: str, user_id: str, judge_model_id: int | None, executor: Callable[..., str],
) -> None:
    """Wait for admission, not evaluation completion; an accepted run is detached from HTTP."""
    acknowledged: Future[int | None] = Future()

    def work(cancel_event: Event) -> str | None:
        if cancel_event.is_set():
            acknowledged.cancel()
            return
        try:
            execution_id = _claim_evaluation(evaluation_id, tenant_id, user_id)
        except BaseException as exc:
            acknowledged.set_exception(exc)
            raise
        acknowledged.set_result(execution_id)
        options = {} if execution_id is None else {"before_finalize": lambda: _begin_finalizing(execution_id)}
        return executor(tenant_id, user_id, evaluation_id, judge_model_id, **options)

    def finish(worker: asyncio.Future) -> None:
        if not acknowledged.done():
            acknowledged.cancel()
        succeeded = not worker.cancelled() and worker.exception() is None and worker.result() == EvalRunStatus.COMPLETED
        if acknowledged.cancelled() or acknowledged.exception() is not None:
            return
        execution_id = acknowledged.result()
        if execution_id is not None or not succeeded:
            status = EvalRunStatus.COMPLETED if succeeded else EvalRunStatus.FAILED
            task = asyncio.create_task(_finish_evaluation(execution_id, evaluation_id, tenant_id, user_id, status))
            _settlement_tasks.add(task)
            task.add_done_callback(_settlement_tasks.discard)

    execution = runtime_thread_manager.submit(
        "evaluation", ManagedTaskSpec(
            task_name="agent-evaluation-dispatch", owner="runtime", run_id=str(evaluation_id), pass_cancel_event=True,
        ), work,
    )
    asyncio.wrap_future(execution.future).add_done_callback(finish)
    response = asyncio.wrap_future(acknowledged)
    response.add_done_callback(lambda future: None if future.cancelled() else future.exception())
    try:
        await runtime_thread_manager.wait_until_started(execution)
        await asyncio.shield(response)
    except asyncio.CancelledError:
        if not acknowledged.done():
            runtime_thread_manager.cancel(
                execution.execution_id, reason="evaluation dispatch request ended before admission",
                wait_timeout=0, mark_stuck_on_timeout=False,
            )
        raise
