import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from services.agent_evaluation_service import (
    create_agent_evaluation_run_impl,
    delete_agent_evaluation_run_impl,
    generate_agent_evaluation_report_impl,
    get_agent_evaluation_run_impl,
    list_agent_evaluation_cases_impl,
    list_agent_evaluations_by_agent_impl,
)
from utils.auth_utils import get_current_user_id

logger = logging.getLogger("agent_evaluation_app")

router = APIRouter(prefix="/agent-evaluations")


@router.post("")
async def create_agent_evaluation_api(
    agent_id: int = Body(...),
    evaluation_set_id: int = Body(...),
    judge_model_id: int = Body(..., description="Model id used for judging (Jiuwen)"),
    authorization: Optional[str] = Header(None),
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        run = create_agent_evaluation_run_impl(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            evaluation_set_id=evaluation_set_id,
            judge_model_id=judge_model_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Success", "data": run})
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        logger.exception("Create agent evaluation error: %r", exc)
        raise HTTPException(status_code=500, detail="Create agent evaluation error")


@router.get("")
async def list_agent_evaluations_by_agent_api(
    agent_id: int = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = list_agent_evaluations_by_agent_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Success", "data": data})
    except Exception as exc:
        logger.exception("List agent evaluations error: %r", exc)
        raise HTTPException(status_code=500, detail="List agent evaluations error")


@router.get("/{agent_evaluation_id}")
async def get_agent_evaluation_api(
    agent_evaluation_id: int,
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = get_agent_evaluation_run_impl(agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id)
        return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Success", "data": data})
    except Exception as exc:
        logger.exception("Get agent evaluation error: %r", exc)
        raise HTTPException(status_code=500, detail="Get agent evaluation error")


@router.get("/{agent_evaluation_id}/cases")
async def list_agent_evaluation_cases_api(
    agent_evaluation_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = list_agent_evaluation_cases_impl(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Success", "data": data})
    except Exception as exc:
        logger.exception("List agent evaluation cases error: %r", exc)
        raise HTTPException(status_code=500, detail="List agent evaluation cases error")


@router.get("/{agent_evaluation_id}/report")
async def download_agent_evaluation_report_api(
    agent_evaluation_id: int,
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data, fail_count = generate_agent_evaluation_report_impl(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
        )
        suffix = "_failed.xlsx" if fail_count > 0 else "_all.xlsx"
        return StreamingResponse(
            iter([data]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=evaluation_report_{agent_evaluation_id}{suffix}"
            },
        )
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as exc:
        logger.exception("Download agent evaluation report error: %r", exc)
        raise HTTPException(status_code=500, detail="Download agent evaluation report error")


@router.delete("/{agent_evaluation_id}")
async def delete_agent_evaluation_api(
    agent_evaluation_id: int,
    authorization: Optional[str] = Header(None),
):
    """Soft-delete an evaluation run. Only the creator may delete."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        delete_agent_evaluation_run_impl(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Success"})
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        logger.exception("Delete agent evaluation error: %r", exc)
        raise HTTPException(status_code=500, detail="Delete agent evaluation error")
