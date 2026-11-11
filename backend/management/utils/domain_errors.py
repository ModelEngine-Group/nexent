# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Narrow domain-error registry: one table from a domain exception to HTTP.

Every entry owns a stable ``code``, an HTTP ``status`` and a default message, so
the same failure reads the same way from the internal and the northbound entry.

Governance rules
----------------
- Append-only. Repurposing an existing code breaks a published contract; a new
  meaning needs a new entry and a new code.
- Narrow domain classes only. Registering a bare built-in such as ``ValueError``
  would flatten ``TenantResourceLimitError`` (429) into 400, because several
  domain errors share that base class.
- The most specific registered class wins. Resolution walks the exception MRO,
  so a subclass keeps its own status code even when its base is registered.
- Wording is static unless the exception class owns the message (see
  ``use_exception_message``). Never interpolate ``str(exc)`` of an unexpected
  exception into a response: internal paths and table names must stay in logs.

Changelog
---------
2026-11-06  Initial table for the northbound exposure initiative: rate limit,
            not-found, unauthorized, forbidden, tenant quota, runtime metadata
            conflict, validation and automation lifecycle errors.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Type

from contracts.errors.exceptions import (
    AgentAutomationError,
    AutomationCapabilityBindingInvalidError,
    AutomationCapabilityNotReadyError,
    AutomationCapabilityUnavailableError,
    AutomationConversationAlreadyBoundError,
    AutomationNotFoundError,
    AutomationScheduleInvalidError,
    ForbiddenError,
    LimitExceededError,
    NotFoundException,
    RuntimeMetadataVersionConflict,
    TenantResourceLimitError,
    UnauthorizedError,
    ValidationError,
)

# Longest exception-owned wording copied into a response body. Anything longer
# is treated as unexpected detail and replaced by the static wording.
MAX_MESSAGE_LENGTH = 200


@dataclass(frozen=True)
class DomainErrorSpec:
    """HTTP projection of one domain exception class."""

    status: int
    code: str
    message: str
    use_exception_message: bool = False


DOMAIN_ERROR_SPECS: Dict[Type[BaseException], DomainErrorSpec] = {
    # Rate limiting and quota
    LimitExceededError: DomainErrorSpec(
        429, "RATE_LIMIT_EXCEEDED", "Too many requests", use_exception_message=True
    ),
    TenantResourceLimitError: DomainErrorSpec(
        429, "TENANT_RESOURCE_EXCEEDED", "Tenant resource limit exceeded", use_exception_message=True
    ),
    # Identity and permission
    UnauthorizedError: DomainErrorSpec(
        401, "UNAUTHORIZED", "Authentication is required", use_exception_message=True
    ),
    ForbiddenError: DomainErrorSpec(403, "FORBIDDEN", "Forbidden", use_exception_message=True),
    PermissionError: DomainErrorSpec(403, "FORBIDDEN", "Forbidden"),
    # Resource state
    NotFoundException: DomainErrorSpec(404, "NOT_FOUND", "Resource not found", use_exception_message=True),
    ValidationError: DomainErrorSpec(400, "VALIDATION_ERROR", "Invalid request", use_exception_message=True),
    RuntimeMetadataVersionConflict: DomainErrorSpec(
        409, "CHAT_METADATA_VERSION_CONFLICT", "Runtime metadata version conflict"
    ),
    # Automation lifecycle. Codes reuse the domain ``error_code`` values so the
    # northbound contract stays stable after the hand-written map is removed.
    AutomationNotFoundError: DomainErrorSpec(404, "AUTOMATION_TASK_NOT_FOUND", "Automation task not found"),
    AutomationConversationAlreadyBoundError: DomainErrorSpec(
        409, "AUTOMATION_CONVERSATION_ALREADY_BOUND", "Conversation is already bound to an automation task"
    ),
    AutomationCapabilityNotReadyError: DomainErrorSpec(
        400, "AUTOMATION_CAPABILITY_NOT_READY", "Automation capability is not ready"
    ),
    AutomationCapabilityUnavailableError: DomainErrorSpec(
        400, "AUTOMATION_CAPABILITY_UNAVAILABLE", "Automation capability is unavailable"
    ),
    AutomationCapabilityBindingInvalidError: DomainErrorSpec(
        400, "AUTOMATION_CAPABILITY_BINDING_INVALID", "Automation capability binding is invalid"
    ),
    AutomationScheduleInvalidError: DomainErrorSpec(400, "AUTOMATION_SCHEDULE_INVALID", "Automation schedule is invalid"),
    AgentAutomationError: DomainErrorSpec(400, "AUTOMATION_ERROR", "Automation request failed"),
}


def resolve_domain_error(exc: BaseException) -> Optional[DomainErrorSpec]:
    """Return the most specific registered spec for ``exc``, if any."""
    if not isinstance(exc, BaseException):
        return None
    for error_class in type(exc).__mro__:
        spec = DOMAIN_ERROR_SPECS.get(error_class)
        if spec is not None:
            return spec
    return None


def domain_error_message(exc: BaseException, spec: DomainErrorSpec) -> str:
    """Resolve the client-facing wording for a registered domain exception."""
    if not spec.use_exception_message:
        return spec.message
    text = str(exc).strip()
    if not text or len(text) > MAX_MESSAGE_LENGTH:
        return spec.message
    return text


def domain_error_body(exc: BaseException, request_id: Optional[str] = None) -> Optional[dict]:
    """Build the ``{code, message, status, requestId}`` body, or ``None``."""
    spec = resolve_domain_error(exc)
    if spec is None:
        return None
    return {
        "code": spec.code,
        "message": domain_error_message(exc, spec),
        "status": spec.status,
        "requestId": request_id,
    }


def registered_domain_errors() -> Tuple[Type[BaseException], ...]:
    """Every registered class, for framework handler installation."""
    return tuple(DOMAIN_ERROR_SPECS)
