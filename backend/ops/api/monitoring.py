# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Operations model monitoring HTTP routes."""

import logging
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from hmac import digest
from struct import error as StructError
from struct import pack, unpack
from typing import Annotated, Literal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from contracts.constants.environment import JWT_SECRET
from management.services.permission.identity.session import authenticate
from ops.monitoring.model import summarize
from ops.monitoring.query import days_inclusive, metric_value, model_rows, read_models
from permissions.models import CurrentUser
from permissions.operations import operations_scope


logger = logging.getLogger(__name__)
ops_router = APIRouter(prefix="/ops/v1/monitoring", tags=["model monitoring"])
Metric = Literal["request_count", "total_tokens", "error_rate", "avg_duration_ms", "avg_ttft_ms",
                 "avg_generation_rate"]


class Selection(BaseModel):
    tenant_id: str | None
    start_date: date
    end_date: date
    group_ids: list[int]
    model_id: int | None
    model_type: str | None


def selection(start_date: date, end_date: date, tenant_id: str | None = None,
              group_ids: Annotated[list[int] | None, Query(max_length=100)] = None,
              model_id: Annotated[int | None, Query(gt=0)] = None, model_type: str | None = None):
    if not 0 <= (end_date - start_date).days < 366 or any(group <= 0 for group in group_ids or ()):
        raise HTTPException(422, "Invalid monitoring date range or group ID")
    return Selection(tenant_id=tenant_id, start_date=start_date, end_date=end_date, group_ids=group_ids or [],
                     model_id=model_id, model_type=model_type)


def ops_tenant(scope: Annotated[Selection, Depends(selection)], user: Annotated[CurrentUser, Depends(authenticate)]):
    return operations_scope(user, scope.tenant_id)


def _read(request, scope, tenant):
    service = getattr(request.app.state, "monitoring", None)
    if service is None:
        raise HTTPException(503, "Model monitoring is unavailable")
    try:
        return read_models(service, tenant=tenant, start=scope.start_date, end=scope.end_date,
                           groups=scope.group_ids, model_id=scope.model_id, model_type=scope.model_type)
    except Exception as error:
        logger.warning("Model monitoring query failed error=%s", type(error).__name__)
        raise HTTPException(503, "Model monitoring is temporarily unavailable") from None


def _items(rows, catalog, status, metric, search="", descending=True):
    items = model_rows(rows, catalog, covered=status["coverage_state"] == "covered")
    items = [item for item in items if search.casefold() in
             (item.get("display_name") or item.get("model_name") or "").casefold()]
    items.sort(key=lambda item: (item["tenant_id"], item["model_id"]))
    present = [item for item in items if metric_value(item, metric) is not None]
    missing = [item for item in items if metric_value(item, metric) is None]
    return sorted(present, key=lambda item: metric_value(item, metric), reverse=descending) + missing


@ops_router.get("/models")
def models(request: Request, scope: Annotated[Selection, Depends(selection)],
           tenant: Annotated[str | None, Depends(ops_tenant)],
           page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20,
           search: Annotated[str, Query(max_length=100)] = "", sort_by: Metric = "request_count",
           descending: bool = True):
    rows, catalog, _, status = _read(request, scope, tenant)
    items = _items(rows, catalog, status, sort_by, search, descending)
    start = (page - 1) * page_size
    return {"data": {"items": items[start:start + page_size], "total": len(items)}, **status}


@ops_router.get("/models/summary")
def summary(request: Request, scope: Annotated[Selection, Depends(selection)],
            tenant: Annotated[str | None, Depends(ops_tenant)]):
    rows, catalog, available, status = _read(request, scope, tenant)
    values = summarize(rows) if available else dict.fromkeys(summarize(()))
    return {"data": {"current_model_count": len(catalog), **values}, **status}


@ops_router.get("/models/rankings")
def rankings(request: Request, scope: Annotated[Selection, Depends(selection)],
             tenant: Annotated[str | None, Depends(ops_tenant)],
             metric: Literal["request_count", "total_tokens"] = "request_count"):
    rows, catalog, _, status = _read(request, scope, tenant)
    items = _items(rows, catalog, status, metric)
    return {"data": [item for item in items if metric_value(item, metric) is not None][:5], **status}


@ops_router.get("/models/trends")
def trends(request: Request, scope: Annotated[Selection, Depends(selection)],
           tenant: Annotated[str | None, Depends(ops_tenant)]):
    rows, _, available, status = _read(request, scope, tenant)
    by_date = {}
    for row in rows:
        by_date.setdefault(row["statistic_date"], []).append(row)
    published = set(available)
    missing_metrics = dict.fromkeys(summarize(()))
    history = []
    for day in days_inclusive(scope.start_date, scope.end_date):
        metrics = summarize(by_date.get(day.isoformat(), ())) if day in published else missing_metrics
        history.append({"statistic_date": day, **metrics})
    return {"data": history, **status}


