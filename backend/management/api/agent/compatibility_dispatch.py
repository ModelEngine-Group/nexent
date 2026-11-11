# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Accept old Runtime public starts as signed Management-owned submissions."""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError as PayloadValidationError
from starlette.responses import Response

from backend.http.server.agentos_lifecycle import run_until_disconnect
from contracts.agentos import MAX_REQUEST_BYTES, BackgroundRun, CompatibilityConversationRun, ManagementOperation
from contracts.errors.exceptions import (
    AppException, ForbiddenError, RunModelControlsError, RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError, RuntimeUpstreamError, UnauthorizedError, ValidationError,
)
from management.api.agentos_request import read_agentos_callback
from management.services.agent.background import dispatch_background as execute_background
from management.services.agent.runtime_client import forward_conversation_run
from management.services.agent.raw_execution import forward_raw_run

router = APIRouter()
_OPERATION = ManagementOperation.CONVERSATION_DISPATCH
logger = logging.getLogger(__name__)


@router.post(_OPERATION.value, include_in_schema=False)
async def dispatch_conversation(request: Request):
    payload, actor = await read_agentos_callback(
        request, _OPERATION, CompatibilityConversationRun, max_bytes=MAX_REQUEST_BYTES,
    )
    if payload.preparation == "legacy":
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_PREPARATION_HANDOFF"})
    if payload.invocation == "northbound":
        if payload.resume or payload.idempotency_key is not None or payload.claimed_run_id is not None or payload.user_message != "new":
            raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_RAW_HANDOFF"})
        try:
            return await forward_raw_run(payload, actor)
        except PayloadValidationError as exc:
            raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_AGENT_REQUEST"}) from exc
        except RunModelControlsError as exc:
            status = {"model_not_available": 404, "model_unavailable": 409, "model_type_invalid": 400}.get(exc.code, 422)
            raise HTTPException(status_code=status, detail={"code": exc.code}) from exc
        except UnauthorizedError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ForbiddenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeUpstreamError as exc:
            return Response(content=exc.content, status_code=exc.status_code, headers=exc.headers)
        except (RuntimeServiceTimeoutError, RuntimeServiceUnavailableError) as exc:
            status = 504 if isinstance(exc, RuntimeServiceTimeoutError) else 503
            raise HTTPException(status_code=status, detail="Runtime service is unavailable") from exc
        except (AppException, HTTPException):
            raise
        except Exception as exc:
            logger.exception("Raw Northbound AgentOS preparation failed")
            raise HTTPException(status_code=500, detail="Agent run error.") from exc
    return await forward_conversation_run(payload, actor.user_id, actor.tenant_id)


@router.post(ManagementOperation.BACKGROUND_DISPATCH.value, include_in_schema=False)
async def dispatch_background(request: Request):
    payload, actor = await read_agentos_callback(
        request, ManagementOperation.BACKGROUND_DISPATCH, BackgroundRun, max_bytes=MAX_REQUEST_BYTES,
    )
    if payload.preparation == "legacy":
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_PREPARATION_HANDOFF"})
    try:
        result = await run_until_disconnect(request, execute_background(payload, actor))
        return result.model_dump() if hasattr(result, "model_dump") else result
    except RuntimeUpstreamError as exc:
        return Response(content=exc.content, status_code=exc.status_code, headers=exc.headers)
    except RuntimeServiceTimeoutError as exc:
        raise HTTPException(status_code=504, detail="Runtime service timed out") from exc
    except RuntimeServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Runtime service is unavailable") from exc
