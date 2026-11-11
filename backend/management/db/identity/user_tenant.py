# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
Database operations for user tenant relationship management
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import exists, func, or_, text

from contracts.constants.constants import DEFAULT_TENANT_ID
from contracts.constants.environment import (
    MAX_ADMINS_PER_TENANT,
    MAX_SUPER_ADMIN_COUNT,
    MAX_USERS_PER_TENANT,
)
from contracts.errors.exceptions import RoleAssignmentConflict, TenantResourceLimitError
from contracts.roles import (
    has_any_role,
    normalize_roles,
    primary_role,
    roles_from_record,
)
from management.db.client import get_db_session
from management.db.identity.account import set_account_profile
from management.db.identity.membership import (
    check_admin_removal,
    get_user_tenant_by_user_id,
    lock_tenants,
    locked_members,
)
from management.db.identity.roles import replace_member_roles
from management.db.models import (
    TenantGroupInfo,
    TenantGroupUser,
    UserOAuthAccount,
    UserTenant,
)
from management.utils.orm import as_dict
from permissions.role_assignment import check_managed_target

logger = logging.getLogger(__name__)

_USER_LIMIT = MAX_USERS_PER_TENANT if isinstance(MAX_USERS_PER_TENANT, int) else 10_000
_ADMIN_LIMIT = MAX_ADMINS_PER_TENANT if isinstance(MAX_ADMINS_PER_TENANT, int) else 1_000
_SUPER_ADMIN_LIMIT = MAX_SUPER_ADMIN_COUNT if isinstance(MAX_SUPER_ADMIN_COUNT, int) else 1


def _count_or_zero(value) -> int:
    """Return a database count while keeping lightweight test doubles harmless."""
    return value if isinstance(value, int) else 0


def _lock_resource_limit(session, lock_key: str) -> None:
    """Serialize limit checks for a resource during the current transaction."""
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": lock_key})


def _validate_user_tenant_limit(
    session,
    tenant_id: str,
    user_role: str,
    *,
    include_user_count: bool = True,
) -> None:
    _lock_resource_limit(session, f"tenant-user-limit:{tenant_id}")
    if include_user_count:
        user_count = _count_or_zero(
            session.query(UserTenant)
            .filter(
                getattr(UserTenant, "tenant_id", None) == tenant_id,
                getattr(UserTenant, "delete_flag", None) == "N",
            )
            .count()
        )
        if user_count >= _USER_LIMIT:
            error = TenantResourceLimitError(f"Tenant user limit reached: maximum {_USER_LIMIT} users per tenant")
            error.resource = "users"
            error.scope = "tenant"
            error.limit = _USER_LIMIT
            error.current_count = user_count
            raise error

    normalized_role = normalize_roles(user_role)
    if "ADMIN" in normalized_role:
        _lock_resource_limit(session, f"tenant-admin-limit:{tenant_id}")
        admin_count = _count_or_zero(
            session.query(UserTenant)
            .filter(
                getattr(UserTenant, "tenant_id", None) == tenant_id,
                UserTenant.roles.contains(["ADMIN"]),
                getattr(UserTenant, "delete_flag", None) == "N",
            )
            .count()
        )
        if admin_count >= _ADMIN_LIMIT:
            error = TenantResourceLimitError(
                f"Tenant administrator limit reached: maximum {_ADMIN_LIMIT} administrators per tenant"
            )
            error.resource = "administrators"
            error.scope = "tenant"
            error.limit = _ADMIN_LIMIT
            error.current_count = admin_count
            raise error
    elif "SU" in normalized_role:
        _lock_resource_limit(session, "super-admin-limit")
        super_admin_count = _count_or_zero(
            session.query(UserTenant)
            .filter(
                UserTenant.roles.contains(["SU"]),
                getattr(UserTenant, "delete_flag", None) == "N",
            )
            .count()
        )
        if super_admin_count >= _SUPER_ADMIN_LIMIT:
            error = TenantResourceLimitError(
                f"Super administrator limit reached: maximum {_SUPER_ADMIN_LIMIT} super administrator"
            )
            error.resource = "super_admins"
            error.scope = "platform"
            error.limit = _SUPER_ADMIN_LIMIT
            error.current_count = super_admin_count
            raise error


