# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Northbound gate for conversation deletion (action capability).

Two gates share the one service the internal route uses; both are audit
capabilities, so every attempt — including denied ones — leaves a trail.
"""

from http import HTTPStatus
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
    get_request_id,
)
from management.services.conversation.service import (
    delete_conversation_service,
    delete_conversations_batch_service,
)

nb_conversation_router = APIRouter(prefix="/nb/v1/conversations", tags=["northbound-gates"])

# Domain exceptions the three-field error body is defined for (aligned with the
# develop-side gate translation table). Unlisted failures fall back to a
# generic 500 without leaking internals.
_DOMAIN_ERROR_STATUS = {
    "ForbiddenError": (403, "FORBIDDEN"),
    "UnauthorizedError": (401, "UNAUTHORIZED"),
    "NotFoundException": (404, "NOT_FOUND"),
    "AutomationNotFoundError": (404, "AUTOMATION_TASK_NOT_FOUND"),
    "ValidationError": (400, "VALIDATION_ERROR"),
    "TokenExpiredError": (401, "TOKEN_EXPIRED"),
}


def _error_response(exc: Exception, request) -> JSONResponse:
    """Translate a domain exception into the three-field northbound error body."""
    for name, (status, code) in _DOMAIN_ERROR_STATUS.items():
        if any(base.__name__ == name for base in type(exc).__mro__):
            message = str(exc).strip() or code.replace("_", " ").lower()
            return JSONResponse(
                status_code=status,
                content={
                    "code": code,
                    "message": message[:200],
                    "status": status,
                    "requestId": get_request_id(request),
                },
            )
    return JSONResponse(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
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
