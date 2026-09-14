"""HTTP boundary for owner-scoped human decisions and independent run controls."""

import asyncio

from consts.const import HITL_ACCEPT_NEW_RUNS, HITL_ENABLED, HITL_TOOL_APPROVAL_ENABLED
from fastapi import APIRouter, Header, HTTPException
from services.human_interaction.application import require_enabled
from services.human_interaction.models import (
    DecisionCommand,
    InteractionError,
    SteeringCommand,
)
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/agent/human-interactions", tags=["human-interaction"])


async def _call(authorization, callback):
    user_id, tenant_id = get_current_user_id(authorization)
    try:
        return await asyncio.to_thread(callback, require_enabled(), tenant_id, user_id)
    except InteractionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/capabilities")
async def capabilities(authorization: str = Header(None)):
    get_current_user_id(authorization)
    return {"enabled": HITL_ENABLED, "accept_new_runs": HITL_ACCEPT_NEW_RUNS,
            "executor": "linear-json-v1" if HITL_TOOL_APPROVAL_ENABLED else "native-live-v1", "live_resume": True,
            "tool_approval_enabled": HITL_TOOL_APPROVAL_ENABLED,
            "subagents": not HITL_TOOL_APPROVAL_ENABLED, "attachments": not HITL_TOOL_APPROVAL_ENABLED,
            "clarification_max_questions": 5, "clarification_max_cards": 1}


@router.get("/conversation/{conversation_id}")
async def conversation_snapshot(conversation_id: int, authorization: str = Header(None)):
    def read(service, tenant_id, user_id):
        run_id = service.repository.latest(tenant_id, user_id, conversation_id)
        return service.snapshot(run_id, tenant_id, user_id) if run_id else None
    return await _call(authorization, read)


@router.get("/{run_id}")
async def snapshot(run_id: str, authorization: str = Header(None)):
    return await _call(authorization, lambda service, tenant, user: service.snapshot(run_id, tenant, user))


@router.post("/{run_id}/requests/{request_id}/decisions")
async def decide(run_id: str, request_id: str, command: DecisionCommand, authorization: str = Header(None)):
    return await _call(authorization, lambda service, tenant, user:
                       service.decide(run_id, request_id, tenant, user, command))


@router.post("/{run_id}/pause")
async def pause(run_id: str, authorization: str = Header(None)):
    return await _call(authorization, lambda service, tenant, user: service.control(run_id, tenant, user, "pause"))


@router.post("/{run_id}/steer")
async def steer(run_id: str, command: SteeringCommand, authorization: str = Header(None)):
    return await _call(authorization, lambda service, tenant, user: service.steer(run_id, tenant, user, command))


@router.post("/{run_id}/terminate")
async def terminate(run_id: str, authorization: str = Header(None)):
    return await _call(authorization, lambda service, tenant, user: service.control(run_id, tenant, user, "terminate"))
