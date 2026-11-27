# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Operations monitoring HTTP routes."""

import logging
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from hmac import digest
from struct import error as StructError
from struct import pack, unpack
from typing import Annotated, Literal

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from infrastructure.monitoring.contracts import McpServerType
from pydantic import BaseModel, Field

from backend.http.server.northbound import is_northbound_path
from backend.http.server.request_context import get_request_id
from contracts.authentication import AuthenticatedIdentity, CredentialKind
from contracts.constants.environment import JWT_SECRET
from contracts.errors.exceptions import UnauthorizedError
from management.services.permission.identity.session import (
    authenticate,
    authenticate_identity,
)
from ops.monitoring.agent_tokens import read_agent_tokens
from ops.monitoring.mcp_tool import summarize as summarize_mcp_tool
from ops.monitoring.model import summarize
from ops.monitoring.query import (
    days_inclusive,
    mcp_server_catalog,
    mcp_server_rows,
    mcp_services_by_tenant,
    mcp_tool_rows,
    metric_value,
    model_rows,
    read_agent_views,
    read_agents,
    read_mcp_tools,
    read_models,
    read_skills,
    skill_metric_value,
    skill_rows,
)
from permissions.models import CurrentUser
from permissions.operations import operations_scope

logger = logging.getLogger(__name__)
ops_router = APIRouter(prefix="/ops/v1/monitoring", tags=["model monitoring"])
Metric = Literal["request_count", "total_tokens", "error_rate", "avg_duration_ms", "avg_ttft_ms",
                 "avg_generation_rate"]
PositiveResourceId = Annotated[int, Field(gt=0, le=2**31 - 1)]
AgentMetric = Literal["execution_count", "avg_duration_ms", "avg_ttft_ms", "total_tokens", "success_rate"]
ToolMetric = Literal["request_count", "error_rate", "avg_duration_ms"]


class MonitoringSelection(BaseModel):
    tenant_id: str | None
    start_date: date
    end_date: date
    group_ids: list[int]


class Selection(MonitoringSelection):
    model_id: int | None
    model_type: str | None
    skill_id: str | None = None
    skill_name: str | None = None


class AgentSelection(MonitoringSelection):
    agent_id: int | None


def _validate_range(start_date: date, end_date: date, group_ids: list[int] | None) -> None:
    if not 0 <= (end_date - start_date).days < 366 or any(group <= 0 for group in group_ids or ()):
        raise HTTPException(422, "Invalid monitoring date range or group ID")


def selection(start_date: date, end_date: date, tenant_id: str | None = None,
              group_ids: Annotated[list[int] | None, Query(max_length=100)] = None,
              model_id: Annotated[int | None, Query(gt=0)] = None, model_type: str | None = None,
              skill_id: str | None = None, skill_name: str | None = None):
    _validate_range(start_date, end_date, group_ids)
    return Selection(tenant_id=tenant_id, start_date=start_date, end_date=end_date, group_ids=group_ids or [],
                     model_id=model_id, model_type=model_type, skill_id=skill_id, skill_name=skill_name)


class OpsPrincipal:
    """Lane-resolved caller: API-key identity on northbound mounts, session user otherwise."""

    __slots__ = ("identity", "kind", "user")

    def __init__(self, *, kind: str, user: CurrentUser | None = None,
                 identity: AuthenticatedIdentity | None = None):
        self.kind = kind
        self.user = user
        self.identity = identity


def _request_path(request: Request) -> str:
    scope_path = request.scope.get("path") if request is not None else ""
    return scope_path or (request.url.path if request is not None else "")


def _submit_api_key_usage(principal: AuthenticatedIdentity, request: Request) -> None:
    """Queue usage accounting on this process's control-io lane; fail-open.

    The ops process owns its own thread manager, so the accounting lands on
    ``app.state.thread_manager`` instead of the management config manager.
    """
    from nexent.core.concurrency import ManagedTaskSpec

    from management.services.permission.identity.northbound import record_api_key_usage

    manager = getattr(request.app.state, "thread_manager", None)
    if manager is None:
        return
    try:
        manager.submit("control-io", ManagedTaskSpec(task_name="record-api-key-usage", owner="ops"),
                       record_api_key_usage, principal, request)
    except Exception as exc:
        logger.warning("API key usage accounting dropped: %s", exc)


