"""Discovery, lifecycle, and retention policy for durable NL2AGENT sessions."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from agents.nl2agent_session_catalog import delete_nl2agent_session_catalogs
from consts.const import (
    NL2AGENT_ABANDONED_RETENTION_DAYS,
    NL2AGENT_CLEANUP_BATCH_SIZE,
)
from consts.exceptions import Nl2AgentDraftNotFoundError, Nl2AgentValidationError
from database.nl2agent_session_db import (
    NL2AGENT_SESSION_ABANDONED,
    cleanup_abandoned_nl2agent_sessions,
    get_nl2agent_session,
    get_nl2agent_session_by_conversation,
    list_nl2agent_sessions,
    update_nl2agent_session_status,
)

logger = logging.getLogger(__name__)


def _positive_identifier(value: int, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise Nl2AgentValidationError(f"{field_name} must be a positive integer.")
    return value


def _public_session(record: Dict[str, Any]) -> Dict[str, Any]:
    """Project a database row without exposing workflow or catalog payloads."""
    return {
        "draft_agent_id": int(record["draft_agent_id"]),
        "conversation_id": int(record["conversation_id"]),
        "status": str(record["status"]),
        "create_time": record.get("create_time"),
        "update_time": record.get("update_time"),
    }


def resolve_active_session(
    *, conversation_id: int, tenant_id: str, user_id: str
) -> Dict[str, Any]:
    """Resolve one active session by conversation with owner isolation."""
    conversation_id = _positive_identifier(conversation_id, "conversation_id")
    record = get_nl2agent_session_by_conversation(
        tenant_id,
        user_id,
        conversation_id,
    )
    if record is None:
        raise Nl2AgentDraftNotFoundError()
    return _public_session(record)


def list_active_sessions(
    *, tenant_id: str, user_id: str, limit: int = 50
) -> List[Dict[str, Any]]:
    """List the current user's recent active sessions."""
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise Nl2AgentValidationError("limit must be an integer.")
    return [
        _public_session(record)
        for record in list_nl2agent_sessions(
            tenant_id,
            user_id,
            limit=max(1, min(100, limit)),
        )
    ]


def abandon_session(
    *, draft_agent_id: int, tenant_id: str, user_id: str
) -> Dict[str, Any]:
    """Move an owned active session to abandoned and evict its cache."""
    draft_agent_id = _positive_identifier(draft_agent_id, "draft_agent_id")
    record = get_nl2agent_session(
        tenant_id,
        draft_agent_id,
        user_id=user_id,
    )
    if record is None or record.get("status") != "active":
        raise Nl2AgentDraftNotFoundError()
    return _abandon_record(record, tenant_id=tenant_id, user_id=user_id)


def abandon_session_by_conversation(
    *, conversation_id: int, tenant_id: str, user_id: str
) -> Dict[str, Any] | None:
    """Abandon an owned active builder session before deleting its Conversation."""
    conversation_id = _positive_identifier(conversation_id, "conversation_id")
    record = get_nl2agent_session_by_conversation(
        tenant_id,
        user_id,
        conversation_id,
    )
    if record is None:
        return None
    return _abandon_record(record, tenant_id=tenant_id, user_id=user_id)


def _abandon_record(
    record: Dict[str, Any], *, tenant_id: str, user_id: str
) -> Dict[str, Any]:
    """Apply the shared active-to-abandoned transition and cache eviction."""
    draft_agent_id = int(record["draft_agent_id"])
    changed = update_nl2agent_session_status(
        tenant_id=tenant_id,
        draft_agent_id=draft_agent_id,
        status=NL2AGENT_SESSION_ABANDONED,
        user_id=user_id,
    )
    if not changed:
        raise Nl2AgentDraftNotFoundError()
    try:
        delete_nl2agent_session_catalogs(tenant_id, draft_agent_id)
    except Exception:
        logger.warning(
            "Failed to evict abandoned NL2AGENT session cache: "
            "tenant_id=%s draft_agent_id=%s",
            tenant_id,
            draft_agent_id,
            exc_info=True,
        )
    return {
        **_public_session(record),
        "status": NL2AGENT_SESSION_ABANDONED,
    }


def cleanup_expired_abandoned_sessions(*, now: datetime | None = None) -> int:
    """Clean one bounded retention batch; safe to invoke opportunistically."""
    reference_time = now or datetime.now()
    return cleanup_abandoned_nl2agent_sessions(
        abandoned_before=reference_time
        - timedelta(days=NL2AGENT_ABANDONED_RETENTION_DAYS),
        limit=NL2AGENT_CLEANUP_BATCH_SIZE,
    )
