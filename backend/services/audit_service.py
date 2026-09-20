"""Security audit logging for authentication and account lifecycle events.

Entries go through the standard logging pipeline (logger name ``audit.auth``
propagates to the root logger), so they land in the existing per-category log
files of the serving process (e.g. ``logs/config/nexent_config.log``) without
introducing a new log category. Every entry is a single line prefixed with
``[AUTH_AUDIT]`` for easy grep/filtering::

    [AUTH_AUDIT] event=user_signin result=failure reason=invalid_credentials user_id=- tenant_id=- email=a@b.com ip=1.2.3.4 ua="Mozilla/5.0 ..." session_id=- details=-

Recording is best-effort: ``record_auth_event`` never raises, so an audit
failure can never break the underlying authentication flow. Secrets
(passwords, access keys) must never be passed in; call sites only provide
identifiers and non-sensitive context.
"""

import json
import logging
from typing import Any, Dict, Optional

from fastapi import Request

logger = logging.getLogger("audit.auth")

AUDIT_LOG_PREFIX = "[AUTH_AUDIT]"
USER_AGENT_MAX_LENGTH = 200

AUDIT_RESULT_SUCCESS = "success"
AUDIT_RESULT_FAILURE = "failure"


def get_client_ip(request: Optional[Request]) -> str:
    """Resolve the client IP: first hop of X-Forwarded-For, then X-Real-IP, then peer.

    X-Forwarded-For is attacker-controllable, so the result is a lead for
    investigation, not proof of origin.
    """
    if request is None:
        return ""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        first_hop = forwarded_for.split(",")[0].strip()
        if first_hop:
            return first_hop
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else ""


def _compact(value: Any) -> str:
    """Flatten a value into a whitespace-free string so the entry stays one log line."""
    if value is None:
        return ""
    return "".join(str(value).split())


def format_audit_entry(
    event_type: str,
    result: str,
    reason: str = "",
    user_id: str = "",
    tenant_id: str = "",
    user_email: str = "",
    client_ip: str = "",
    user_agent: str = "",
    session_id: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> str:
    """Render one audit entry as a single log line.

    Atomic fields are whitespace-free; user_agent is quoted (inner quotes
    replaced); details is a whitespace-collapsed JSON blob kept last so a
    parser can treat the rest of the line as its value.
    """
    ua = " ".join(str(user_agent).split()).replace('"', "'")[:USER_AGENT_MAX_LENGTH]
    if details:
        try:
            details_json = " ".join(
                json.dumps(details, ensure_ascii=False, separators=(",", ":"), default=str).split()
            )
        except Exception:
            details_json = "unserializable"
    else:
        details_json = "-"

    parts = [
        f"event={_compact(event_type) or '-'}",
        f"result={_compact(result) or '-'}",
        f"reason={_compact(reason) or '-'}",
        f"user_id={_compact(user_id) or '-'}",
        f"tenant_id={_compact(tenant_id) or '-'}",
        f"email={_compact(user_email) or '-'}",
        f"ip={_compact(client_ip) or '-'}",
        f'ua="{ua}"' if ua else "ua=-",
        f"session_id={_compact(session_id) or '-'}",
        f"details={details_json}",
    ]
    return " ".join(parts)


def record_auth_event(
    event_type: str,
    result: str,
    request: Optional[Request] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    user_email: Optional[str] = None,
    session_id: Optional[str] = None,
    reason: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Record one authentication audit entry. Best-effort: never raises."""
    try:
        entry = format_audit_entry(
            event_type=event_type,
            result=result,
            reason=reason,
            user_id=str(user_id) if user_id else "",
            tenant_id=str(tenant_id) if tenant_id else "",
            user_email=str(user_email) if user_email else "",
            client_ip=get_client_ip(request),
            user_agent=request.headers.get("user-agent", "") if request else "",
            session_id=str(session_id) if session_id else "",
            details=details,
        )
        logger.info("%s %s", AUDIT_LOG_PREFIX, entry)
    except Exception:
        try:
            logger.error("Failed to record auth audit entry, event=%s", event_type)
        except Exception:
            pass