def _resolve_session_user(request: Request, authorization: str | None) -> CurrentUser:
    """Resolve the session user the way FastAPI would, honoring dependency overrides.

    The principal dependency calls ``authenticate`` directly, so the same
    ``dependency_overrides`` lookup FastAPI applies is mirrored here; test
    fixtures that override ``authenticate`` keep working unchanged. Overrides
    declaring their own parameters are not supported at this call site.
    """
    override = request.app.dependency_overrides.get(authenticate)
    if override is not None:
        return override()
    return authenticate(authorization, _credentials=None)


def ops_principal(request: Request, authorization: str | None = Header(None)) -> OpsPrincipal:
    """Single identity dependency for both mounts of the monitoring router.

    ``/nb`` requests are northbound API-key callers: the principal is resolved
    with the API-key policy and usage-accounted here, so business code never
    participates in accounting. Every other path keeps the browser session.
    """
    if is_northbound_path(_request_path(request)):
        principal = authenticate_identity(authorization, kind=CredentialKind.API_KEY, request=request)
        if not principal.user_id or not principal.tenant_id:
            raise UnauthorizedError("Authenticated principal is incomplete")
        request.state.authenticated_identity = principal
        request.state.request_id = get_request_id(request)
        _submit_api_key_usage(principal, request)
        return OpsPrincipal(kind="api_key", identity=principal)
    return OpsPrincipal(kind="session", user=_resolve_session_user(request, authorization))


def ops_scoped_tenant(principal: OpsPrincipal, tenant_id: str | None = None,
                      permission: str = "ops.dashboard:read") -> str | None:
    """One tenant resolution per lane: northbound callers are locked to their key's tenant."""
    if principal.kind == "api_key":
        locked = principal.identity.tenant_id
        if tenant_id is not None and tenant_id != locked:
            raise HTTPException(403, "Northbound monitoring is limited to the API key's tenant")
        return locked
    return operations_scope(principal.user, tenant_id, permission)


async def nb_action_guard(request: Request,
                          principal: Annotated[OpsPrincipal, Depends(ops_principal)]) -> None:
    """Per-tenant rate limit for northbound action routes; query routes stay unthrottled."""
    if principal.kind == "api_key":
        from backend.http.server.northbound import check_and_consume_rate_limit

        await check_and_consume_rate_limit(principal.identity.tenant_id)


def _audit_outcome(status_code: int) -> str:
    return "denied" if status_code in (401, 403) else "failed"


def _nb_audit(principal: OpsPrincipal, request: Request, capability: str, outcome: str,
              target: dict) -> None:
    """Record one northbound action audit event; fail-open like the gate policy hook."""
    if principal.kind != "api_key":
        return
    try:
        from backend.http.server.security_audit import record_security_event

        record_security_event(
            f"northbound_{capability.replace('.', '_')}",
            request=request, user_id=principal.identity.user_id, tenant_id=principal.identity.tenant_id,
            details={"capability": capability, "token_id": principal.identity.token_id, "target": target,
                     "outcome": outcome, "request_id": get_request_id(request)},
            result=outcome,
        )
    except Exception:
        logger.warning("Northbound monitoring audit write failed capability=%s", capability)


def ops_tenant(scope: Annotated[Selection, Depends(selection)],
               principal: Annotated[OpsPrincipal, Depends(ops_principal)]):
    return ops_scoped_tenant(principal, scope.tenant_id)


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


def _read_skill(request, scope, tenant):
    service = getattr(request.app.state, "monitoring", None)
    if service is None:
        raise HTTPException(503, "Skill monitoring is unavailable")
    try:
        return read_skills(service, tenant=tenant, start=scope.start_date, end=scope.end_date,
                           groups=scope.group_ids, skill_id=scope.skill_id, skill_name=scope.skill_name)
    except Exception as error:
        logger.warning("Skill monitoring query failed error=%s", type(error).__name__)
        raise HTTPException(503, "Skill monitoring is temporarily unavailable") from None