class RefreshSelection(BaseModel):
    tenant_id: str | None = None
    start_date: date
    end_date: date


def _refresh_key():
    return digest(JWT_SECRET.encode(), b"ops-model-monitoring-refresh", sha256)


@ops_router.post("/models/refresh", status_code=202)
def refresh_models(request: Request, scope: RefreshSelection,
                   user: Annotated[CurrentUser, Depends(authenticate)]):
    tenant = operations_scope(user, scope.tenant_id, "ops.dashboard:update")
    if tenant is None or not 0 <= (scope.end_date - scope.start_date).days < 366:
        raise HTTPException(422, "Refresh requires a single tenant and a valid date range")
    service = getattr(request.app.state, "monitoring", None)
    if service is None or not JWT_SECRET:
        raise HTTPException(503, "Model monitoring refresh is unavailable")
    try:
        rows = service.store.states(tenant, "model", scope.start_date, scope.end_date)
    except Exception:
        raise HTTPException(503, "Model monitoring refresh is temporarily unavailable") from None
    revisions = {row["statistic_date"].isoformat(): row["source_revision"] for row in rows}
    dates = [day.isoformat() for day in days_inclusive(scope.start_date, scope.end_date)]
    missing_dates = [day for day in dates if day not in revisions]
    if missing_dates:
        raise HTTPException(409, {"code": "MONITORING_DATES_UNCOVERED", "missing_dates": missing_dates})
    now = datetime.now(timezone.utc)
    # Keep the path-sized token bounded even with a full year of PostgreSQL BIGINT revisions.
    revision_bytes = pack(f"!{len(dates)}Q", *(revisions[day] for day in dates))
    token = jwt.encode({
        "aud": "ops-model-monitoring-refresh", "tenant": tenant,
        "start": scope.start_date.isoformat(), "end": scope.end_date.isoformat(),
        "revisions": {},  # An older worker can report the target as uncovered during a rollout.
        "revision_bytes": urlsafe_b64encode(revision_bytes).decode("ascii"),
        "requested": now.timestamp(), "exp": now + timedelta(minutes=10),
    }, _refresh_key(), algorithm="HS256")
    return {"data": {"refresh_id": token, "status": "queued"}}


@ops_router.get("/models/refreshes/{refresh_id}")
def model_refresh_status(request: Request, refresh_id: str,
                         user: Annotated[CurrentUser, Depends(authenticate)]):
    service = getattr(request.app.state, "monitoring", None)
    if service is None or not JWT_SECRET:
        raise HTTPException(503, "Model monitoring refresh is unavailable")
    try:
        target = jwt.decode(refresh_id, _refresh_key(), algorithms=["HS256"], audience="ops-model-monitoring-refresh")
        tenant_id = target["tenant"]
        start, end = date.fromisoformat(target["start"]), date.fromisoformat(target["end"])
        if not 0 <= (end - start).days < 366:
            raise ValueError("Invalid signed refresh date range")
        dates = [day.isoformat() for day in days_inclusive(start, end)]
        encoded = target.get("revision_bytes")
        if encoded is None:
            revisions = target["revisions"]
            if not isinstance(revisions, dict):
                raise ValueError("Invalid signed refresh revisions")
        else:
            versions = unpack(f"!{len(dates)}Q", urlsafe_b64decode(encoded))
            revisions = dict(zip(dates, versions, strict=True))
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError, StructError):
        raise HTTPException(404, "Monitoring refresh was not found") from None
    tenant = operations_scope(user, tenant_id, "ops.dashboard:update")
    try:
        rows = service.store.states(tenant, "model", start, end)
    except Exception:
        raise HTTPException(503, "Model monitoring refresh is temporarily unavailable") from None
    available = {row["statistic_date"].isoformat(): row["published_source_revision"] for row in rows}
    if set(dates) - (available.keys() & revisions.keys()):
        status = "uncovered"
    elif all(available[day] is not None and available[day] >= revisions[day] for day in dates):
        status = "completed"
    else:
        elapsed = datetime.now(timezone.utc).timestamp() - target["requested"]
        status = "timed_out" if elapsed >= 5 else "running"
    snapshot_at = min((row["source_snapshot_at"] for row in rows if row["source_snapshot_at"]), default=None)
    return {"data": {"status": status, "data_as_of": snapshot_at}}
