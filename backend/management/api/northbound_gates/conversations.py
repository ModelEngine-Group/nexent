# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Northbound gate for conversation deletion (action capability).

Two gates share the one service the internal route uses; both are audit
capabilities, so every attempt — including denied ones — leaves a trail.

Failures are translated by the shared domain-error registry
(``management.utils.domain_errors``): a registered domain exception maps to
its contract status and code, anything else surfaces as a generic 500
without leaking internals. The registry is also wired into the app-level
generic exception handler, so gates that let an exception propagate get the
same three-field body.
"""

from typing import Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from contracts.authentication import AuthenticatedIdentity
from contracts.conversation import BatchDeleteConversationRequest
from management.services.permission.identity.dependency import unified_identity
from management.services.permission.identity.gate_policies import (
    audit_hook,
    audit_outcome,
    northbound_envelope_factory,
)
from management.services.conversation.service import (
    delete_conversation_service,
    delete_conversations_batch_service,
)
from management.utils.domain_errors import domain_error_body
from management.utils.request_context import get_request_id

nb_conversation_router = APIRouter(prefix="/nb/v1/conversations", tags=["northbound-gates"])


def _error_response(exc: Exception, request) -> JSONResponse:
    """Translate a domain exception into the three-field northbound error body.

    Kept as a small local helper (automations.py imports it) so gates can
    translate inline; the status/code mapping itself lives in the shared
    registry, single source of truth for both entry points.
    """
    body = domain_error_body(exc, get_request_id(request))
    if body is not None:
        return JSONResponse(status_code=body["status"], content=body)
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "Internal server error",
            "status": 500,
            "requestId": get_request_id(request),
        },
    )


@nb_conversation_router.delete("/{conversation_id}")
async def nb_delete_conversation(
    conversation_id: int,
    request: Request,
    ctx: AuthenticatedIdentity = Depends(unified_identity),
    envelope: Callable = Depends(northbound_envelope_factory),
    audit: Callable = Depends(audit_hook("conversations.delete")),
):
    """Delete one conversation owned by the calling partner (AC-02/05)."""
    target = {"conversation_id": conversation_id}
    try:
        delete_conversation_service(conversation_id, ctx.user_id)
    except Exception as exc:
        audit(audit_outcome(exc), target)
        return _error_response(exc, request)
    audit("success", target)
    return envelope(True)


@nb_conversation_router.post("/batch-delete")
async def nb_delete_conversations_batch(
    request: BatchDeleteConversationRequest,
    raw_request: Request,
    ctx: AuthenticatedIdentity = Depends(unified_identity),
    envelope: Callable = Depends(northbound_envelope_factory),
    audit: Callable = Depends(audit_hook("conversations.batch_delete")),
):
    """Batch-delete conversations; per-item failures surface in failed_ids."""
    target = {"conversation_ids": list(getattr(request, "conversation_ids", []) or [])}
    try:
        result = delete_conversations_batch_service(request.conversation_ids, ctx.user_id)
    except Exception as exc:
        audit(audit_outcome(exc), target)
        return _error_response(exc, raw_request)
    audit("success", target)
    return envelope(result)