def _skill_items(rows, catalog, status, search="", descending=True):
    items = skill_rows(rows, catalog, covered=status["coverage_state"] == "covered")
    needle = search.casefold()
    items = [item for item in items if needle in (item.get("skill_name") or "").casefold()]
    items.sort(key=lambda item: (item["tenant_id"] or "", item["skill_id"]))
    present = [item for item in items if skill_metric_value(item) is not None]
    missing = [item for item in items if skill_metric_value(item) is None]
    return sorted(present, key=skill_metric_value, reverse=descending) + missing


@ops_router.get("/skills", tags=["skill monitoring"])
def skills(request: Request, scope: Annotated[Selection, Depends(selection)],
           tenant: Annotated[str | None, Depends(ops_tenant)],
           page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20,
           search: Annotated[str, Query(max_length=100)] = "", descending: bool = True):
    rows, catalog, _, status = _read_skill(request, scope, tenant)
    items = _skill_items(rows, catalog, status, search, descending)
    start = (page - 1) * page_size
    return {"data": {"items": items[start:start + page_size], "total": len(items)}, **status}


@ops_router.get("/skills/summary", tags=["skill monitoring"])
def skill_summary(request: Request, scope: Annotated[Selection, Depends(selection)],
                  tenant: Annotated[str | None, Depends(ops_tenant)]):
    rows, catalog, _, status = _read_skill(request, scope, tenant)
    items = skill_rows(rows, catalog, covered=status["coverage_state"] == "covered")
    return {"data": {"current_skill_count": len(catalog),
                      "usage_count": sum(skill_metric_value(item) or 0 for item in items),
                      "skill_count": sum(skill_metric_value(item) is not None for item in items)}, **status}


@ops_router.get("/skills/rankings", tags=["skill monitoring"])
def skill_rankings(request: Request, scope: Annotated[Selection, Depends(selection)],
                   tenant: Annotated[str | None, Depends(ops_tenant)]):
    rows, catalog, _, status = _read_skill(request, scope, tenant)
    items = _skill_items(rows, catalog, status)
    return {"data": [item for item in items if skill_metric_value(item) is not None][:5], **status}


@ops_router.get("/skills/trends", tags=["skill monitoring"])
def skill_trends(request: Request, scope: Annotated[Selection, Depends(selection)],
                 tenant: Annotated[str | None, Depends(ops_tenant)]):
    rows, _, available, status = _read_skill(request, scope, tenant)
    by_date = defaultdict(int)
    for row in rows:
        by_date[row["statistic_date"]] += row.get("usage_count", 0)
    published = set(available)
    history = [{"statistic_date": day,
                "usage_count": by_date.get(day.isoformat(), 0) if day in published else None}
               for day in days_inclusive(scope.start_date, scope.end_date)]
    return {"data": history, **status}


def agent_selection(
    start_date: date, end_date: date,
    tenant_id: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    group_ids: Annotated[list[PositiveResourceId] | None, Query(max_length=100)] = None,
    agent_id: Annotated[int | None, Query(gt=0, le=2**31 - 1)] = None,
):
    _validate_range(start_date, end_date, group_ids)
    return AgentSelection(tenant_id=tenant_id, start_date=start_date, end_date=end_date,
                          group_ids=group_ids or [], agent_id=agent_id)


@ops_router.get("/agents/summary", tags=["agent monitoring"])
def agent_summary(request: Request, scope: Annotated[AgentSelection, Depends(agent_selection)],
                  principal: Annotated[OpsPrincipal, Depends(ops_principal)]):
    tenant = ops_scoped_tenant(principal, scope.tenant_id)
    service = getattr(request.app.state, "monitoring", None)
    if service is None:
        raise HTTPException(503, "Agent monitoring is unavailable")
    try:
        values, status = read_agents(service, tenant=tenant, start=scope.start_date, end=scope.end_date,
                                     groups=scope.group_ids, agent_id=scope.agent_id)
        token_usage = read_agent_tokens(service, tenant=tenant, start=scope.start_date, end=scope.end_date,
                                        groups=scope.group_ids, agent_id=scope.agent_id)
    except Exception as error:
        logger.warning("Agent monitoring query failed error=%s", type(error).__name__)
        raise HTTPException(503, "Agent monitoring is temporarily unavailable") from None
    return {"data": values, **status, "tokens": token_usage.tokens, "token_status": token_usage.status}


