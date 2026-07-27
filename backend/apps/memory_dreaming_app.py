"""Manual Dreaming run and audit endpoints."""

from http import HTTPStatus
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from pydantic import model_validator
from nexent.scheduler import (
    ScheduleMode,
    ScheduleRuleType,
    ScheduleSpec,
    compute_next_fire_at,
    is_valid_cron_expression,
)

from consts.const import (
    DREAMING_COMPRESSION_MAX_ATTEMPTS,
    DREAMING_LONG_TERM_MAX_CHARS,
    DREAMING_SOURCE_LIMIT,
)
from database import memory_dreaming_db
from database.role_permission_db import check_role_permission
from database.user_tenant_db import get_user_tenant_by_user_id
from services.memory_dreaming_service import (
    DreamingConflictError,
    DreamingRunError,
    get_memory_dreaming_service,
)
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/memory/dreaming", tags=["memory-dreaming"])


class DreamingRunRequest(BaseModel):
    agent_id: str = Field(..., min_length=1)
    target_user_id: Optional[str] = None


class DreamingVersionSwitchRequest(BaseModel):
    agent_id: str = Field(..., min_length=1)
    expected_active_version_id: int = Field(..., ge=1)
    target_user_id: Optional[str] = None


class DreamingScheduleRequest(BaseModel):
    agent_id: str = Field(..., min_length=1)
    enabled: bool
    rule_type: Literal["CRON", "INTERVAL"] = "CRON"
    timezone: str = "Asia/Shanghai"
    start_at: Optional[datetime] = None
    cron_expr: Optional[str] = None
    interval_seconds: Optional[int] = Field(default=None, ge=3600)
    target_user_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_schedule(self):
        try:
            ZoneInfo(self.timezone)
        except Exception as exc:
            raise ValueError(f"Invalid timezone: {self.timezone}") from exc
        if self.rule_type == "CRON":
            if not is_valid_cron_expression(self.cron_expr or ""):
                raise ValueError("A valid five-field cron_expr is required")
            if self.interval_seconds is not None:
                raise ValueError("CRON schedule cannot include interval_seconds")
        else:
            if self.interval_seconds is None:
                raise ValueError("interval_seconds is required")
            if self.cron_expr is not None:
                raise ValueError("INTERVAL schedule cannot include cron_expr")
        return self


def _resolve_target_user(
    authorization: Optional[str],
    target_user_id: Optional[str],
    *,
    tenant_capability: str,
) -> tuple[str, str]:
    caller_user_id, tenant_id = get_current_user_id(authorization)
    if not target_user_id or target_user_id == caller_user_id:
        return caller_user_id, tenant_id
    caller = get_user_tenant_by_user_id(caller_user_id) or {}
    caller_role = str(caller.get("user_role") or "").upper()
    if not check_role_permission(
        caller_role,
        permission_category="RESOURCE",
        permission_type="DREAMING",
        permission_subtype=tenant_capability,
    ):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Resource not found"
        )
    target = get_user_tenant_by_user_id(target_user_id) or {}
    if target.get("tenant_id") != tenant_id:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Resource not found"
        )
    return target_user_id, tenant_id