def get_user_role_by_tenant(user_id: str, tenant_id: str) -> tuple[str, ...]:
    """Return the user's role within the given tenant.

    Joins ``user_tenant_t`` by ``(user_id, tenant_id)`` so the result is
    strictly tenant-scoped. Returns the empty string when no active row
    exists; callers should treat that as "no role".
    """
    if not user_id or not tenant_id:
        return ()
    with get_db_session() as session:
        result = (
            session.query(UserTenant)
            .filter(
                UserTenant.user_id == user_id,
                UserTenant.tenant_id == tenant_id,
                UserTenant.delete_flag == "N",
            )
            .first()
        )
        # Access ORM attributes INSIDE the session context — the session
        # closes on context-manager exit and lazy-loaded attributes are not
        # reachable after that (would raise DetachedInstanceError).
        return roles_from_record(as_dict(result)) if result is not None else ()


def get_user_email_map(user_ids: List[str]) -> Dict[str, str]:
    """Return active user email addresses keyed by user ID."""
    unique_user_ids = list({user_id for user_id in user_ids if user_id})
    if not unique_user_ids:
        return {}

    with get_db_session() as session:
        rows = (
            session.query(UserTenant.user_id, UserTenant.user_email)
            .filter(
                UserTenant.user_id.in_(unique_user_ids),
                UserTenant.delete_flag == "N",
            )
            .all()
        )

    return {user_id: user_email for user_id, user_email in rows if user_email}


def get_all_tenant_ids() -> list[str]:
    """
    Get all unique tenant IDs from the database

    Returns:
        list[str]: List of unique tenant IDs
    """
    with get_db_session() as session:
        result = session.query(UserTenant.tenant_id).filter(UserTenant.delete_flag == "N").distinct().all()

        tenant_ids = [row[0] for row in result]

        # Add default tenant_id if not already in the list
        if DEFAULT_TENANT_ID not in tenant_ids:
            tenant_ids.append(DEFAULT_TENANT_ID)

        return tenant_ids


def insert_user_tenant(
    user_id: str,
    tenant_id: str,
    user_role: str = "USER",
    user_email: str = None,
    created_by: Optional[str] = None,
    db_session=None,
    roles=None,
) -> Dict[str, Any]:
    """
    Insert user tenant relationship

    Args:
        user_id (str): User ID
        tenant_id (str): Tenant ID
        user_role (str): User role (SUPER_ADMIN, ADMIN, DEV, USER)
        user_email (str): User email address
    """
    session_context = get_db_session() if db_session is None else get_db_session(db_session)
    with session_context as session:
        assigned = normalize_roles(roles if roles is not None else user_role)
        _validate_user_tenant_limit(session, tenant_id, assigned)
        user_role = primary_role(assigned, user_role)
        actor = created_by or user_id
        set_account_profile(user_id, user_role, user_email, actor, session, roles=assigned)
        user_tenant = UserTenant(
            user_id=user_id,
            tenant_id=tenant_id,
            created_by=actor,
            updated_by=actor,
        )
        session.add(user_tenant)
        session.flush()
        return as_dict(user_tenant)


