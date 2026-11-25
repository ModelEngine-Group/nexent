# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Route-level policy dependencies for the northbound gates.

``northbound_envelope_factory`` builds the {message, data, requestId} success
envelope; ``audit_hook(capability_id)`` records one security-audit entry for
action capabilities, including denied attempts, fail-open. Usage accounting
is inherited from ``unified_identity`` (API-Key calls, fail-open).
"""

import logging
from typing import Any, Callable, Dict

from fastapi import Depends, Request

from contracts.authentication import AuthenticatedIdentity
from management.services.permission.identity.dependency import unified_identity
from management.utils.envelope import northbound_envelope
from management.utils.request_context import get_request_id

logger = logging.getLogger(__name__)

AUDIT_OUTCOME_SUCCESS = "success"
AUDIT_OUTCOME_DENIED = "denied"


def northbound_envelope_factory(request: Request) -> Callable[[Any], Dict[str, Any]]:
    """Envelope callable bound to this request's requestId."""

    def envelope(data: Any = None, message: str = "success") -> Dict[str, Any]:
        return northbound_envelope(data, get_request_id(request), message)

    return envelope


def audit_hook(capability_id: str):
    """Audit dependency for one action capability.

    Returns a recorder the handler calls with the outcome after the
    business run, so denied attempts (401/403) leave a trail even though
    the business never executed. Fail-open.
    """

    async def audit_recorder(
        request: Request,
        ctx: AuthenticatedIdentity = Depends(unified_identity),
    ) -> Callable[[str, Dict[str, Any]], None]:
        from management.services.monitor.audit import record_security_event

        def record(outcome: str, target: Dict[str, Any] | None = None) -> None:
            try:
                record_security_event(
                    f"northbound_{capability_id.replace('.', '_')}",
                    request=request,
                    user_id=ctx.user_id,
                    tenant_id=ctx.tenant_id,
                    details={
                        "capability": capability_id,
                        "token_id": ctx.token_id,
                        "target": target or {},
                        "outcome": outcome,
                        "request_id": get_request_id(request),
                    },
                    result=outcome,
                )
            except Exception:
                logger.warning("Audit event failed for capability %s", capability_id)

        return record

    return audit_recorder


def audit_outcome(exc: BaseException) -> str:
    """Classify a business failure into an audit outcome."""
    from contracts.errors.exceptions import ForbiddenError, UnauthorizedError

    if isinstance(exc, (UnauthorizedError, ForbiddenError, PermissionError)):
        return AUDIT_OUTCOME_DENIED
    return "failed"
