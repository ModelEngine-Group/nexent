# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contracts.authentication import AuthenticatedIdentity
import logging
from nexent.core.concurrency import run_blocking
from http import HTTPStatus
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from starlette.responses import JSONResponse, StreamingResponse
from contracts.constants.environment import ENABLE_AGENT_WORKBENCH
from contracts.agent import AgentRequest, NL2AgentRunRequest
from contracts.errors.exceptions import ForbiddenError, AppException, UnauthorizedError, ValidationError, RuntimeCapacityExceededError, RuntimeQueueTimeoutError, WorkbenchConfigVersionConflict, WorkbenchError
from permissions.depends import require
from permissions.models import CurrentUser
from management.services.agent.service import run_agent_stream, stop_agent_tasks
from contracts.errors.exceptions import AgentDraftEditError
from services.nl2agent_service import Nl2AgentDraftSaveError, create_nl2agent_stream
from contracts.errors.exceptions import RunModelControlsError
from management.services.conversation.creation_history import prepare_creation_history, persist_creation_stream
from gateway.authentication.auth import get_current_user_info, get_current_user_id
from gateway.authentication.auth import verify_internal_runtime_jwt

agent_runtime_router = APIRouter(prefix="/agent")


require_agent_create_permission = require("agent:create")


logger = logging.getLogger("agent_app")


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


@agent_runtime_router.post("/run")
async def agent_run_api(
    agent_request: AgentRequest,
    http_request: Request,
    authorization: str = Header(None),
    resume: bool = Query(False, description="Resume an existing streaming conversation"),
):
    """
    Agent execution API endpoint.
    If resume=true, attempts to continue streaming from where it left off after a tab switch.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        return await run_agent_stream(
            agent_request=agent_request,
            http_request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            resume=resume,
        )
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
    """Run a northbound-prepared agent request inside the runtime service."""
    try:
        user_id, tenant_id = verify_internal_runtime_jwt(authorization)
        return await run_agent_stream(
            agent_request=agent_request,
            http_request=None,
            user_id=user_id,
            tenant_id=tenant_id,
            skip_user_save=True,
        )
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        ) from exc
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


@agent_runtime_router.post("/nl2agent/run")
async def nl2agent_run_api(
    nl2agent_request: NL2AgentRunRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
    _current_user: CurrentUser = Depends(require_agent_create_permission),
):
    """Run NL2Agent; Workbench turns opt into conversation persistence."""
    if (
        nl2agent_request.persist_history or nl2agent_request.workbench_config is not None
    ) and not ENABLE_AGENT_WORKBENCH:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail={"code": "WORKBENCH_DISABLED"})

    try:
        user_id, tenant_id, language = get_current_user_info(
            authorization, http_request
        )
        if nl2agent_request.conversation_id is not None:
            from management.services.conversation.model_preferences import read_model_preferences
            preference_user, _ = get_current_user_id(authorization)
            saved = await run_blocking("creator-model-preferences", read_model_preferences, nl2agent_request.conversation_id, preference_user)
            nl2agent_request.__dict__["_runtime_model_parameter_preferences"] = saved["model_parameter_preferences"]
            if nl2agent_request.model_id is None:
                nl2agent_request.model_id = saved.get("selected_model_id")
        stream = await create_nl2agent_stream(
            request=nl2agent_request,
            tenant_id=tenant_id,
            language=language,
            identity=AuthenticatedIdentity(user_id, tenant_id),
            authorization=authorization,
        )
        if nl2agent_request.persist_history:
            conversation_id, assistant_index = prepare_creation_history(
                conversation_id=nl2agent_request.conversation_id,
                mode="agent_create",
                query=nl2agent_request.query,
                minio_files=nl2agent_request.minio_files,
                workbench_config=nl2agent_request.workbench_config,
                model_parameter_preferences=nl2agent_request.model_parameter_preferences,
                selected_model_id=nl2agent_request.model_id,
                agent_id=nl2agent_request.agent_id,
                user_id=user_id,
                tenant_id=tenant_id,
                retry_user_message_id=nl2agent_request.retry_user_message_id,
                retry_message_index=nl2agent_request.retry_message_index,
            )
            stream = persist_creation_stream(
                stream,
                conversation_id=conversation_id,
                assistant_index=assistant_index,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            return StreamingResponse(
                stream,
                media_type="text/event-stream",
                headers={"conversation_id": str(conversation_id)},
            )
        return StreamingResponse(stream, media_type="text/event-stream")
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except AgentDraftEditError as exc:
        status_code = (
            HTTPStatus.NOT_FOUND
            if exc.code == "agent_not_found"
            else HTTPStatus.FORBIDDEN
            if exc.code in {"agent_deleted", "agent_read_only"}
            else HTTPStatus.BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": "Agent draft cannot be reused."},
        ) from exc
    except RunModelControlsError as exc:
        status = {"model_not_available": 404, "model_unavailable": 409, "model_type_invalid": 400}.get(exc.code, 422)
        raise HTTPException(status_code=status, detail={"code": exc.code}) from exc
    except Nl2AgentDraftSaveError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail={"code": exc.code, "message": "Agent context is invalid."},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Invalid Workbench creation session.",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Agent draft cannot be reused.",
        ) from exc
    except Exception as exc:
        logger.exception("NL2Agent run error")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="NL2Agent run error.",
        ) from exc


@agent_runtime_router.get("/stop/{run_id}")
async def agent_stop_api(run_id: str, authorization: Optional[str] = Header(None)):
    """
    Stop an agent run by conversation ID or ephemeral debug run ID.
    """
    user_id, tenant_id = get_current_user_id(authorization)
    return stop_agent_tasks(int(run_id) if run_id.isdigit() else run_id, user_id)


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
        return stop_agent_tasks(conversation_id, user_id)
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        ) from exc
