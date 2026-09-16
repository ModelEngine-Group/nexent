"""Northbound HITL controls authenticated by API key and executed by runtime."""

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from apps.northbound_app import _get_northbound_context
from consts.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError
from services.human_interaction.models import DecisionCommand, SteeringCommand
from services.northbound_service import NorthboundContext
from services.runtime_proxy_service import forward_human_interaction, forward_human_interaction_events

router = APIRouter(prefix="/nb/v1/chat/human-interactions", tags=["northbound-human-interaction"])


async def _forward(ctx, method, path, *, command=None, after_event=None):
    try:
        if after_event is not None:
            response = await forward_human_interaction_events(
                path, ctx.user_id, ctx.tenant_id, after_event=after_event,
            )
            response.headers["X-Request-Id"] = ctx.request_id
            response.headers["X-Accel-Buffering"] = "no"
            return response
        result = await forward_human_interaction(
            method, path, ctx.user_id, ctx.tenant_id,
            payload=command.model_dump(mode="json") if command is not None else None,
        )
        return JSONResponse(
            {"message": "success", "requestId": ctx.request_id, "data": result},
            headers={"X-Request-Id": ctx.request_id},
        )
    except RuntimeUpstreamError as exc:
        return Response(content=exc.content, status_code=exc.status_code, headers=exc.headers)
    except RuntimeServiceTimeoutError as exc:
        raise HTTPException(status_code=HTTPStatus.GATEWAY_TIMEOUT, detail=str(exc)) from exc
    except RuntimeServiceUnavailableError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/capabilities")
async def capabilities(ctx: NorthboundContext = Depends(_get_northbound_context)):
    """Read the runtime deployment's HITL capabilities."""
    return await _forward(ctx, "GET", "capabilities")


@router.get("/conversation/{conversation_id}")
async def conversation_snapshot(conversation_id: int, ctx: NorthboundContext = Depends(_get_northbound_context)):
    """Find this API user's latest run in a conversation, including pending cards."""
    return await _forward(ctx, "GET", f"conversation/{conversation_id}")


@router.get("/{run_id}")
async def snapshot(run_id: UUID, ctx: NorthboundContext = Depends(_get_northbound_context)):
    return await _forward(ctx, "GET", str(run_id))


@router.get("/{run_id}/events")
async def events(
    run_id: UUID,
    request: Request,
    after_event: int = Query(0, ge=0, description="Last consumed SSE event ID; 0 replays the run."),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    ctx: NorthboundContext = Depends(_get_northbound_context),
):
    """Subscribe to the same run after submitting a decision or reconnecting."""
    if last_event_id is not None and "after_event" not in request.query_params:
        if not last_event_id.isascii() or not last_event_id.isdigit() or len(last_event_id) > 19:
            raise HTTPException(status_code=422, detail="Last-Event-ID must be a non-negative integer")
        after_event = int(last_event_id)
    return await _forward(ctx, "GET", str(run_id), after_event=after_event)


@router.post("/{run_id}/requests/{request_id}/decisions")
async def decide(
    run_id: UUID,
    request_id: UUID,
    command: DecisionCommand,
    ctx: NorthboundContext = Depends(_get_northbound_context),
):
    """Submit a versioned, idempotent answer or approval to the exact pending card."""
    return await _forward(ctx, "POST", f"{run_id}/requests/{request_id}/decisions", command=command)


@router.post("/{run_id}/pause")
async def pause(run_id: UUID, ctx: NorthboundContext = Depends(_get_northbound_context)):
    return await _forward(ctx, "POST", f"{run_id}/pause")


@router.post("/{run_id}/steer")
async def steer(run_id: UUID, command: SteeringCommand, ctx: NorthboundContext = Depends(_get_northbound_context)):
    """Submit new guidance; runtime cancels any pending card before applying it."""
    return await _forward(ctx, "POST", f"{run_id}/steer", command=command)


@router.post("/{run_id}/terminate")
async def terminate(run_id: UUID, ctx: NorthboundContext = Depends(_get_northbound_context)):
    return await _forward(ctx, "POST", f"{run_id}/terminate")
