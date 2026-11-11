# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own the public conversation submission claim before contacting Runtime."""

from collections.abc import Awaitable, Callable

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse, Response

from contracts.agent import AgentRequest
from contracts.agentos import CompatibilityConversationRun
from infrastructure.rdb.agent_admission import (
    AdmissionRequestConflict, AdmissionScopeError, authorize_conversation_dispatch, claim_conversation_run, conversation_claim_scope,
    conversation_request_fingerprint,
)
from infrastructure.rdb.conversation_state import conversation_belongs_to
from nexent.core.concurrency import run_blocking


async def _control_io(task, function, *args, **kwargs):
    return await run_blocking(task, function, *args, lane="control-io", owner="management", **kwargs)


async def _require_owner(conversation_id: int, user_id: str, tenant_id: str) -> None:
    if not await _control_io(
        "conversation-claim-owner", conversation_belongs_to, conversation_id, user_id=user_id, tenant_id=tenant_id,
    ):
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})


async def submit_conversation(
    payload: CompatibilityConversationRun,
    user_id: str,
    tenant_id: str,
    dispatch: Callable[[CompatibilityConversationRun, str, str], Awaitable[Response]],
    *,
    include_claim_headers: bool = True,
) -> Response:
    request = AgentRequest.model_validate(payload.request)
    conversation_id = request.conversation_id
    if payload.idempotency_key is None or payload.resume or request.is_debug or (
        conversation_id is not None and conversation_id <= 0
    ):
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_IDEMPOTENCY_REQUEST"})
    if conversation_id is not None:
        await _require_owner(conversation_id, user_id, tenant_id)

    scope = conversation_claim_scope(user_id, tenant_id, payload.idempotency_key)
    fingerprint = conversation_request_fingerprint(
        payload.model_dump(mode="json", exclude={"idempotency_key", "claimed_run_id"}),
    )
    if payload.claimed_run_id is not None:
        try:
            authorized = await _control_io(
                "conversation-handoff-scope", authorize_conversation_dispatch,
                scope, fingerprint, payload.claimed_run_id, user_id, tenant_id, consume=False,
            )
        except (SQLAlchemyError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail={"code": "AGENTOS_ADMISSION_UNAVAILABLE"}) from exc
        if not authorized:
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_ADMISSION_NOT_PENDING"})
        headers = ({"X-AgentOS-Run-ID": payload.claimed_run_id, "Cache-Control": "no-store"}
                   if include_claim_headers else {})
        try:
            response = await dispatch(payload, user_id, tenant_id)
        except HTTPException as exc:
            exc.headers = {**(exc.headers or {}), **headers}
            raise
        response.headers.update(headers)
        return response
    try:
        claim = await _control_io(
            "conversation-claim", claim_conversation_run, scope, fingerprint, user_id, tenant_id,
        )
    except AdmissionScopeError as exc:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"}) from exc
    except AdmissionRequestConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_IDEMPOTENCY_CONFLICT"}) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_ADMISSION_UNAVAILABLE"}) from exc

    headers = {"X-AgentOS-Run-ID": claim.run_id, "Cache-Control": "no-store"}
    if not claim.acquired:
        if claim.conversation_id is not None:
            if claim.conversation_id != conversation_id:
                await _require_owner(claim.conversation_id, user_id, tenant_id)
            headers["conversation_id"] = str(claim.conversation_id)
        if claim.status == "pending":
            headers["Retry-After"] = "1"
        return JSONResponse({
            "run_id": claim.run_id,
            "status": claim.status,
            "conversation_id": claim.conversation_id,
            "journal_available": claim.journal_available,
        }, status_code=409 if claim.status == "rejected" else 202, headers=headers)

    # Compatibility Runtime binds the conversation and journal before writing headers.
    # A transport failure leaves the claim intact so retry cannot dispatch again.
    response = await dispatch(payload.model_copy(update={"claimed_run_id": claim.run_id}), user_id, tenant_id)
    if include_claim_headers:
        response.headers.update(headers)
    return response
