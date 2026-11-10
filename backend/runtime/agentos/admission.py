# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Claim a signed ordinary conversation submission before starting its execution."""

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse, Response

from contracts.agent import AgentRequest
from contracts.agentos import CompatibilityConversationRun
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.agent_admission import (
    AdmissionRequestConflict, AdmissionScopeError, claim_conversation_run, set_conversation_admission,
)
from infrastructure.rdb.conversation_state import conversation_belongs_to
from nexent.core.concurrency import run_blocking


logger = logging.getLogger(__name__)


def _digest(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


async def _control_io(task, function, *args, **kwargs):
    return await run_blocking(task, function, *args, lane="control-io", owner="runtime", **kwargs)


async def _require_conversation_owner(conversation_id: int, actor: ServicePrincipal) -> None:
    if not await _control_io(
        "agentos-admission-ownership", conversation_belongs_to, conversation_id,
        user_id=actor.user_id, tenant_id=actor.tenant_id,
    ):
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})


async def admit_conversation_run(
    payload: CompatibilityConversationRun,
    request: AgentRequest,
    actor: ServicePrincipal,
    execute: Callable[[], Awaitable[Response]],
) -> Response:
    conversation_id = request.conversation_id
    if payload.resume or request.is_debug or (conversation_id is not None and conversation_id <= 0):
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_IDEMPOTENCY_REQUEST"})
    if conversation_id is not None:
        await _require_conversation_owner(conversation_id, actor)

    scope = _digest(["conversation-admission-v1", actor.tenant_id, actor.user_id, payload.idempotency_key])
    fingerprint = _digest(payload.model_dump(mode="json", exclude={"idempotency_key"}))
    try:
        claim = await _control_io(
            "agentos-claim-conversation", claim_conversation_run, scope, fingerprint, actor.user_id, actor.tenant_id,
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
                await _require_conversation_owner(claim.conversation_id, actor)
            headers["conversation_id"] = str(claim.conversation_id)
        if claim.status == "pending":
            headers["Retry-After"] = "1"
        return JSONResponse(
            {
                "run_id": claim.run_id,
                "status": claim.status,
                "conversation_id": claim.conversation_id,
                "journal_available": claim.journal_available,
            },
            status_code=409 if claim.status == "rejected" else 202, headers=headers,
        )

    request._projection_run_id = claim.run_id
    request._run_admission_scope = scope

    async def reject():
        try:
            await _control_io(
                "agentos-reject-conversation", set_conversation_admission, scope, claim.run_id, actor.user_id,
                actor.tenant_id, conversation_id=None, journal_available=False,
            )
        except (SQLAlchemyError, RuntimeError):
            logger.warning("Could not record rejected AgentOS admission run_id=%s", claim.run_id)

    try:
        response = await execute()
    except HTTPException as exc:
        if exc.status_code < 500:
            await reject()
        exc.headers = {**(exc.headers or {}), **headers}
        raise
    if response.status_code < 500 and (response.status_code >= 400 or "conversation_id" not in response.headers):
        await reject()
    for name, value in headers.items():
        response.headers[name] = value
    return response
