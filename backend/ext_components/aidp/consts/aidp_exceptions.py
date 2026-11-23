"""Domain exceptions raised by the AIDP permission subsystem.

These map to HTTP status codes in ``aidp_mgmt_app`` so the rest of the
backend can stay consistent with the v7.1 permission model:

* ``AidpKbNotFoundError`` -> 404 (resource not visible to the tenant)
* ``AidpKbPermissionDeniedError`` -> 403 (visible but not permitted)
* ``AidpKbConflictError`` -> 409 (active kb_id collision)
* ``AidpKbSyncError`` -> 502 (AIDP service layer returned an error)
* ``AidpGroupValidationError`` -> 400 (cross-tenant or empty group_ids)
"""
from __future__ import annotations


class AidpKbNotFoundError(Exception):
    """KB does not exist or does not belong to the current tenant. HTTP 404."""

    def __init__(self, kb_id: str, tenant_id: str | None = None) -> None:
        self.kb_id = kb_id
        self.tenant_id = tenant_id
        super().__init__(
            f"AIDP knowledge base {kb_id} not found"
            + (f" in tenant {tenant_id}" if tenant_id else "")
        )


class AidpKbPermissionDeniedError(Exception):
    """KB belongs to the tenant but the user lacks the required permission.

    Maps to HTTP 403. Carries the required level so the caller can include it
    in the response without recomputing the decision.
    """

    def __init__(self, kb_id: str, user_id: str, required: str) -> None:
        self.kb_id = kb_id
        self.user_id = user_id
        self.required = required
        super().__init__(
            f"User {user_id} lacks {required} permission on {kb_id}"
        )


class AidpKbConflictError(Exception):
    """An active permission record already exists for this kbs_id.

    Maps to HTTP 409. Raised when the application-layer pre-check finds an
    existing active row, or when the database unique index trips.
    """

    def __init__(self, kb_id: str, tenant_id: str) -> None:
        self.kb_id = kb_id
        self.tenant_id = tenant_id
        super().__init__(
            f"Knowledge base {kb_id} already exists in tenant {tenant_id}"
        )


class AidpKbSyncError(Exception):
    """AIDP returned an unexpected error for an otherwise valid request.

    Maps to HTTP 502. ``cause`` keeps the original exception for diagnostics.
    """

    def __init__(self, operation: str, kb_id: str | None = None, cause: Exception | None = None) -> None:
        self.operation = operation
        self.kb_id = kb_id
        self.cause = cause
        suffix = f" ({cause})" if cause is not None else ""
        target = f" for {kb_id}" if kb_id else ""
        super().__init__(f"AIDP {operation}{target} failed{suffix}")


class AidpGroupValidationError(Exception):
    """One or more ``group_ids`` do not belong to the current tenant.

    Maps to HTTP 400. ``invalid_ids`` are the offending values so the caller
    can surface them to the API client without re-iterating.
    """

    def __init__(self, invalid_ids: list[int], tenant_id: str) -> None:
        self.invalid_ids = list(invalid_ids)
        self.tenant_id = tenant_id
        super().__init__(
            f"Group ids {self.invalid_ids} are not part of tenant {tenant_id}"
        )


__all__ = [
    "AidpKbNotFoundError",
    "AidpKbPermissionDeniedError",
    "AidpKbConflictError",
    "AidpKbSyncError",
    "AidpGroupValidationError",
]
