# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Query, Request
from starlette.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError as PayloadValidationError
from sqlalchemy.exc import SQLAlchemyError
from nexent.core.concurrency import run_blocking
from contracts.agent import AgentRequest
from contracts.errors.exceptions import ForbiddenError, AppException, UnauthorizedError, ValidationError, RuntimeCapacityExceededError, RuntimeQueueTimeoutError, WorkbenchConfigVersionConflict, WorkbenchError
from management.services.agent.subscription import run_agent_stream as run_legacy_agent_stream
from contracts.errors.exceptions import RunModelControlsError
from gateway.downstream.identity import IdentityError, trusted_identity
from gateway.downstream.internal_tokens import verify_internal_runtime_jwt
from infrastructure.agentos_identity import ServicePrincipal
from contracts.agentos import (
    BackgroundRun, CompatibilityConversationRun, TrackedBackgroundResult,
)
from infrastructure.rdb.agent_execution import ActiveExecutionError, read_execution
from runtime.adapters.nexent.factory import materialize_legacy_run
from runtime.agentos.debug import stop_agentos_debug
from runtime.agentos.legacy_admission import admit_legacy_execution
from runtime.agentos.legacy_resume import resume_legacy_conversation
from runtime.executions import AgentRunManager, agent_run_manager, stop_registered_run
from runtime.thread_management import (
    agent_stream_producer_tasks,
    channel_cleanup_tasks,
    external_memory_ingest_tasks,
    fa_extraction_tasks,
    runtime_thread_manager,
    unregister_after_worker_exit,
)

agent_runtime_router = APIRouter(prefix="/agent")




logger = logging.getLogger("agent_app")


@dataclass(frozen=True)
class LegacyExecutionHost:
    registry: AgentRunManager
    admit: Callable
    unregister: Callable[..., bool]
    producer_tasks: set[asyncio.Task]
    cleanup_tasks: set[asyncio.Task]
    ingest_tasks: set[asyncio.Task]
    extraction_tasks: set[asyncio.Task]


_legacy_execution_host = LegacyExecutionHost(
    registry=agent_run_manager,
    admit=partial(admit_legacy_execution, agent_run_manager),
    unregister=partial(unregister_after_worker_exit, agent_run_manager),
    producer_tasks=agent_stream_producer_tasks,
    cleanup_tasks=channel_cleanup_tasks,
    ingest_tasks=external_memory_ingest_tasks,
    extraction_tasks=fa_extraction_tasks,
)


async def run_agent_stream(**options):
    return await run_legacy_agent_stream(
        **options, legacy_materializer=materialize_legacy_run, thread_manager=runtime_thread_manager,
        execution_host=_legacy_execution_host,
    )


def _execution_conflict_response() -> JSONResponse:
    return JSONResponse(
        {"code": "AGENTOS_RUN_ALREADY_ACTIVE"}, status_code=409, headers={"X-Stream-Status": "conflict"},
    )


def _runtime_overload_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, RuntimeQueueTimeoutError):
        code = "RUNTIME_QUEUE_TIMEOUT"
        retry_after = exc.retry_after_seconds
        message = "Agent runtime queue wait timed out."
    else:
        code = "RUNTIME_CAPACITY_FULL"
        retry_after = 1
        message = "Agent runtime is at capacity."
    return JSONResponse(
        status_code=HTTPStatus.TOO_MANY_REQUESTS,
        content={"code": code, "message": message, "retryable": True},
        headers={"Retry-After": str(retry_after)},
    )


