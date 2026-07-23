"""Manual Dreaming run and audit endpoints."""

from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from services.memory_dreaming_service import (
    DreamingRunError,
    get_memory_dreaming_service,
)
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/memory/dreaming", tags=["memory-dreaming"])


class DreamingRunRequest(BaseModel):
    agent_id: str = Field(..., min_length=1)


@router.post("/run")
async def run_dreaming(
    payload: DreamingRunRequest,
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id = get_current_user_id(authorization)
    try:
        return get_memory_dreaming_service().run(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=payload.agent_id,
        )
    except DreamingRunError as exc:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.get("/audit")
async def list_dreaming_audits(
    authorization: Optional[str] = Header(None),
    agent_id: Optional[str] = Query(default=None),
    run_id: Optional[int] = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
):
    user_id, tenant_id = get_current_user_id(authorization)
    return get_memory_dreaming_service().list_audits(
        tenant_id,
        user_id,
        agent_id=agent_id,
        run_id=run_id,
        limit=limit,
    )
