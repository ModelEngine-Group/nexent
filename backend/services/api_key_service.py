"""Shared business logic for tenant API user and API key management."""

import uuid
from typing import Any, Dict, List, Optional

from consts.exceptions import ForbiddenError, NotFoundException, ValidationError
from database.client import get_db_session
from database.group_db import add_user_to_group, query_groups
from database.token_db import (
    create_token,
    generate_access_key,
    list_active_tokens_by_tenant,
    soft_delete_tokens_by_user,
)
from database.user_tenant_db import (
    get_user_tenant_by_email,
    get_user_tenant_in_tenant,
    insert_user_tenant,
)
from services.group_service import get_tenant_default_group_id


def _require_tenant_admin(actor_tenant_id: str, actor_role: str) -> None:
    if (actor_role or "").upper() not in {"ADMIN", "SU"}:
        raise ForbiddenError("Only administrators can manage API keys")
    if not actor_tenant_id:
        raise ForbiddenError("Tenant context is required")


def _resolve_group(tenant_id: str, group_id: Optional[int]) -> Dict[str, Any]:
    resolved_group_id = group_id or get_tenant_default_group_id(tenant_id)
    if not resolved_group_id:
        raise ValidationError("The tenant does not have a default user group")

    group = query_groups(resolved_group_id)
    if not group or group.get("tenant_id") != tenant_id:
        raise NotFoundException("User group not found in the caller tenant")
    return group


def _resolve_target(
    tenant_id: str, user_id: Optional[str], email: Optional[str]
) -> Dict[str, Any]:
    target = None
    if user_id:
        target = get_user_tenant_in_tenant(user_id.strip(), tenant_id)
        if not target or target.get("tenant_id") != tenant_id:
            raise ForbiddenError(
                "Cannot manage API keys for a user outside the caller tenant"
            )
    elif email:
        target = get_user_tenant_by_email(email, tenant_id)
    else:
        raise ValidationError("Exactly one of user_id or email must be provided")

    if not target:
        raise NotFoundException("Target user not found in the caller tenant")
    return target


def create_api_users_batch(
    *,
    actor_user_id: str,
    actor_tenant_id: str,
    actor_role: str,
    role: str = "USER",
    group_id: Optional[int] = None,
    count: int = 1,
) -> List[Dict[str, Any]]:
    """Create API-only users, group memberships, and keys."""
    _require_tenant_admin(actor_tenant_id, actor_role)
    normalized_role = (role or "USER").upper()
    if normalized_role not in {"DEV", "USER"}:
        raise ValidationError("API user role must be DEV or USER")
    if count < 1 or count > 100:
        raise ValidationError("API user count must be between 1 and 100")

    group = _resolve_group(actor_tenant_id, group_id)
    created: List[Dict[str, Any]] = []
    with get_db_session() as session:
        for _ in range(count):
            user_id = str(uuid.uuid4())
            insert_user_tenant(
                user_id=user_id,
                tenant_id=actor_tenant_id,
                user_role=normalized_role,
                user_email=None,
                created_by=actor_user_id,
                db_session=session,
            )
            add_user_to_group(
                group_id=group["group_id"],
                user_id=user_id,
                created_by=actor_user_id,
            )
            token = create_token(
                generate_access_key(),
                user_id,
                created_by=actor_user_id,
                db_session=session,
            )
            created.append(
                {
                    "user_id": user_id,
                    "role": normalized_role,
                    "group_id": group["group_id"],
                    "group_name": group.get("group_name"),
                    "api_key": token["access_key"],
                }
            )
    return created


def refresh_user_api_key(
    *,
    actor_user_id: str,
    actor_tenant_id: str,
    actor_role: str,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """Revoke all target keys and return one newly-created key."""
    _require_tenant_admin(actor_tenant_id, actor_role)
    target = _resolve_target(actor_tenant_id, user_id, email)

    with get_db_session() as session:
        revoked_count = soft_delete_tokens_by_user(
            target["user_id"], actor_user_id, session
        )
        token = create_token(
            generate_access_key(),
            target["user_id"],
            created_by=actor_user_id,
            db_session=session,
        )

    return {
        "user_id": target["user_id"],
        "email": target.get("user_email"),
        "api_key": token["access_key"],
        "revoked_count": revoked_count,
    }


def revoke_user_api_keys(
    *,
    actor_user_id: str,
    actor_tenant_id: str,
    actor_role: str,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """Soft-delete every active API key for a tenant user."""
    _require_tenant_admin(actor_tenant_id, actor_role)
    target = _resolve_target(actor_tenant_id, user_id, email)
    revoked_count = soft_delete_tokens_by_user(target["user_id"], actor_user_id)
    if revoked_count == 0:
        raise NotFoundException("The target user has no active API key")
    return {
        "user_id": target["user_id"],
        "email": target.get("user_email"),
        "api_key": None,
        "revoked_count": revoked_count,
    }


def list_tenant_api_keys(
    *,
    actor_tenant_id: str,
    actor_role: str,
    tenant_id: str,
    page: int = 1,
    page_size: int = 20,
    sort_order: str = "desc",
) -> Dict[str, Any]:
    """List active API keys after enforcing tenant administrator access."""
    _require_tenant_admin(actor_tenant_id, actor_role)
    if tenant_id != actor_tenant_id:
        raise NotFoundException("Tenant not found")
    return list_active_tokens_by_tenant(tenant_id, page, page_size, sort_order)