def _gateway_session_principal() -> ServicePrincipal:
    try:
        identity = trusted_identity("session")
    except IdentityError as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc
    if not identity or not identity.get("user_id") or not identity.get("tenant_id"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return ServicePrincipal(identity["user_id"], identity["tenant_id"])


@agent_runtime_router.post("/run")
async def agent_run_api(
    agent_request: AgentRequest,
    http_request: Request,
    resume: bool = Query(False, description="Resume an existing streaming conversation"),
):
    """Legacy signed Gateway entry for starting or resuming a stream."""
    agent_request._track_execution = not resume and not agent_request.is_debug
    return await _run_public_conversation(
        agent_request, http_request, _gateway_session_principal(), resume,
    )


async def run_agentos_conversation(payload: CompatibilityConversationRun, principal: ServicePrincipal):
    try:
        request = AgentRequest.model_validate(payload.request)
        headers = [(b"cookie", f"NEXT_LOCALE={payload.language}".encode("ascii"))]
        if payload.timezone:
            headers.append((b"x-user-timezone", payload.timezone.encode("latin-1")))
    except (PayloadValidationError, UnicodeEncodeError) as exc:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_AGENT_REQUEST"}) from exc
    context = Request({"type": "http", "headers": headers})
    request._track_execution = not payload.resume and not request.is_debug

    async def execute():
        return await _run_public_conversation(
            request, context, principal, payload.resume,
        )

    if payload.idempotency_key is not None or payload.claimed_run_id is not None:
        from runtime.agentos.admission import admit_conversation_run

        return await admit_conversation_run(payload, request, principal, execute)
    return await execute()


async def _run_public_conversation(agent_request, http_request, principal, resume):
    if resume and (agent_request.is_debug or (agent_request.conversation_id or 0) <= 0):
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_RESUME_REQUEST"})
    try:
        if resume:
            return await resume_legacy_conversation(
                agent_request.conversation_id, principal, workbench=agent_request.entrypoint == "workbench",
            )
        return await run_agent_stream(
            agent_request=agent_request,
            http_request=http_request,
            user_id=principal.user_id,
            tenant_id=principal.tenant_id,
            resume=False,
        )
    except ActiveExecutionError:
        return _execution_conflict_response()
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"}) from exc
    except ForbiddenError as e:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(e)) from e
    except WorkbenchError as e:
        raise HTTPException(status_code=e.status_code, detail={"code": e.code}) from e
    except RunModelControlsError as e:
        status = {"model_not_available": 404, "model_unavailable": 409, "model_type_invalid": 400}.get(e.code, 422)
        raise HTTPException(status_code=status, detail={"code": e.code}) from e
    except ValidationError as e:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except (RuntimeCapacityExceededError, RuntimeQueueTimeoutError) as exc:
        return _runtime_overload_response(exc)
    except WorkbenchConfigVersionConflict as e:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail={
                "code": "WORKBENCH_CONFIG_VERSION_CONFLICT",
                "current_version": e.current_version,
            },
        ) from e
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Agent run error: {str(e)}")
        # Only expose actual error in debug mode for better diagnosis
        # Keep generic message in normal mode for user experience
        error_detail = str(e) if agent_request.is_debug else "Agent run error."
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=error_detail)


@agent_runtime_router.post(
    "/internal/northbound/run",
    include_in_schema=False,
)
async def northbound_agent_run_api(
    agent_request: AgentRequest,
    authorization: Optional[str] = Header(None),
):
    """Compatibility route for callers on the previous deployment version."""
    try:
        user_id, tenant_id = verify_internal_runtime_jwt(authorization)
    except UnauthorizedError as exc:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc)) from exc
    return await _execute_northbound_run(agent_request, user_id, tenant_id)


async def run_agentos_compatibility(payload: dict, principal: ServicePrincipal):
    try:
        agent_request = AgentRequest.model_validate(payload)
    except PayloadValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_AGENT_REQUEST"}) from exc
    return await _execute_northbound_run(agent_request, principal.user_id, principal.tenant_id)