def _read_agent_views(request, scope, principal, *, include_tokens=True):
    tenant = ops_scoped_tenant(principal, scope.tenant_id)
    service = getattr(request.app.state, "monitoring", None)
    if service is None:
        raise HTTPException(503, "Agent monitoring is unavailable")
    try:
        items, current_count, history, status = read_agent_views(
            service, tenant=tenant, start=scope.start_date, end=scope.end_date,
            groups=scope.group_ids, agent_id=scope.agent_id,
        )
        if not include_tokens:
            return items, current_count, history, status
        resources = {(item["tenant_id"], item["agent_id"]): dict(item) for item in items}
        token_usage = read_agent_tokens(service, tenant=tenant, start=scope.start_date, end=scope.end_date,
                                        groups=scope.group_ids, agent_id=scope.agent_id, identities=resources)
        for key, usage in token_usage.agents.items():
            resources.setdefault(key, {"tenant_id": key[0], "agent_id": key[1], "is_current": False, "metrics": None})
            resources[key].update(usage)
        history = [{**row, **token_usage.days[row["statistic_date"]]} for row in history]
        return list(resources.values()), current_count, history, {**status, "token_status": token_usage.status}
    except Exception as error:
        logger.warning("Agent monitoring view failed error=%s", type(error).__name__)
        raise HTTPException(503, "Agent monitoring is temporarily unavailable") from None


def _agent_metric_value(item, metric):
    if metric == "total_tokens":
        return metric_value({"metrics": item.get("tokens")}, metric)
    return metric_value(item, metric)


def _agent_items(items, metric, search="", descending=True):
    needle = search.casefold()
    items = [item for item in items if any(needle in (item.get(name) or "").casefold()
                                         for name in ("name", "display_name"))]
    items.sort(key=lambda item: (item["tenant_id"], item["agent_id"]))
    present = [item for item in items if _agent_metric_value(item, metric) is not None]
    missing = [item for item in items if _agent_metric_value(item, metric) is None]
    return sorted(present, key=lambda item: _agent_metric_value(item, metric), reverse=descending) + missing


@ops_router.get("/agents", tags=["agent monitoring"])
def agents(request: Request, scope: Annotated[AgentSelection, Depends(agent_selection)],
           principal: Annotated[OpsPrincipal, Depends(ops_principal)],
           page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20,
           search: Annotated[str, Query(max_length=100)] = "", sort_by: AgentMetric = "execution_count",
           descending: bool = True):
    items, current_count, _, status = _read_agent_views(request, scope, principal)
    items = _agent_items(items, sort_by, search, descending)
    start = (page - 1) * page_size
    return {"data": {"items": items[start:start + page_size], "total": len(items),
                     "current_agent_count": current_count}, **status}


@ops_router.get("/agents/trends", tags=["agent monitoring"])
def agent_trends(request: Request, scope: Annotated[AgentSelection, Depends(agent_selection)],
                 principal: Annotated[OpsPrincipal, Depends(ops_principal)]):
    _, _, history, status = _read_agent_views(request, scope, principal)
    return {"data": history, **status}


@ops_router.get("/agents/rankings", tags=["agent monitoring"])
def agent_rankings(request: Request, scope: Annotated[AgentSelection, Depends(agent_selection)],
                   principal: Annotated[OpsPrincipal, Depends(ops_principal)],
                   metric: Literal["execution_count", "total_tokens", "success_rate"] = "execution_count"):
    items, _, _, status = _read_agent_views(request, scope, principal, include_tokens=metric == "total_tokens")
    ordered = _agent_items(items, metric)
    ranked = [item for item in ordered if _agent_metric_value(item, metric) is not None][:5]
    if metric == "success_rate":
        ranked = [{**item, "metrics": {**item["metrics"], "success_sample_count":
                   item["metrics"]["succeeded_count"] + item["metrics"]["failed_count"]}} for item in ranked]
    return {"data": ranked, **status}


class RefreshSelection(BaseModel):
    tenant_id: str | None = None
    start_date: date
    end_date: date


