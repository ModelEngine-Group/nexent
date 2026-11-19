# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Durably claim evaluation work before submitting a Management worker."""

import logging
from http import HTTPStatus

from fastapi import HTTPException
from nexent.core.concurrency import ManagedTaskSpec

from contracts.errors.exceptions import AppException
from contracts.evaluation import EvalRunStatus
from management.db.evaluation.runs import (
    claim_agent_evaluation_run,
    get_agent_evaluation,
    release_agent_evaluation_claim,
)
from management.thread_management import config_thread_manager

logger = logging.getLogger(__name__)


def dispatch_agent_evaluation_run(agent_evaluation_id: int, user_id: str, tenant_id: str) -> dict:
    try:
        run = get_agent_evaluation(
            agent_evaluation_id=agent_evaluation_id,
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
            "agent_evaluation_id": agent_evaluation_id,
        }

    if status == EvalRunStatus.PENDING:
        claimed = claim_agent_evaluation_run(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            updated_by=user_id,
        )
        if not claimed:
            # Another worker won the conditional update.  It owns the
            # run, so this request is an idempotent success rather than a 409.
            latest = get_agent_evaluation(
                agent_evaluation_id=agent_evaluation_id,
                tenant_id=tenant_id,
            )
            if latest and latest.get("status") == EvalRunStatus.RUNNING:
                return {
                    "accepted": True,
                    "already_running": True,
                    "agent_evaluation_id": agent_evaluation_id,
                }
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail="Agent evaluation run is no longer pending",
            )
    elif status == EvalRunStatus.RUNNING:
        return {
            "accepted": True,
            "already_running": True,
            "agent_evaluation_id": agent_evaluation_id,
        }
    else:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=f"Unsupported evaluation status: {status}",
        )

    try:
        from management.services.evaluation.execution import execute_agent_evaluation_run
        config_thread_manager.submit(
            "evaluation",
            ManagedTaskSpec(
                task_name="agent-evaluation-dispatch",
                owner="management",
                run_id=str(agent_evaluation_id),
            ),
            execute_agent_evaluation_run,
            tenant_id,
            user_id,
            agent_evaluation_id,
            run.get("judge_model_id"),
        )
    except Exception as exc:
        logger.exception(
            "Failed to submit evaluation run to Management pool: run_id=%s",
            agent_evaluation_id,
        )
        try:
            release_agent_evaluation_claim(agent_evaluation_id, tenant_id, user_id)
        except Exception:
            logger.exception("Failed to release evaluation claim: run_id=%s", agent_evaluation_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to submit agent evaluation run",
        ) from exc

    logger.info(
        "Dispatched evaluation run in Management: run_id=%s tenant=%s user=%s",
        agent_evaluation_id,
        tenant_id,
        user_id,
    )
    return {
        "accepted": True,
        "agent_evaluation_id": agent_evaluation_id,
    }
