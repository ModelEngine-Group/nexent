"""Authenticated management operations for login-gated Agent share links."""

import secrets
from typing import Any, Dict, Optional
from uuid import uuid4

from consts.const import SUPABASE_JWT_SECRET
from database.agent_share_db import (
    create_agent_share,
    get_active_agent_share,
    get_agent_share_by_public_id,
    get_agent_share_session,
    get_or_create_agent_share_session,
    revoke_agent_share,
    rotate_agent_share as rotate_agent_share_record,
)
from database.agent_db import search_agent_info_by_agent_id
from database.agent_version_db import query_current_version_no
from services.agent_draft_permission_service import AgentDraftEditError, require_agent_draft_edit
from services.conversation_management_service import get_conversation_history_service
from services.agent_share_token_service import AgentShareTokenPayload, build_agent_share_token, parse_agent_share_token


class AgentShareError(ValueError):
    """Stable validation and authorization error for share-link management."""


def _require_share_signing_secret() -> str:
    """Use the established auth root with an Agent-share token domain separator."""
    if not SUPABASE_JWT_SECRET:
        raise AgentShareError("agent_share_unavailable")
    return SUPABASE_JWT_SECRET


def _require_manageable_published_agent(*, agent_id: int, tenant_id: str, user_id: str) -> int:
    try:
        require_agent_draft_edit(agent_id=agent_id, tenant_id=tenant_id, user_id=user_id)
    except AgentDraftEditError as exc:
        raise AgentShareError(exc.code) from exc
    version_no = query_current_version_no(agent_id=agent_id, tenant_id=tenant_id)
    if not version_no:
        raise AgentShareError("agent_not_published")
    return version_no


def _serialize_share(share: Dict[str, Any], *, agent_id: int, secret: str) -> Dict[str, Any]:
    token = build_agent_share_token(
        public_share_id=share["public_share_id"],
        generation=int(share["token_generation"]),
        nonce=share["token_nonce"],
        secret=secret,
    )
    return {
        "agent_id": agent_id,
        "share_token": token,
        "generation": int(share["token_generation"]),
        "status": share["status"],
    }