def _refresh_key(kind="model"):
    return digest(JWT_SECRET.encode(), f"ops-{kind}-monitoring-refresh".encode(), sha256)


@ops_router.post("/models/refresh", status_code=202)
def refresh_models(request: Request, scope: RefreshSelection,
                   _guard: Annotated[None, Depends(nb_action_guard)],
                   principal: Annotated[OpsPrincipal, Depends(ops_principal)]):
    target = {"start_date": scope.start_date.isoformat(), "end_date": scope.end_date.isoformat()}
    try:
        tenant = ops_scoped_tenant(principal, scope.tenant_id, permission="ops.dashboard:update")
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
        }, _refresh_key("model"), algorithm="HS256")
    except HTTPException as exc:
        _nb_audit(principal, request, "monitoring.models.refresh", _audit_outcome(exc.status_code), target)
        raise
    _nb_audit(principal, request, "monitoring.models.refresh", "success", {**target, "tenant_id": tenant})
    return {"data": {"refresh_id": token, "status": "queued"}}


@ops_router.get("/models/refreshes/{refresh_id}")
def model_refresh_status(request: Request, refresh_id: str,
                         principal: Annotated[OpsPrincipal, Depends(ops_principal)]):
    service = getattr(request.app.state, "monitoring", None)
    if service is None or not JWT_SECRET:
        raise HTTPException(503, "Model monitoring refresh is unavailable")
    try:
        target = jwt.decode(refresh_id, _refresh_key("model"), algorithms=["HS256"], audience="ops-model-monitoring-refresh")
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
    if principal.kind == "api_key" and tenant_id != principal.identity.tenant_id:
        # A foreign tenant's token stays indistinguishable from a missing one.
        raise HTTPException(404, "Monitoring refresh was not found")
    tenant = ops_scoped_tenant(principal, tenant_id, permission="ops.dashboard:update")
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


@ops_router.post("/skills/refresh", status_code=202, tags=["skill monitoring"])
def refresh_skills(request: Request, scope: RefreshSelection,
                   _guard: Annotated[None, Depends(nb_action_guard)],
                   principal: Annotated[OpsPrincipal, Depends(ops_principal)]):
    target = {"start_date": scope.start_date.isoformat(), "end_date": scope.end_date.isoformat()}
    try:
        tenant = ops_scoped_tenant(principal, scope.tenant_id, permission="ops.dashboard:update")
        if tenant is None or not 0 <= (scope.end_date - scope.start_date).days < 366:
            raise HTTPException(422, "Refresh requires a single tenant and a valid date range")
        service = getattr(request.app.state, "monitoring", None)
        if service is None or not JWT_SECRET:
            raise HTTPException(503, "Skill monitoring refresh is unavailable")
        try:
            rows = service.store.states(tenant, "skill", scope.start_date, scope.end_date)
        except Exception:
            raise HTTPException(503, "Skill monitoring refresh is temporarily unavailable") from None
        revisions = {row["statistic_date"].isoformat(): row["source_revision"] for row in rows}
        dates = [day.isoformat() for day in days_inclusive(scope.start_date, scope.end_date)]
        missing_dates = [day for day in dates if day not in revisions]
        if missing_dates:
            raise HTTPException(409, {"code": "MONITORING_DATES_UNCOVERED", "missing_dates": missing_dates})
        now = datetime.now(timezone.utc)
        revision_bytes = pack(f"!{len(dates)}Q", *(revisions[day] for day in dates))
        token = jwt.encode({
            "aud": "ops-skill-monitoring-refresh", "tenant": tenant,
            "start": scope.start_date.isoformat(), "end": scope.end_date.isoformat(),
            "revisions": {}, "revision_bytes": urlsafe_b64encode(revision_bytes).decode("ascii"),
            "requested": now.timestamp(), "exp": now + timedelta(minutes=10),
        }, _refresh_key("skill"), algorithm="HS256")
    except HTTPException as exc:
        _nb_audit(principal, request, "monitoring.skills.refresh", _audit_outcome(exc.status_code), target)
        raise
    _nb_audit(principal, request, "monitoring.skills.refresh", "success", {**target, "tenant_id": tenant})
    return {"data": {"refresh_id": token, "status": "queued"}}