def _require_owned_conversation(conversation_id: int, principal: ServicePrincipal) -> None:
    from infrastructure.rdb.conversation_state import conversation_belongs_to

    if not conversation_belongs_to(conversation_id, user_id=principal.user_id, tenant_id=principal.tenant_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


async def stop_agentos_compatibility(conversation_id: int, principal: ServicePrincipal):
    def stop_owned_conversation():
        _require_owned_conversation(conversation_id, principal)
        return stop_registered_run(conversation_id, principal.user_id)

    return await run_blocking(
        "agentos-stop-conversation", stop_owned_conversation, lane="control-io", owner="runtime",
    )


async def run_agentos_tracked_background(payload: BackgroundRun, principal: ServicePrincipal) -> TrackedBackgroundResult:
    try:
        request = AgentRequest.model_validate(payload.request)
    except PayloadValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_AGENT_REQUEST"}) from exc
    conversation_id = request.conversation_id
    if type(conversation_id) is not int or conversation_id <= 0 or request.is_debug:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_AGENT_REQUEST"})

    await run_blocking(
        "agentos-background-ownership", _require_owned_conversation,
        conversation_id, principal, lane="control-io", owner="runtime",
    )
    request.enable_automation_tool = False
    request._track_execution = True
    request._projection_run_id = payload.run_id
    request._message_source = "AUTOMATION"

    async def read_state(**options):
        return await run_blocking(
            "agentos-background-state", read_execution, payload.run_id, principal.user_id, principal.tenant_id,
            conversation_id, lane="control-io", owner="runtime", **options,
        )

    producer = None
    try:
        if await read_state() is not None:
            raise ActiveExecutionError
        response = await run_agent_stream(
            agent_request=request, http_request=None, user_id=principal.user_id, tenant_id=principal.tenant_id,
            skip_user_save=True,
        )
        if response.headers.get("X-Stream-Status") == "conflict":
            raise ActiveExecutionError
        producer = getattr(response, "agentos_producer", None)
        chunks = 0
        async for _ in response.body_iterator:
            chunks += 1
        if producer is not None:
            try:
                await asyncio.shield(producer)
            except asyncio.CancelledError:
                if not producer.cancelled() or asyncio.current_task().cancelling():
                    raise
        state = await read_state()
    except asyncio.CancelledError:
        try:
            await read_state(request_stop=True, prevent_start=True)
        except (PermissionError, SQLAlchemyError, RuntimeError):
            if producer is not None:
                producer.cancel()
            logger.warning("Could not persist background disconnect cancellation for run_id=%s", payload.run_id)
        raise
    except ActiveExecutionError as exc:
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_RUN_ALREADY_ACTIVE"}) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"}) from exc
    except (RuntimeCapacityExceededError, RuntimeQueueTimeoutError) as exc:
        return _runtime_overload_response(exc)

    if state is None or state["status"] != "completed":
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_BACKGROUND_NOT_COMPLETED"})
    return TrackedBackgroundResult(
        run_id=payload.run_id, conversation_id=conversation_id,
        assistant_message_id=state["assistant_message_id"], chunks=chunks,
    )


async def _execute_northbound_run(agent_request: AgentRequest, user_id: str, tenant_id: str):
    agent_request._track_execution = not agent_request.is_debug and (agent_request.conversation_id or 0) > 0
    try:
        return await run_agent_stream(
            agent_request=agent_request,
            http_request=None,
            user_id=user_id,
            tenant_id=tenant_id,
            skip_user_save=True,
        )
    except ActiveExecutionError:
        return _execution_conflict_response()
    except UnauthorizedError as exc:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail=str(exc),
        ) from exc
    except RunModelControlsError as exc:
        status = {"model_not_available": 404, "model_unavailable": 409, "model_type_invalid": 400}.get(exc.code, 422)
        raise HTTPException(status_code=status, detail={"code": exc.code}) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except (RuntimeCapacityExceededError, RuntimeQueueTimeoutError) as exc:
        return _runtime_overload_response(exc)
    except AppException:
        raise
    except Exception as exc:
        logger.error("Northbound agent run error: %s", exc)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Agent run error.",
        ) from exc


@agent_runtime_router.get("/stop/{run_id}")
async def agent_stop_api(run_id: str):
    """Stop a run owned by the signed Gateway session."""
    principal = _gateway_session_principal()
    if run_id.isdecimal():
        return await stop_agentos_compatibility(int(run_id), principal)
    return await stop_agentos_debug(run_id, principal)


@agent_runtime_router.post(
    "/internal/northbound/stop/{conversation_id}",
    include_in_schema=False,
)
async def northbound_agent_stop_api(
    conversation_id: int,
    authorization: Optional[str] = Header(None),
):
    """Stop a northbound agent run inside the runtime service."""
    try:
        user_id, tenant_id = verify_internal_runtime_jwt(authorization)
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    return await stop_agentos_compatibility(conversation_id, ServicePrincipal(user_id, tenant_id))
