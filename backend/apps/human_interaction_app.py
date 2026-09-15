"""HTTP boundary for owner-scoped human decisions and independent run controls."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from nexent.core.concurrency import run_blocking

from consts.const import HITL_ACCEPT_NEW_RUNS, HITL_ENABLED, HITL_TOOL_APPROVAL_ENABLED
from consts.exceptions import UnauthorizedError
from services.human_interaction.application import require_enabled, stream_run
from services.human_interaction.models import DecisionCommand, InteractionError, SteeringCommand
from utils.auth_utils import get_current_user_id


async def _user_identity(authorization: str = Header(None)):
    return get_current_user_id(authorization)


async def _internal_identity(authorization: str = Header(None)):
    from utils.auth_utils import verify_internal_runtime_jwt

    try:
        return verify_internal_runtime_jwt(authorization)
    except UnauthorizedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


async def _call(identity, callback):
    user_id, tenant_id = identity
    try:
        return await run_blocking(
            "hitl-callback", callback, require_enabled(), tenant_id, user_id, lane="control-io",
            owner=__name__,
        )
    except InteractionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _build_router(prefix, identity_dependency, *, include_in_schema=True):
    """Share the lifecycle contract while keeping session and internal JWT authentication separate."""
    result = APIRouter(prefix=prefix, tags=["human-interaction"], include_in_schema=include_in_schema)

    @result.get("/capabilities")
    async def capabilities(identity=Depends(identity_dependency)):
        return {"enabled": HITL_ENABLED, "accept_new_runs": HITL_ACCEPT_NEW_RUNS,
                "executor": "linear-json-v1" if HITL_TOOL_APPROVAL_ENABLED else "native-live-v1", "live_resume": True,
                "tool_approval_enabled": HITL_TOOL_APPROVAL_ENABLED,
                "subagents": not HITL_TOOL_APPROVAL_ENABLED, "attachments": not HITL_TOOL_APPROVAL_ENABLED,
                "clarification_max_questions": 5, "clarification_max_cards": 1}

    @result.get("/conversation/{conversation_id}")
    async def conversation_snapshot(conversation_id: int, identity=Depends(identity_dependency)):
        def read(service, tenant_id, user_id):
            run_id = service.repository.latest(tenant_id, user_id, conversation_id)
            return service.snapshot(run_id, tenant_id, user_id) if run_id else None
        return await _call(identity, read)

    @result.get("/{run_id}")
    async def snapshot(run_id: str, identity=Depends(identity_dependency)):
        return await _call(identity, lambda service, tenant, user: service.snapshot(run_id, tenant, user))

    @result.get("/{run_id}/events")
    async def events(run_id: str, after_event: int = Query(0, ge=0), identity=Depends(identity_dependency)):
        user_id, tenant_id = identity
        try:
            return await stream_run(run_id, tenant_id, user_id, after=after_event)
        except InteractionError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @result.post("/{run_id}/requests/{request_id}/decisions")
    async def decide(run_id: str, request_id: str, command: DecisionCommand, identity=Depends(identity_dependency)):
        return await _call(identity, lambda service, tenant, user:
                           service.decide(run_id, request_id, tenant, user, command))

    @result.post("/{run_id}/pause")
    async def pause(run_id: str, identity=Depends(identity_dependency)):
        return await _call(identity, lambda service, tenant, user: service.control(run_id, tenant, user, "pause"))

    @result.post("/{run_id}/steer")
    async def steer(run_id: str, command: SteeringCommand, identity=Depends(identity_dependency)):
        return await _call(identity, lambda service, tenant, user: service.steer(run_id, tenant, user, command))

    @result.post("/{run_id}/terminate")
    async def terminate(run_id: str, identity=Depends(identity_dependency)):
        return await _call(identity, lambda service, tenant, user: service.control(run_id, tenant, user, "terminate"))

    return result


router = _build_router("/agent/human-interactions", _user_identity)
internal_router = _build_router(
    "/agent/internal/northbound/human-interactions", _internal_identity, include_in_schema=False,
)
