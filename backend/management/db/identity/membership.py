# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Membership reads, transaction locks and active-administrator invariants."""

from typing import Any, Dict, Optional

from sqlalchemy import func, select, text

from contracts.errors.exceptions import RoleAssignmentConflict
from management.db.client import get_db_session
from management.db.models import UserAccount, UserTenant
from management.utils.orm import as_dict


def lock_tenants(session, tenant_ids):
    """Use the same order as member creation and quota checks."""
    for tenant_id in sorted(set(tenant_ids)):
        for kind in ("user", "admin"):
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"tenant-{kind}-limit:{tenant_id}"}
            )


def locked_members(session, user_ids):
    rows = (
        session.execute(
            select(UserTenant)
            .join(UserAccount, UserAccount.user_id == UserTenant.user_id)
            .where(
                UserTenant.user_id.in_(sorted(set(user_ids))),
                UserTenant.delete_flag == "N",
                UserAccount.delete_flag == "N",
            )
            .order_by(UserTenant.user_id)
            .with_for_update(of=(UserTenant, UserAccount))
        )
        .scalars()
        .all()
    )
    return {row.user_id: as_dict(row) for row in rows}


def active_admin_count(session, tenant_id):
    return session.scalar(
        select(func.count())
        .select_from(UserTenant)
        .join(UserAccount, UserAccount.user_id == UserTenant.user_id)
        .where(
            UserTenant.tenant_id == tenant_id,
            UserTenant.delete_flag == "N",
            UserAccount.delete_flag == "N",
            UserAccount.user_roles.contains(["ADMIN"]),
        )
    )


def api_only_account(session, user_id):
    metadata = (
        session.scalar(
            select(UserAccount.source_metadata).where(UserAccount.user_id == user_id, UserAccount.delete_flag == "N")
        )
        or {}
    )
    return bool(metadata.get("api_only"))


def get_user_tenant_by_user_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Return the active membership, including its account compatibility fields."""
    with get_db_session() as session:
        result = session.query(UserTenant).filter(UserTenant.user_id == user_id, UserTenant.delete_flag == "N").first()

        if result:
            return as_dict(result)
        return None


def check_admin_removal(session, target, old, requested, actor_id=None):
    if "ADMIN" in old and "ADMIN" not in requested:
        if actor_id == target["user_id"]:
            raise RoleAssignmentConflict("Cannot remove your own ADMIN role")
        if active_admin_count(session, target["tenant_id"]) <= 1:
            raise RoleAssignmentConflict("Cannot remove the last active tenant administrator")
