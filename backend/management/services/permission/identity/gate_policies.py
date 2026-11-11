# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Route-level policy dependencies for the northbound gates.

Two symmetric helpers, one per cross-cutting concern of the exposure design:

* ``get_envelope`` — the two-state success envelope, injected as a dependency
  and resolved from the request path so the same handler shape serves both
  entrypoints with each one's published contract (§5.4).
* ``audit_hook(capability_id)`` — records one security-audit entry for action
  capabilities, including denied attempts, before any business work runs.
  Best effort: an audit failure never blocks the request (§5.5).

Usage accounting needs no gate-side declaration: ``unified_identity`` already
accounts every authenticated API-Key call (fail-open), and chat-family routes
keep their in-business accounting via the shared exclusion table — usage is
never double-counted (§5.5).
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
DENIED_STATUS_CODES = frozenset({401, 403})


def northbound_envelope_factory(request: Request) -> Callable[[Any], Dict[str, Any]]:
    """Return the envelope callable bound to this request's correlation id.

    The northbound contract is ``{message, data, requestId}``; ``requestId``
    comes from the request so a partner can correlate an error with the
    server-side log of the same call.
    """

    def envelope(data: Any = None, message: str = "success") -> Dict[str, Any]:
        return northbound_envelope(data, get_request_id(request), message)

    return envelope


def audit_hook(capability_id: str):
    """Build the route-level audit dependency for one action capability.

    The hook runs after authentication and before the business function, so a
    denied attempt (401/403) is recorded even though the business never ran —
    which key probed which resource is the most valuable part of the trail.

    The dependency returns an ``audit_recorder`` callable instead of recording
    immediately: the gate handler passes it to ``record_outcome`` after the
    business call, which stamps success or denied on the same entry. Both the
    attempted write and the outcome write are fail-open.
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