@ops_router.get("/skills/refreshes/{refresh_id}", tags=["skill monitoring"])
def skill_refresh_status(request: Request, refresh_id: str,
                         principal: Annotated[OpsPrincipal, Depends(ops_principal)]):
    service = getattr(request.app.state, "monitoring", None)
    if service is None or not JWT_SECRET:
        raise HTTPException(503, "Skill monitoring refresh is unavailable")
    try:
        target = jwt.decode(refresh_id, _refresh_key("skill"), algorithms=["HS256"],
                           audience="ops-skill-monitoring-refresh")
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
    if principal.kind == "api_key" and tenant_id != principal.identity.tenant_id:
        # A foreign tenant's token stays indistinguishable from a missing one.
        raise HTTPException(404, "Monitoring refresh was not found")
    tenant = ops_scoped_tenant(principal, tenant_id, permission="ops.dashboard:update")
    try:
        rows = service.store.states(tenant, "skill", start, end)
    except Exception:
        raise HTTPException(503, "Skill monitoring refresh is temporarily unavailable") from None
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

class ToolSelection(BaseModel):
    tenant_id: str | None
    start_date: date
    end_date: date
    # Group filtering matches MCPs explicitly configured for these groups (the
    # management access groups); public servers and the tenant-local endpoint
    # never match an active group filter.
    group_ids: list[int]
    server_id: int | None
    # Same normalized values the fact contract carries; an unknown filter value
    # is a client error instead of a silently empty result.
    server_type: McpServerType | None
    tool_name: str | None


def tool_selection(start_date: date, end_date: date, tenant_id: str | None = None,
                   group_ids: Annotated[list[int] | None, Query(max_length=100)] = None,
                   server_id: Annotated[int | None, Query(gt=0)] = None,
                   server_type: McpServerType | None = None,
                   tool_name: Annotated[str | None, Query(max_length=200)] = None):
    if not 0 <= (end_date - start_date).days < 366 or any(group <= 0 for group in group_ids or ()):
        raise HTTPException(422, "Invalid monitoring date range or group ID")
    return ToolSelection(tenant_id=tenant_id, start_date=start_date, end_date=end_date, group_ids=group_ids or [],
                         server_id=server_id, server_type=server_type, tool_name=tool_name)


def _read_tools(request, scope, tenant):
    service = getattr(request.app.state, "monitoring", None)
    if service is None:
        raise HTTPException(503, "MCP tool monitoring is unavailable")
    try:
        return read_mcp_tools(service, tenant=tenant, start=scope.start_date, end=scope.end_date,
                              groups=scope.group_ids, server_id=scope.server_id, server_type=scope.server_type,
                              tool_name=scope.tool_name)
    except Exception as error:
        logger.warning("MCP tool monitoring query failed error=%s", type(error).__name__)
        raise HTTPException(503, "MCP tool monitoring is temporarily unavailable") from None


def _tool_items(rows, status, metric, search="", descending=True):
    items = mcp_tool_rows(rows)
    items = [item for item in items if search.casefold() in (item.get("tool_name") or "").casefold()]
    items.sort(key=lambda item: (item["tenant_id"], item.get("mcp_server_id") or 0, item["tool_name"]))
    present = [item for item in items if metric_value(item, metric) is not None]
    missing = [item for item in items if metric_value(item, metric) is None]
    return sorted(present, key=lambda item: metric_value(item, metric), reverse=descending) + missing


def _server_items(rows, inventory, status, metric, search="", descending=True):
    covered = status["coverage_state"] == "covered"
    items = mcp_server_rows(rows, inventory, covered=covered)
    items = [item for item in items if search.casefold() in (item.get("mcp_server_name") or "").casefold()]
    items.sort(key=lambda item: (item["tenant_id"], item.get("mcp_server_id") or 0))
    present = [item for item in items if metric_value(item, metric) is not None]
    missing = [item for item in items if metric_value(item, metric) is None]
    return sorted(present, key=lambda item: metric_value(item, metric), reverse=descending) + missing


