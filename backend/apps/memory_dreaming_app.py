"""Manual Dreaming run and audit endpoints."""

from http import HTTPStatus
from typing import Annotated, Optional

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
def run_dreaming(
    payload: DreamingRunRequest,
    authorization: Annotated[Optional[str], Header()] = None,
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
def list_dreaming_audits(
    authorization: Annotated[Optional[str], Header()] = None,
    agent_id: Annotated[Optional[str], Query()] = None,
    run_id: Annotated[Optional[int], Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    user_id, tenant_id = get_current_user_id(authorization)
    return get_memory_dreaming_service().list_audits(
        tenant_id,
        user_id,
        agent_id=agent_id,
        run_id=run_id,
        limit=limit,
    )