@router.get("/parameters")
def get_dreaming_parameters(
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Expose effective read-only build parameters for an authenticated user."""
    get_current_user_id(authorization)
    return {
        "source_limit": DREAMING_SOURCE_LIMIT,
        "long_term_max_chars": DREAMING_LONG_TERM_MAX_CHARS,
        "compression_max_attempts": DREAMING_COMPRESSION_MAX_ATTEMPTS,
    }


@router.get("/schedule")
def get_dreaming_schedule(
    agent_id: Annotated[str, Query(min_length=1)],
    authorization: Annotated[Optional[str], Header()] = None,
    target_user_id: Annotated[Optional[str], Query()] = None,
):
    user_id, tenant_id = _resolve_target_user(
        authorization, target_user_id, tenant_capability="VIEW_TENANT"
    )
    schedule = memory_dreaming_db.get_schedule(tenant_id, user_id, agent_id)
    return schedule or {
        "agent_id": agent_id,
        "enabled": False,
        "rule_type": "CRON",
        "timezone": "Asia/Shanghai",
        "start_at": None,
        "cron_expr": "0 3 * * *",
        "interval_seconds": None,
        "next_fire_at": None,
        "last_fire_at": None,
        "fire_count": 0,
    }


@router.put("/schedule")
def put_dreaming_schedule(
    payload: DreamingScheduleRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    user_id, tenant_id = _resolve_target_user(
        authorization, payload.target_user_id, tenant_capability="EDIT_TENANT"
    )
    actor_user_id, _ = get_current_user_id(authorization)
    now = datetime.now(timezone.utc)
    start_at = payload.start_at or now
    spec = ScheduleSpec(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType(payload.rule_type),
        timezone=payload.timezone,
        start_at=start_at,
        cron_expr=payload.cron_expr,
        interval_seconds=payload.interval_seconds,
    )
    next_fire_at = compute_next_fire_at(spec, now, 0) if payload.enabled else None
    return memory_dreaming_db.upsert_schedule(
        tenant_id,
        user_id,
        payload.agent_id,
        enabled=payload.enabled,
        rule_type=payload.rule_type,
        timezone_name=payload.timezone,
        start_at=(
            start_at.replace(tzinfo=ZoneInfo(payload.timezone))
            if start_at.tzinfo is None
            else start_at.astimezone(ZoneInfo(payload.timezone))
        ).replace(tzinfo=None),
        cron_expr=payload.cron_expr,
        interval_seconds=payload.interval_seconds,
        next_fire_at=(
            next_fire_at.astimezone(timezone.utc).replace(tzinfo=None)
            if next_fire_at
            else None
        ),
        actor_user_id=actor_user_id,
    )


@router.post("/run", status_code=HTTPStatus.ACCEPTED)
def run_dreaming(
    payload: DreamingRunRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    user_id, tenant_id = _resolve_target_user(
        authorization,
        payload.target_user_id,
        tenant_capability="EDIT_TENANT",
    )
    try:
        run_id = memory_dreaming_db.create_audit(
            tenant_id,
            user_id,
            payload.agent_id,
            trigger_source="manual",
            status="queued",
        )
        return {"run_id": run_id, "status": "queued"}
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
    target_user_id: Annotated[Optional[str], Query()] = None,
):
    user_id, tenant_id = _resolve_target_user(
        authorization,
        target_user_id,
        tenant_capability="VIEW_TENANT",
    )
    return get_memory_dreaming_service().list_audits(
        tenant_id,
        user_id,
        agent_id=agent_id,
        run_id=run_id,
        limit=limit,
    )


@router.get("/versions")
def list_dreaming_versions(
    agent_id: Annotated[str, Query(min_length=1)],
    authorization: Annotated[Optional[str], Header()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    target_user_id: Annotated[Optional[str], Query()] = None,
):
    user_id, tenant_id = _resolve_target_user(
        authorization,
        target_user_id,
        tenant_capability="VIEW_TENANT",
    )
    return get_memory_dreaming_service().list_versions(
        tenant_id, user_id, agent_id=agent_id, limit=limit
    )


@router.post("/versions/{version_id}/activate")
def activate_dreaming_version(
    version_id: int,
    payload: DreamingVersionSwitchRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    user_id, tenant_id = _resolve_target_user(
        authorization,
        payload.target_user_id,
        tenant_capability="EDIT_TENANT",
    )
    actor_user_id, _ = get_current_user_id(authorization)
    try:
        version = get_memory_dreaming_service().activate_version(
            tenant_id,
            user_id,
            agent_id=payload.agent_id,
            version_id=version_id,
            actor_user_id=actor_user_id,
            expected_active_version_id=payload.expected_active_version_id,
        )
    except DreamingConflictError as exc:
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(exc)) from exc
    if version is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Version not found"
        )
    return version