@ops_router.get("/mcp-tools")
def mcp_tools(request: Request, scope: Annotated[ToolSelection, Depends(tool_selection)],
              tenant: Annotated[str | None, Depends(ops_tenant)],
              dimension: Literal["tools", "services"] = "services",
              page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20,
              search: Annotated[str, Query(max_length=100)] = "", sort_by: ToolMetric = "request_count",
              descending: bool = True):
    rows, inventory, _, status = _read_tools(request, scope, tenant)
    if dimension == "services":
        items = _server_items(rows, inventory, status, sort_by, search, descending)
    else:
        items = _tool_items(rows, status, sort_by, search, descending)
    start = (page - 1) * page_size
    return {"data": {"items": items[start:start + page_size], "total": len(items)}, **status}


@ops_router.get("/mcp-tools/summary")
def mcp_tools_summary(request: Request, scope: Annotated[ToolSelection, Depends(tool_selection)],
                      tenant: Annotated[str | None, Depends(ops_tenant)]):
    rows, inventory, available, status = _read_tools(request, scope, tenant)
    covered = status["coverage_state"] == "covered"
    servers = mcp_server_rows(rows, inventory, covered=covered)
    tools = mcp_tool_rows(rows)
    if available:
        values = summarize_mcp_tool(rows)
        active_servers = sum(1 for server in servers if server["metrics"]["request_count"])
        active_tools = sum(1 for tool in tools if tool["metrics"]["request_count"])
    else:
        values = dict.fromkeys(summarize_mcp_tool(()))
        active_servers = active_tools = 0
    return {"data": {"service_count": len(servers), "active_services": active_servers,
                     "tool_count": len(tools), "active_tools": active_tools, **values}, **status}


@ops_router.get("/mcp-tools/rankings")
def mcp_tools_rankings(request: Request, scope: Annotated[ToolSelection, Depends(tool_selection)],
                       tenant: Annotated[str | None, Depends(ops_tenant)],
                       dimension: Literal["tools", "services"] = "services",
                       metric: ToolMetric = "request_count"):
    rows, inventory, _, status = _read_tools(request, scope, tenant)
    if dimension == "services":
        items = _server_items(rows, inventory, status, metric)
    else:
        items = _tool_items(rows, status, metric)
    return {"data": [item for item in items if metric_value(item, metric) is not None][:5], **status}


@ops_router.get("/mcp-tools/trends")
def mcp_tools_trends(request: Request, scope: Annotated[ToolSelection, Depends(tool_selection)],
                     tenant: Annotated[str | None, Depends(ops_tenant)]):
    rows, _, available, status = _read_tools(request, scope, tenant)
    by_date = {}
    for row in rows:
        by_date.setdefault(row["statistic_date"], []).append(row)
    published = set(available)
    missing_metrics = dict.fromkeys(summarize_mcp_tool(()))
    history = []
    for day in days_inclusive(scope.start_date, scope.end_date):
        metrics = summarize_mcp_tool(by_date.get(day.isoformat(), ())) if day in published else missing_metrics
        history.append({"statistic_date": day, **metrics})
    return {"data": history, **status}


def _tool_refresh_key():
    return digest(JWT_SECRET.encode(), b"ops-mcp-tool-monitoring-refresh", sha256)


