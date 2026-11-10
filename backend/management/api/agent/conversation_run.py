# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public conversation streaming facade backed by signed AgentOS calls."""

import re
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request
from starlette.responses import Response

from contracts.agent import AgentRequest
from contracts.agentos import (
    EVENT_ID_PATTERN, IDEMPOTENCY_KEY_PATTERN, RUN_ID_PATTERN, AgentResume, AgentStop, CompatibilityConversationRun,
)
from contracts.errors.exceptions import (
    RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError, UnauthorizedError,
)
from management.services.agent.runtime_client import (
    forward_active_run, forward_conversation_resume, forward_conversation_run, forward_debug_stop, forward_scoped_stop,
)
from management.services.permission.identity.session import get_current_user_id
from management.utils.request_context import get_user_language

router = APIRouter(prefix="/agent")


@router.post("/run")
async def run_conversation(
    agent_request: AgentRequest,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    resume: bool = False,
    run_id: Annotated[str | None, Query(pattern=RUN_ID_PATTERN)] = None,
    after_event_id: Annotated[str | None, Query(pattern=EVENT_ID_PATTERN)] = None,
    idempotency_key: Annotated[str | None, Header(pattern=IDEMPOTENCY_KEY_PATTERN)] = None,
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
    except UnauthorizedError as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc

    if idempotency_key is not None and (resume or agent_request.is_debug):
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_IDEMPOTENCY_REQUEST"})

    try:
        if run_id is not None or after_event_id is not None:
            conversation_id = agent_request.conversation_id
            if not resume or run_id is None or not conversation_id or conversation_id <= 0 or agent_request.is_debug:
                raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_RESUME_REQUEST"})
            cursor = AgentResume(conversation_id=conversation_id, run_id=run_id, after_event_id=after_event_id)
            return await forward_conversation_resume(cursor, user_id, tenant_id)

        timezone = request.headers.get("x-user-timezone")
        payload = CompatibilityConversationRun(
            request=agent_request.model_dump(mode="json", exclude_unset=True),
            resume=resume,
            language=get_user_language(request),
            timezone=timezone if timezone and len(timezone) <= 128 else None,
            idempotency_key=idempotency_key,
        )
        return await forward_conversation_run(payload, user_id, tenant_id)
    except RuntimeServiceTimeoutError as exc:
        raise HTTPException(status_code=504, detail="Runtime service timed out") from exc
    except RuntimeServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Runtime service is unavailable") from exc
    except RuntimeUpstreamError as exc:
        return Response(content=exc.content, status_code=exc.status_code, headers=exc.headers)


@router.get("/stop/{run_id}")
async def stop_conversation(run_id: str, response: Response, authorization: Annotated[str | None, Header()] = None):
    response.headers["Cache-Control"] = "no-store"
    try:
        user_id, tenant_id = get_current_user_id(authorization)
    except UnauthorizedError as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc

    try:
        if re.fullmatch(r"debug-[0-9a-f]{32}", run_id):
            return await forward_debug_stop(run_id, user_id, tenant_id)

        conversation_id = None
        if not re.fullmatch(RUN_ID_PATTERN, run_id):
            if not re.fullmatch(r"[0-9]{1,10}", run_id) or not 0 < int(run_id) <= 2147483647:
                raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})
            conversation_id = int(run_id)
            run_id = await forward_active_run(conversation_id, user_id, tenant_id)
            if run_id is None:
                return {"status": "success", "message": "No active run found", "already_stopped": True}

        state = await forward_scoped_stop(AgentStop(run_id=run_id, conversation_id=conversation_id), user_id, tenant_id)
        result = {
            "status": "success",
            "message": "Run cancellation requested" if state.cancellation_requested else "Run has already ended",
            "run_id": state.run_id,
            "run_status": state.status,
            "cancellation_requested": state.cancellation_requested,
        }
        if not state.cancellation_requested:
            result["already_stopped"] = True
        return result
    except RuntimeServiceTimeoutError as exc:
        raise HTTPException(status_code=504, detail="Runtime service timed out") from exc
    except RuntimeServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Runtime service is unavailable") from exc
    except RuntimeUpstreamError as exc:
        return Response(content=exc.content, status_code=exc.status_code, headers=exc.headers)
