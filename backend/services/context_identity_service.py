import logging
from typing import Any, Dict, Optional

from nexent.core.agents.agent_model import ContextAuthorizationDecision, ContextIdentity

logger = logging.getLogger("context_identity_service")


def resolve_context_identity(
    *,
    tenant_id: Optional[str],
    user_id: Optional[str],
    conversation_id: Any,
) -> ContextIdentity:
    """Resolve immutable context identity from trusted authenticated request data."""
    return ContextIdentity(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )


def authorize_context_operation(
    *,
    identity: Optional[ContextIdentity],
    operation: str,
    resource: str,
    allowed: bool = True,
    reason_code: Optional[str] = None,
    audit_metadata: Optional[Dict[str, Any]] = None,
) -> ContextAuthorizationDecision:
    """Create a server-issued W4 single-owner authorization decision."""
    metadata = audit_metadata or {}
    if identity is None:
        decision = ContextAuthorizationDecision(
            allowed=False,
            reason_code=reason_code or "identity_not_found",
            operation=operation,
            resource=resource,
            audit_metadata=metadata,
        )
    else:
        decision = ContextAuthorizationDecision(
            allowed=allowed,
            reason_code=reason_code or ("allowed" if allowed else "user_not_authorized"),
            operation=operation,
            resource=resource,
            identity_hash=identity.scoped_hash,
            audit_metadata=metadata,
        )

    if not decision.allowed:
        logger.warning(
            "context_authorization_denied operation=%s resource=%s reason=%s identity_hash=%s metadata=%s",
            decision.operation,
            decision.resource,
            decision.reason_code,
            decision.identity_hash,
            decision.audit_metadata,
        )
    return decision


def require_context_identity(
    *,
    tenant_id: Optional[str],
    user_id: Optional[str],
    conversation_id: Any,
    operation: str,
    resource: str = "conversation",
) -> ContextIdentity:
    """Resolve identity and raise ValueError after recording a denied decision if incomplete."""
    try:
        identity = resolve_context_identity(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
    except Exception as exc:
        authorize_context_operation(
            identity=None,
            operation=operation,
            resource=resource,
            allowed=False,
            reason_code="identity_not_found",
            audit_metadata={"error": type(exc).__name__},
        )
        raise

    authorize_context_operation(
        identity=identity,
        operation=operation,
        resource=resource,
        allowed=True,
    )
    return identity


def authorize_conversation_owner(
    *,
    conversation_id: Any,
    user_id: Optional[str],
    tenant_id: Optional[str],
    operation: str,
    resource: str = "conversation",
) -> Dict[str, Any]:
    """Resolve identity and require that the conversation belongs to that owner."""
    from database.conversation_db import get_conversation

    identity = resolve_context_identity(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    conversation = get_conversation(conversation_id, user_id, tenant_id=tenant_id)
    if not conversation:
        authorize_context_operation(
            identity=identity,
            operation=operation,
            resource=resource,
            allowed=False,
            reason_code="conversation_not_owned",
        )
        raise ValueError(f"Conversation {conversation_id} does not exist or is not accessible")

    authorize_context_operation(
        identity=identity,
        operation=operation,
        resource=resource,
        allowed=True,
    )
    return conversation
