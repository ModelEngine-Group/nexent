# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Accept old Runtime public starts as signed Management-owned submissions."""

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import Response

from backend.http.server.agentos_lifecycle import run_until_disconnect
from contracts.agentos import MAX_REQUEST_BYTES, BackgroundRun, CompatibilityConversationRun, ManagementOperation
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError
from management.api.agentos_request import read_agentos_callback
from management.services.agent.background import dispatch_background as execute_background
from management.services.agent.runtime_client import forward_conversation_run

router = APIRouter()
_OPERATION = ManagementOperation.CONVERSATION_DISPATCH


@router.post(_OPERATION.value, include_in_schema=False)
async def dispatch_conversation(request: Request):
    payload, actor = await read_agentos_callback(
        request, _OPERATION, CompatibilityConversationRun, max_bytes=MAX_REQUEST_BYTES,
    )
    if payload.preparation == "legacy":
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_PREPARATION_HANDOFF"})
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