def get_agent_share_link(*, agent_id: int, tenant_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Return the active link only after editable ownership and publish checks."""
    secret = _require_share_signing_secret()
    _require_manageable_published_agent(agent_id=agent_id, tenant_id=tenant_id, user_id=user_id)
    share = get_active_agent_share(tenant_id, agent_id)
    return None if share is None else _serialize_share(share, agent_id=agent_id, secret=secret)


def enable_agent_share(*, agent_id: int, tenant_id: str, user_id: str) -> Dict[str, Any]:
    """Create an active share, or return the one already enabled for this Agent."""
    secret = _require_share_signing_secret()
    _require_manageable_published_agent(agent_id=agent_id, tenant_id=tenant_id, user_id=user_id)
    share = get_active_agent_share(tenant_id, agent_id)
    if share is None:
        share = create_agent_share(
            {
                "public_share_id": str(uuid4()),
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "owner_user_id": user_id,
                "token_generation": 1,
                "token_nonce": secrets.token_urlsafe(32),
            },
            manager_user_id=user_id,
        )
    return _serialize_share(share, agent_id=agent_id, secret=secret)


def rotate_agent_share_link(*, agent_id: int, tenant_id: str, user_id: str) -> Dict[str, Any]:
    """Rotate the independent share token while retaining its opaque public id."""
    secret = _require_share_signing_secret()
    _require_manageable_published_agent(agent_id=agent_id, tenant_id=tenant_id, user_id=user_id)
    share = get_active_agent_share(tenant_id, agent_id)
    if share is None:
        raise AgentShareError("agent_share_not_found")

    nonce = secrets.token_urlsafe(32)
    if not rotate_agent_share_record(int(share["agent_share_id"]), manager_user_id=user_id, token_nonce=nonce):
        raise AgentShareError("agent_share_not_found")

    rotated = {**share, "token_generation": int(share["token_generation"]) + 1, "token_nonce": nonce}
    return _serialize_share(rotated, agent_id=agent_id, secret=secret)


def revoke_agent_share_link(*, agent_id: int, tenant_id: str, user_id: str) -> None:
    """Disable the active share link without deleting auditable history."""
    _require_share_signing_secret()
    _require_manageable_published_agent(agent_id=agent_id, tenant_id=tenant_id, user_id=user_id)
    share = get_active_agent_share(tenant_id, agent_id)
    if share is None or not revoke_agent_share(int(share["agent_share_id"]), manager_user_id=user_id):
        raise AgentShareError("agent_share_not_found")


def resolve_agent_share_context(token: str) -> Dict[str, Any]:
    """Validate an active share link without reading or creating visitor state."""
    secret = _require_share_signing_secret()
    public_share_id = token.split(".", maxsplit=1)[0]
    share = get_agent_share_by_public_id(public_share_id)
    if share is None:
        raise AgentShareError("agent_share_not_found")
    payload = parse_agent_share_token(token, nonce=share["token_nonce"], secret=secret)
    if payload is None or payload.public_share_id != share["public_share_id"]:
        raise AgentShareError("agent_share_invalid_token")
    if payload.generation != int(share["token_generation"]):
        raise AgentShareError("agent_share_invalid_token")

    try:
        require_agent_draft_edit(
            agent_id=int(share["agent_id"]),
            tenant_id=share["tenant_id"],
            user_id=share["owner_user_id"],
        )
    except AgentDraftEditError as exc:
        raise AgentShareError("agent_share_unavailable") from exc
    version_no = query_current_version_no(agent_id=int(share["agent_id"]), tenant_id=share["tenant_id"])
    if not version_no:
        raise AgentShareError("agent_share_unavailable")

    return {
        "agent_share_id": int(share["agent_share_id"]),
        "agent_id": int(share["agent_id"]),
        "agent_version_no": int(version_no),
        "owner_user_id": str(share["owner_user_id"]),
        "tenant_id": str(share["tenant_id"]),
    }


def get_agent_share_metadata(token: str, *, visitor_user_id: str) -> Dict[str, Any]:
    """Return the small public display projection for an authenticated visitor."""
    context = resolve_agent_share_context(token)
    try:
        agent = search_agent_info_by_agent_id(
            agent_id=context["agent_id"],
            tenant_id=context["tenant_id"],
            version_no=context["agent_version_no"],
        )
    except ValueError as exc:
        raise AgentShareError("agent_share_unavailable") from exc
    session = get_agent_share_session(
        agent_share_id=context["agent_share_id"],
        visitor_user_id=visitor_user_id,
    )
    return {
        "display_name": agent.get("display_name") or agent.get("name") or "",
        "description": agent.get("description") or "",
        "icon_url": agent.get("icon_url"),
        "greeting_message": agent.get("greeting_message") or "",
        "session_recoverable": session is not None,
    }


def get_agent_share_history(token: str, *, visitor_user_id: str) -> Dict[str, Any]:
    """Read history through the share/visitor mapping without creating a session."""
    context = resolve_agent_share_context(token)
    session = get_agent_share_session(
        agent_share_id=context["agent_share_id"],
        visitor_user_id=visitor_user_id,
    )
    if session is None:
        return {"history": [], "session_recoverable": False}
    return {
        "history": get_conversation_history_service(
            int(session["conversation_id"]), visitor_user_id
        ),
        "session_recoverable": True,
    }


def resolve_agent_share_session(token: str, *, visitor_user_id: str) -> Dict[str, int]:
    """Create or recover the visitor's isolated, hidden conversation on demand."""
    context = resolve_agent_share_context(token)
    session = get_or_create_agent_share_session(
        agent_share_id=context["agent_share_id"],
        visitor_user_id=visitor_user_id,
        agent_id=context["agent_id"],
        agent_version_no=context["agent_version_no"],
    )
    return {
        "agent_id": context["agent_id"],
        "conversation_id": int(session["conversation_id"]),
        "agent_version_no": int(session["agent_version_no"]),
    }