@ops_router.post("/mcp-tools/refresh", status_code=202)
def refresh_mcp_tools(request: Request, scope: RefreshSelection,
                      _guard: Annotated[None, Depends(nb_action_guard)],
                      principal: Annotated[OpsPrincipal, Depends(ops_principal)]):
    target = {"start_date": scope.start_date.isoformat(), "end_date": scope.end_date.isoformat()}
    try:
        tenant = ops_scoped_tenant(principal, scope.tenant_id, permission="ops.dashboard:update")
        if tenant is None or not 0 <= (scope.end_date - scope.start_date).days < 366:
            raise HTTPException(422, "Refresh requires a single tenant and a valid date range")
        service = getattr(request.app.state, "monitoring", None)
        if service is None or not JWT_SECRET:
            raise HTTPException(503, "MCP tool monitoring refresh is unavailable")
        try:
            rows = service.store.states(tenant, "mcp_tool", scope.start_date, scope.end_date)
        except Exception:
            raise HTTPException(503, "MCP tool monitoring refresh is temporarily unavailable") from None
        revisions = {row["statistic_date"].isoformat(): row["source_revision"] for row in rows}
        dates = [day.isoformat() for day in days_inclusive(scope.start_date, scope.end_date)]
        missing_dates = [day for day in dates if day not in revisions]
        if missing_dates:
            raise HTTPException(409, {"code": "MONITORING_DATES_UNCOVERED", "missing_dates": missing_dates})
        now = datetime.now(timezone.utc)
        revision_bytes = pack(f"!{len(dates)}Q", *(revisions[day] for day in dates))
        token = jwt.encode({
            "aud": "ops-mcp-tool-monitoring-refresh", "tenant": tenant,
            "start": scope.start_date.isoformat(), "end": scope.end_date.isoformat(),
            "revisions": {},  # An older worker can report the target as uncovered during a rollout.
            "revision_bytes": urlsafe_b64encode(revision_bytes).decode("ascii"),
            "requested": now.timestamp(), "exp": now + timedelta(minutes=10),
        }, _tool_refresh_key(), algorithm="HS256")
    except HTTPException as exc:
        _nb_audit(principal, request, "monitoring.mcp_tools.refresh", _audit_outcome(exc.status_code), target)
        raise
    _nb_audit(principal, request, "monitoring.mcp_tools.refresh", "success", {**target, "tenant_id": tenant})
    return {"data": {"refresh_id": token, "status": "queued"}}


@ops_router.get("/mcp-tools/refreshes/{refresh_id}")
def mcp_tool_refresh_status(request: Request, refresh_id: str,
                            principal: Annotated[OpsPrincipal, Depends(ops_principal)]):
    service = getattr(request.app.state, "monitoring", None)
    if service is None or not JWT_SECRET:
        raise HTTPException(503, "MCP tool monitoring refresh is unavailable")
    try:
        target = jwt.decode(refresh_id, _tool_refresh_key(), algorithms=["HS256"],
                            audience="ops-mcp-tool-monitoring-refresh")
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
    if principal.kind == "api_key" and tenant_id != principal.identity.tenant_id:
        # A foreign tenant's token stays indistinguishable from a missing one.
        raise HTTPException(404, "Monitoring refresh was not found")
    tenant = ops_scoped_tenant(principal, tenant_id, permission="ops.dashboard:update")
    try:
        rows = service.store.states(tenant, "mcp_tool", start, end)
    except Exception:
        raise HTTPException(503, "MCP tool monitoring refresh is temporarily unavailable") from None
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


@ops_router.get("/mcp-tools/catalog")
def mcp_tools_catalog(principal: Annotated[OpsPrincipal, Depends(ops_principal)],
                      tenant_id: Annotated[str | None, Query(max_length=100)] = None,
                      group_ids: Annotated[list[int] | None, Query(max_length=100)] = None):
    if any(group <= 0 for group in group_ids or ()):
        raise HTTPException(422, "Invalid monitoring group ID")
    tenant = ops_scoped_tenant(principal, tenant_id)
    return {"data": mcp_server_catalog(tenant, group_ids)}


@ops_router.get("/mcp-tools/overview")
def mcp_tools_overview(request: Request, scope: Annotated[ToolSelection, Depends(tool_selection)],
                       tenant: Annotated[str | None, Depends(ops_tenant)]):
    """Platform overview inputs: per-tenant server inventory and daily call volume.

    ``tenant`` is ``None`` for SU readers (whole platform) and the caller's
    tenant otherwise; the trend carries ``None`` for unpublished days, mirroring
    the trends endpoint.
    """
    rows, _, available, status = _read_tools(request, scope, tenant)
    by_date = {}
    for row in rows:
        by_date.setdefault(row["statistic_date"], []).append(row)
    published = set(available)
    missing_metrics = dict.fromkeys(summarize_mcp_tool(()))
    trend = []
    for day in days_inclusive(scope.start_date, scope.end_date):
        metrics = summarize_mcp_tool(by_date.get(day.isoformat(), ())) if day in published else missing_metrics
        trend.append({"statistic_date": day, "request_count": metrics["request_count"]})
    return {"data": {"services_by_tenant": mcp_services_by_tenant(tenant), "calls_trend": trend}, **status}
