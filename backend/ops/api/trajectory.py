# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded historical trajectory APIs; all blocking work uses managed workers."""

import logging
from typing import Annotated

from contracts.errors.exceptions import UnauthorizedError
from contracts.trajectory import CleanupRequest, CleanupScheduleRequest, RecordsQuery
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from gateway.authentication.auth import get_current_user_context
from nexent.core.concurrency import ManagedTaskSpec
from ops.services.trajectory.access import Actor
from ops.services.trajectory.cleanup import cleanup
from ops.services.trajectory.cleanup_schedule import read_schedule, save_schedule
from ops.services.trajectory.collection import facets, records
from ops.services.trajectory.primitives import CURRENT_CANCEL, QueryError
from ops.services.trajectory.runtime import get_service
from pydantic import ValidationError

logger = logging.getLogger(__name__)
PRIVATE = {"Cache-Control": "private,no-store"}


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            if not self.path.startswith(("/trajectory/", "/conversation/agent_groups")):
                return await handler(request)
            try:
                response = await handler(request)
            except RequestValidationError:
                response = JSONResponse(status_code=422, content={"detail": {"code": "invalid_parameters"}})
            except HTTPException as error:
                response = JSONResponse(
                    status_code=error.status_code,
                    content={"detail": error.detail},
                    headers=error.headers,
                )
            response.headers.update(PRIVATE)
            return response

        return private_handler


router = APIRouter(prefix="/trajectory", route_class=PrivateRoute)


async def dispatch(request, authorization, operation, *, lane="trajectory-read", needs_service=True):
    def work(cancel_event):
        user, tenant, role = get_current_user_context(authorization)
        if not user:
            raise QueryError("unauthenticated", 401)
        actor = Actor(user, tenant, role)
        if role not in {"ADMIN", "SU"}:
            raise QueryError("administrator_required", 403)
        token = CURRENT_CANCEL.set(cancel_event)
        try:
            return operation(get_service() if needs_service else None, actor)
        finally:
            CURRENT_CANCEL.reset(token)

    try:
        manager = request.app.state.thread_manager
        result = await manager.run(
            lane,
            ManagedTaskSpec(task_name="trajectory-query", owner=__name__, pass_cancel_event=True),
            work,
        )
        return JSONResponse(content={"code": 0, "message": "success", "data": result}, headers=PRIVATE)
    except UnauthorizedError:
        return JSONResponse(
            status_code=401,
            content={"detail": {"code": "unauthenticated"}},
            headers=PRIVATE,
        )
    except QueryError as error:
        headers = {
            **PRIVATE,
            **({"Retry-After": str(error.retry_after)} if error.retry_after else {}),
        }
        return JSONResponse(
            status_code=error.status,
            content={"detail": {"code": error.code}},
            headers=headers,
        )
    except (ValueError, ValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "invalid_parameters"}},
            headers=PRIVATE,
        )
    except HTTPException as error:
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": error.detail},
            headers={**PRIVATE, **(error.headers or {})},
        )
    except Exception as error:  # noqa: BLE001 - Contain storage/DB faults at the HTTP boundary.
        from nexent.core.concurrency import ThreadCapacityExceeded, ThreadQueueTimedOut

        if isinstance(error, (ThreadCapacityExceeded, ThreadQueueTimedOut)):
            return JSONResponse(
                status_code=503,
                content={"detail": {"code": "query_busy"}},
                headers={**PRIVATE, "Retry-After": "2"},
            )
        logger.error("trajectory.query_failed exception_type=%s", type(error).__name__)
        return JSONResponse(
            status_code=503,
            content={"detail": {"code": "query_unavailable"}},
            headers={**PRIVATE, "Retry-After": "2"},
        )


@router.get("/records")
async def list_records(request: Request, authorization: str | None = Header(None)):
    def operation(service, actor):
        query = RecordsQuery.model_validate(dict(request.query_params))
        if query.facet:
            return facets(
                service,
                actor,
                query.filters,
                query.facet,
                search=query.search,
                cursor=query.cursor,
                limit=query.limit,
            )
        return records(
            service,
            actor,
            query.filters,
            view=query.view,
            query_id=query.query_id,
            page=query.page,
            page_size=query.page_size,
            sort_by=query.sort_by,
            sort_order=query.sort_order,
        )

    return await dispatch(request, authorization, operation)


@router.get("/cleanup/schedule")
async def get_cleanup_schedule(
    request: Request, authorization: str | None = Header(None),
    tenant_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
):
    return await dispatch(
        request, authorization, lambda service, actor: read_schedule(actor, tenant_id), needs_service=False,
    )


@router.put("/cleanup/schedule")
async def put_cleanup_schedule(
    request: Request, body: CleanupScheduleRequest, authorization: str | None = Header(None),
):
    return await dispatch(
        request, authorization, lambda service, actor: save_schedule(actor, body.interval_seconds, body.tenant_id),
        needs_service=False,
    )


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    request: Request,
    conversation_id: str,
    authorization: str | None = Header(None),
    tenant_id: str | None = None,
    target_user_id: str | None = None,
    cursor: Annotated[str | None, Query(max_length=8192)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    include: str | None = None,
    query_id: Annotated[str | None, Query(max_length=8192)] = None,
    message_cursor: Annotated[str | None, Query(max_length=8192)] = None,
    snapshot_id: Annotated[str | None, Query(max_length=8192)] = None,
):
    return await dispatch(
        request,
        authorization,
        lambda service, actor: service.conversation(
            actor,
            conversation_id,
            tenant_id=tenant_id,
            target_user_id=target_user_id,
            cursor=cursor,
            limit=limit,
            include=include,
            message_cursor=message_cursor,
            snapshot_id=snapshot_id,
            query_id=query_id,
        ),
    )


@router.get("/conversations/{conversation_id}/snapshot")
async def get_snapshot(
    request: Request,
    conversation_id: str,
    trajectory_id: str,
    authorization: str | None = Header(None),
    tenant_id: str | None = None,
    target_user_id: str | None = None,
    cursor: Annotated[str | None, Query(max_length=8192)] = None,
    snapshot_id: Annotated[str | None, Query(max_length=8192)] = None,
    node_id: Annotated[str | None, Query(max_length=256)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
):
    return await dispatch(
        request,
        authorization,
        lambda service, actor: service.snapshot(
            actor,
            conversation_id,
            trajectory_id,
            tenant_id=tenant_id,
            target_user_id=target_user_id,
            cursor=cursor,
            snapshot_id=snapshot_id,
            node_id=node_id,
            limit=limit,
        ),
    )


@router.get("/conversations/{conversation_id}/contents/{content_id}")
async def get_content(
    request: Request,
    conversation_id: str,
    content_id: str,
    authorization: str | None = Header(None),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=4, le=1048576)] = 1048576,
):
    return await dispatch(
        request,
        authorization,
        lambda service, actor: service.content(actor, conversation_id, content_id, offset=offset, limit=limit),
    )


@router.post("/cleanup")
async def cleanup_trajectories(request: Request, body: CleanupRequest, authorization: str | None = Header(None)):
    return await dispatch(
        request,
        authorization,
        lambda service, actor: cleanup(service, actor, body.before_days, body.cursor),
        lane="trajectory-cleanup",
    )
