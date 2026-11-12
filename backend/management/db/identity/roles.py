# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Atomic role writes with locked authorization and membership invariants."""

from contracts.constants.environment import MAX_ADMINS_PER_TENANT
from contracts.errors.exceptions import (
    ForbiddenError,
    NotFoundException,
    RoleAssignmentConflict,
)
from contracts.roles import normalize_roles, primary_role, roles_from_record
from management.db.client import get_db_session
from management.db.identity.account import set_account_profile
from management.db.identity.membership import (
    active_admin_count,
    api_only_account,
    check_admin_removal,
    get_user_tenant_by_user_id,
    lock_tenants,
    locked_members,
)
from permissions.role_assignment import check_managed_target


def write_roles(session, member, roles, actor):
    """Update the authoritative account array and compatibility value atomically."""
    set_account_profile(
        member["user_id"], primary_role(roles), None, actor, session, roles=roles
    )


def replace_member_roles(actor_id, user_id, values, *, legacy=False):
    requested = normalize_roles(values, ordinary_only=True)
    snapshot = get_user_tenant_by_user_id(user_id)
    actor_snapshot = get_user_tenant_by_user_id(actor_id)
    if not snapshot or not actor_snapshot:
        raise NotFoundException("User not found")
    with get_db_session() as session:
        lock_tenants(session, [snapshot["tenant_id"], actor_snapshot["tenant_id"]])
        members = locked_members(session, [actor_id, user_id])
        actor, target = members.get(actor_id), members.get(user_id)
        if not actor or not target:
            raise NotFoundException("User not found")
        if target["tenant_id"] != snapshot["tenant_id"] or actor["tenant_id"] != actor_snapshot["tenant_id"]:
            raise RoleAssignmentConflict("Membership changed; reload before retrying")
        check_managed_target(actor, target)
        old = roles_from_record(target)
        if legacy and len(old) > 1:
            raise RoleAssignmentConflict("Use roles to update a user with multiple roles")
        if api_only_account(session, user_id) and set(requested) - {"DEV", "USER"}:
            raise ForbiddenError("API-only identities cannot receive administrative or operations roles")
        check_admin_removal(session, target, old, requested, actor_id)
        if (
            "ADMIN" in requested
            and "ADMIN" not in old
            and active_admin_count(session, target["tenant_id"]) >= MAX_ADMINS_PER_TENANT
        ):
            raise RoleAssignmentConflict("Tenant administrator limit reached")
        if old != requested:
            write_roles(session, target, requested, actor_id)
    return target, old, requested
