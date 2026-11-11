# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Northbound gates for automation task queries and (dark) actions.

The two query capabilities are open this phase. The action capabilities are
declared in northbound.yaml with ``enabled: false`` — declared but not
serving: the gate code exists so operations can open a capability by
flipping one reviewed manifest line, and the gateway returns 404 for them
until then (indistinguishable from nonexistent).
"""

from typing import Annotated, Callable, Optional

from fastapi import APIRouter, Depends, Query

from contracts.authentication import AuthenticatedIdentity
from management.services.permission.identity.dependency import unified_identity
from management.services.permission.identity.gate_policies import (
    audit_hook,
    audit_outcome,
    northbound_envelope_factory,
)
from management.services.automation.service import agent_automation_facade

nb_automation_router = APIRouter(prefix="/nb/v1/automations", tags=["northbound-gates"])


@nb_automation_router.get("")
async def nb_list_automations(
    status: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=200),
    agent_name: Optional[str] = Query(default=None, max_length=200),
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ctx: AuthenticatedIdentity = Depends(unified_identity),
    envelope: Callable = Depends(northbound_envelope_factory),
):
    """List the calling partner's automation tasks."""
    return envelope(
        agent_automation_facade.list_tasks(
            ctx.tenant_id,
            ctx.user_id,
            status,
            search,
            agent_name,
            page,
            page_size,
        )
    )


@nb_automation_router.get("/{task_id}")
async def nb_get_automation(
    task_id: int,
    ctx: AuthenticatedIdentity = Depends(unified_identity),
    envelope: Callable = Depends(northbound_envelope_factory),
):
    """Fetch one automation task owned by the calling partner."""
    return envelope(agent_automation_facade.get_task(task_id, ctx.tenant_id, ctx.user_id))


# ── Dark action gates: present in code, serving only after the manifest ──
# ── flips them on (see northbound.yaml automations.pause/resume/run/delete) ──

@nb_automation_router.post("/{task_id}/pause")
async def nb_pause_automation(
    task_id: int,
    ctx: AuthenticatedIdentity = Depends(unified_identity),
    envelope: Callable = Depends(northbound_envelope_factory),
    audit: Callable = Depends(audit_hook("automations.pause")),
):
    target = {"task_id": task_id}
    try:
        result = agent_automation_facade.pause_task(task_id, ctx.tenant_id, ctx.user_id)
    except Exception as exc:
        audit(audit_outcome(exc), target)
        raise
    audit("success", target)
    return envelope(result)


@nb_automation_router.post("/{task_id}/resume")
async def nb_resume_automation(
    task_id: int,
    ctx: AuthenticatedIdentity = Depends(unified_identity),
    envelope: Callable = Depends(northbound_envelope_factory),
    audit: Callable = Depends(audit_hook("automations.resume")),
):
    target = {"task_id": task_id}
    try:
        result = agent_automation_facade.resume_task(task_id, ctx.tenant_id, ctx.user_id)
    except Exception as exc:
        audit(audit_outcome(exc), target)
        raise
    audit("success", target)
    return envelope(result)


@nb_automation_router.post("/{task_id}/run")
async def nb_run_automation(
    task_id: int,
    ctx: AuthenticatedIdentity = Depends(unified_identity),
    envelope: Callable = Depends(northbound_envelope_factory),
    audit: Callable = Depends(audit_hook("automations.run")),
):
    target = {"task_id": task_id}
    try:
        result = await agent_automation_facade.run_task_now(task_id, ctx.tenant_id, ctx.user_id)
    except Exception as exc:
        audit(audit_outcome(exc), target)
        raise
    audit("success", target)
    return envelope(result)


@nb_automation_router.delete("/{task_id}")
async def nb_delete_automation(
    task_id: int,
    ctx: AuthenticatedIdentity = Depends(unified_identity),
    envelope: Callable = Depends(northbound_envelope_factory),
    audit: Callable = Depends(audit_hook("automations.delete")),
):
    target = {"task_id": task_id}
    try:
        result = agent_automation_facade.delete_task(task_id, ctx.tenant_id, ctx.user_id)
    except Exception as exc:
        audit(audit_outcome(exc), target)
        raise
    audit("success", target)
    return envelope(result)


@nb_automation_router.get("/{task_id}/runs")
async def nb_list_automation_runs(
    task_id: int,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ctx: AuthenticatedIdentity = Depends(unified_identity),
    envelope: Callable = Depends(northbound_envelope_factory),
):
    return envelope(
        agent_automation_facade.list_runs(task_id, ctx.tenant_id, ctx.user_id, page, page_size)
    )


@nb_automation_router.post("/runs/{run_id}/cancel")
async def nb_cancel_automation_run(
    run_id: int,
    ctx: AuthenticatedIdentity = Depends(unified_identity),
    envelope: Callable = Depends(northbound_envelope_factory),
    audit: Callable = Depends(audit_hook("automations.run_cancel")),
):
    target = {"run_id": run_id}
    try:
        result = agent_automation_facade.cancel_run(run_id, ctx.tenant_id, ctx.user_id)
    except Exception as exc:
        audit(audit_outcome(exc), target)
        raise
    audit("success", target)
    return envelope(result)