def get_user_tenant_in_tenant(user_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Return an active user relationship scoped to a tenant."""
    with get_db_session() as session:
        result = (
            session.query(UserTenant)
            .filter(
                UserTenant.user_id == user_id,
                UserTenant.tenant_id == tenant_id,
                UserTenant.delete_flag == "N",
            )
            .first()
        )
        return as_dict(result) if result else None


def get_user_tenant_by_email(email: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Return an active tenant user matching an email address."""
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return None
    with get_db_session() as session:
        results = (
            session.query(UserTenant)
            .filter(
                UserTenant.tenant_id == tenant_id,
                UserTenant.delete_flag == "N",
                func.lower(UserTenant.user_email) == normalized_email,
            )
            .limit(2)
            .all()
        )
        if len(results) > 1:
            raise ValueError("Multiple active users match the requested email")
        return as_dict(results[0]) if results else None


def upsert_user_tenant(
    user_id: str, tenant_id: str, user_role: str = "USER", user_email: str = None, roles=None
) -> Dict[str, Any]:
    """
    Create or update the active user-tenant relationship for an external identity login.
    """
    assigned = normalize_roles(roles if roles is not None else user_role)
    snapshot = get_user_tenant_by_user_id(user_id)
    with get_db_session() as session:
        lock_tenants(session, [tenant_id] + ([snapshot["tenant_id"]] if snapshot else []))
        result = session.query(UserTenant).filter(UserTenant.user_id == user_id, UserTenant.delete_flag == "N").first()

        if result:
            if snapshot and result.tenant_id != snapshot["tenant_id"]:
                raise RoleAssignmentConflict("Membership changed; reload before retrying")
            old_roles = roles_from_record(as_dict(result))
            check_admin_removal(session, as_dict(result), old_roles,
                                assigned if result.tenant_id == tenant_id else (), None)
            is_new_tenant = result.tenant_id != tenant_id
            promoted_roles = set(assigned) - set(old_roles)
            if is_new_tenant:
                _validate_user_tenant_limit(session, tenant_id, assigned)
            elif has_any_role(promoted_roles, {'ADMIN','SU'}):
                _validate_user_tenant_limit(session, tenant_id, assigned, include_user_count=False)
            result.tenant_id = tenant_id
            result.updated_by = user_id
        else:
            _validate_user_tenant_limit(session, tenant_id, assigned)
            result = UserTenant(
                user_id=user_id,
                tenant_id=tenant_id,
                created_by=user_id,
                updated_by=user_id,
            )
            session.add(result)

        set_account_profile(user_id, primary_role(assigned, user_role), user_email, user_id, session, roles=assigned)
        session.flush()
        session.expire(result)
        return as_dict(result)


def get_users_by_tenant_id(
    tenant_id: str,
    page: Optional[int] = 1,
    page_size: Optional[int] = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    email_required: bool = True,
    search: Optional[str] = None,
    roles: Optional[List[str]] = None,
    group_ids: Optional[List[int]] = None,
    *,
    search_cas_username: bool = False,
) -> Dict[str, Any]:
    """
    Get users belonging to a specific tenant with pagination and sorting

    Args:
        tenant_id (str): Tenant ID
        page (Optional[int]): Page number (1-based). If None, returns all data
        page_size (Optional[int]): Number of items per page. If None, returns all data
        sort_by (str): Field to sort by
        sort_order (str): Sort order (asc or desc)

    Returns:
        Dict[str, Any]: Dictionary containing users list and total count
    """
    with get_db_session() as session:
        filters = [
            UserTenant.tenant_id == tenant_id,
            UserTenant.delete_flag == "N",
        ]
        if email_required:
            filters.extend(
                [
                    UserTenant.user_email.isnot(None),
                    func.trim(UserTenant.user_email) != "",
                ]
            )

        if search and search.strip():
            pattern = f"%{search.strip()}%"
            email_match = UserTenant.user_email.ilike(pattern)
            if search_cas_username:
                cas_match = exists().where(
                    UserOAuthAccount.user_id == UserTenant.user_id,
                    UserOAuthAccount.provider == "cas",
                    UserOAuthAccount.delete_flag == "N",
                    UserOAuthAccount.provider_username.ilike(pattern),
                )
                filters.append(or_(email_match, cas_match))
            else:
                filters.append(email_match)
        if roles:
            role_filters = [role.strip().upper() for role in roles]
            filters.append(UserTenant.roles.overlap(role_filters))
        if group_ids:
            matching_user_ids = (
                session.query(TenantGroupUser.user_id)
                .join(TenantGroupInfo, TenantGroupInfo.group_id == TenantGroupUser.group_id)
                .filter(
                    TenantGroupUser.group_id.in_(group_ids),
                    TenantGroupUser.delete_flag == "N",
                    TenantGroupInfo.tenant_id == tenant_id,
                    TenantGroupInfo.delete_flag == "N",
                )
                .subquery()
            )
            filters.append(UserTenant.user_id.in_(matching_user_ids))

        # Count after all filters, before pagination.
        total_count = session.query(UserTenant).filter(*filters).count()

        # Build base query
        query = session.query(UserTenant).filter(*filters)

        # Add sorting
        if sort_by == "created_at":
            if sort_order == "desc":
                query = query.order_by(UserTenant.create_time.desc())
            else:
                query = query.order_by(UserTenant.create_time.asc())

        # Apply pagination only if both page and page_size are provided
        if page is not None and page_size is not None:
            offset = (page - 1) * page_size
            results = query.offset(offset).limit(page_size).all()
        else:
            # Return all results when pagination is not specified
            results = query.all()

        return {"users": [as_dict(row) for row in results], "total": total_count}


def update_user_tenant_role(user_id: str, role: str, updated_by: str) -> bool:
    """Keep legacy callers inside the same locked assignment policy."""
    target, old, requested = replace_member_roles(updated_by, user_id, role, legacy=True)
    if old != requested:
        logger.info(
            "Role assignment actor=%s target=%s tenant=%s before=%s after=%s",
            updated_by, user_id, target["tenant_id"], old, requested,
        )
    return bool(get_user_tenant_by_user_id(user_id))


def soft_delete_user_tenant_by_user_id(user_id: str, deleted_by: str) -> bool:
    """
    Soft delete user tenant relationship by user ID

    Args:
        user_id (str): User ID to delete
        deleted_by (str): User who performed the deletion

    Returns:
        bool: True if any records were deleted
    """
    snapshot = get_user_tenant_by_user_id(user_id)
    if not snapshot:
        return False
    with get_db_session() as session:
        actor_snapshot = get_user_tenant_by_user_id(deleted_by)
        if not actor_snapshot:
            raise ValueError("Acting user is unavailable")
        lock_tenants(session, [snapshot["tenant_id"], actor_snapshot["tenant_id"]])
        members = locked_members(session, [user_id, deleted_by])
        member = members.get(user_id)
        if not member:
            return False
        if member["tenant_id"] != snapshot["tenant_id"]:
            raise RoleAssignmentConflict("Membership changed; reload before retrying")
        actor = members.get(deleted_by)
        if not actor:
            raise ValueError("Acting user is unavailable")
        if deleted_by != user_id or has_any_role(roles_from_record(member), {"ADMIN", "SU", "ASSET_OWNER"}):
            check_managed_target(actor, member)
        check_admin_removal(session, member, roles_from_record(member), (), deleted_by)
        result = (
            session.query(UserTenant)
            .filter(UserTenant.user_id == user_id, UserTenant.delete_flag == "N")
            .update({"delete_flag": "Y", "updated_by": deleted_by, "update_time": "NOW()"})
        )

        return result > 0


def soft_delete_users_by_tenant_id(tenant_id: str, deleted_by: str) -> bool:
    """
    Soft delete all user tenant relationships for a tenant

    Args:
        tenant_id (str): Tenant ID to delete all users from
        deleted_by (str): User who performed the deletion

    Returns:
        bool: True if any records were deleted
    """
    with get_db_session() as session:
        result = (
            session.query(UserTenant)
            .filter(UserTenant.tenant_id == tenant_id, UserTenant.delete_flag == "N")
            .update({"delete_flag": "Y", "updated_by": deleted_by, "update_time": "NOW()"})
        )

        logger.info(f"Soft deleted {result} user-tenant relationships for tenant {tenant_id}")
        return result > 0
