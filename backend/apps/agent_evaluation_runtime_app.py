"""Internal runtime endpoints for agent-evaluation execution."""

import logging
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from consts.evaluation_status import EvalRunStatus
from consts.exceptions import AppException
from database.agent_evaluation_db import (
    claim_agent_evaluation_run,
    get_agent_evaluation,
)
from utils.auth_utils import verify_internal_runtime_jwt
from utils.thread_utils import pool


logger = logging.getLogger("agent_evaluation_runtime_app")
router = APIRouter(prefix="/agent-evaluations/internal")


class EvaluationRunRequest(BaseModel):
    """Payload used by config service to dispatch one evaluation run."""

    agent_evaluation_id: int = Field(gt=0)


def _load_evaluation_executor():
    """Load the evaluation service only when a runtime run is dispatched."""
    from services.agent_evaluation_service import execute_agent_evaluation_run

    return execute_agent_evaluation_run


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

    try:
        run = get_agent_evaluation(
            agent_evaluation_id=payload.agent_evaluation_id,
            tenant_id=tenant_id,
        )
    except AppException as exc:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc),
        ) from exc
    if not run:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Agent evaluation run not found",
        )

    status = run.get("status")
    if status in (EvalRunStatus.COMPLETED, EvalRunStatus.FAILED):
        return {
            "accepted": False,
            "already_finished": True,
            "status": status,
            "agent_evaluation_id": payload.agent_evaluation_id,
        }

    if status == EvalRunStatus.PENDING:
        claimed = claim_agent_evaluation_run(
            agent_evaluation_id=payload.agent_evaluation_id,
            tenant_id=tenant_id,
            updated_by=user_id,
        )
        if not claimed:
            # Another runtime request won the conditional update.  It owns the
            # run, so this request is an idempotent success rather than a 409.
            latest = get_agent_evaluation(
                agent_evaluation_id=payload.agent_evaluation_id,
                tenant_id=tenant_id,
            )
            if latest and latest.get("status") == EvalRunStatus.RUNNING:
                return {
                    "accepted": True,
                    "already_running": True,
                    "agent_evaluation_id": payload.agent_evaluation_id,
                }
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail="Agent evaluation run is no longer pending",
            )
    elif status == EvalRunStatus.RUNNING:
        return {
            "accepted": True,
            "already_running": True,
            "agent_evaluation_id": payload.agent_evaluation_id,
        }
    else:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=f"Unsupported evaluation status: {status}",
        )

    try:
        execute_agent_evaluation_run = _load_evaluation_executor()
        pool.submit(
            execute_agent_evaluation_run,
            tenant_id,
            user_id,
            payload.agent_evaluation_id,
            run.get("judge_model_id"),
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
