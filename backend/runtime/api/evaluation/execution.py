# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Internal runtime endpoints for agent-evaluation execution."""

import logging
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from nexent.core.concurrency import ThreadCapacityExceeded, ThreadManagerDraining, ThreadManagerNotRunning, ThreadQueueTimedOut

from contracts.evaluation import EvalRunStatus, EvaluationRunRequest, RuntimeEvaluationTrialRunRequest as TrialRunRequest
from contracts.errors.exceptions import AppException
from gateway.downstream.internal_tokens import verify_internal_runtime_jwt
from management.services.evaluation.dispatch import read_evaluation_for_dispatch, start_pending_evaluation
from management.services.execution_coordination import ExecutionAlreadyActiveError, RuntimeCoordinationUnavailableError


logger = logging.getLogger("agent_evaluation_runtime_app")
router = APIRouter(prefix="/agent-evaluations/internal")


def _load_evaluation_executor():
    """Load the evaluation service only when a runtime run is dispatched."""
    from management.services.evaluation.runs import execute_agent_evaluation_run

    return execute_agent_evaluation_run


def _load_trial_executor():
    """Load the trial executor only when Runtime receives a trial request."""
    from management.services.evaluation.runs import trial_run_evaluator_impl

    return trial_run_evaluator_impl


def _existing_dispatch_result(evaluation_id: int, status: str | None) -> dict | None:
    if status in (EvalRunStatus.COMPLETED, EvalRunStatus.FAILED):
        return {"accepted": False, "already_finished": True, "status": status, "agent_evaluation_id": evaluation_id}
    if status == EvalRunStatus.RUNNING:
        return {"accepted": True, "already_running": True, "agent_evaluation_id": evaluation_id}
    return None


@router.post("/trial-run", include_in_schema=False)
async def trial_run_evaluation_api(
    payload: TrialRunRequest,
    authorization: Annotated[str | None, Header()] = None,
):
    """Run one ad-hoc evaluation in the Runtime process."""
    try:
        user_id, tenant_id = verify_internal_runtime_jwt(authorization)
    except Exception as exc:
        logger.warning("Rejected unauthenticated trial evaluation: %s", exc)
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail="Invalid internal runtime authorization",
        ) from exc

    trial_run_evaluator_impl = _load_trial_executor()
    return await trial_run_evaluator_impl(
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=payload.agent_id,
        agent_version_no=payload.agent_version_no,
        query=payload.query,
        judge_model_id=payload.judge_model_id,
        evaluator_ids=payload.evaluator_ids,
        language=payload.language,
    )


@router.post("/run", include_in_schema=False, status_code=HTTPStatus.ACCEPTED)
async def dispatch_evaluation_run_api(
    payload: EvaluationRunRequest,
    authorization: Annotated[str | None, Header()] = None,
):
    """Start evaluation execution in the runtime process.

    The database claim is conditional on ``PENDING`` so a retry cannot start
    the same run twice.  The runtime process owns the worker thread and the
    sandbox volume used by ``prepare_agent_run``.
    """
    try:
        user_id, tenant_id = verify_internal_runtime_jwt(authorization)
    except Exception as exc:
        logger.warning("Rejected unauthenticated evaluation dispatch: %s", exc)
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail="Invalid internal runtime authorization",
        ) from exc

    evaluation_id = payload.agent_evaluation_id
    try:
        run = await read_evaluation_for_dispatch(evaluation_id, tenant_id)
        if not run:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Agent evaluation run not found")
        status = run.get("status")
        existing = _existing_dispatch_result(evaluation_id, status)
        if existing is not None:
            return existing
        if status != EvalRunStatus.PENDING:
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=f"Unsupported evaluation status: {status}")

        try:
            await start_pending_evaluation(evaluation_id, tenant_id, user_id, run.get("judge_model_id"), _load_evaluation_executor())
        except ExecutionAlreadyActiveError as exc:
            latest = await read_evaluation_for_dispatch(evaluation_id, tenant_id)
            existing = _existing_dispatch_result(evaluation_id, latest.get("status") if latest else None)
            if existing is not None:
                return existing
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail="Agent evaluation run is no longer pending",
            ) from exc
    except AppException as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc)) from exc
    except HTTPException:
        raise
    except (RuntimeCoordinationUnavailableError, ThreadManagerDraining, ThreadManagerNotRunning):
        return JSONResponse(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            content={"code": "RUNTIME_COORDINATION_UNAVAILABLE", "message": "Runtime coordination is unavailable.",
                     "retryable": True}, headers={"Retry-After": "1"},
        )
    except (ThreadCapacityExceeded, ThreadQueueTimedOut) as exc:
        code = "RUNTIME_QUEUE_TIMEOUT" if isinstance(exc, ThreadQueueTimedOut) else "RUNTIME_CAPACITY_FULL"
        return JSONResponse(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            content={"code": code, "message": "Runtime evaluation capacity is unavailable.", "retryable": True},
            headers={"Retry-After": "1"},
        )
    except Exception as exc:
        logger.exception(
            "Failed to submit evaluation run to runtime pool: run_id=%s",
            payload.agent_evaluation_id,
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to submit agent evaluation run",
        ) from exc

    logger.info(
        "Dispatched evaluation run to runtime: run_id=%s tenant=%s user=%s",
        payload.agent_evaluation_id,
        tenant_id,
        user_id,
    )
    return {
        "accepted": True,
        "agent_evaluation_id": payload.agent_evaluation_id,
    }
