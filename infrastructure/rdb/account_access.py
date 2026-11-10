# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant-scoped identity reads shared by service authorization."""

from typing import List

from infrastructure.rdb.account_record import TenantGroupInfo, TenantGroupUser, UserTenant
from infrastructure.rdb.client import get_db_session


def query_group_ids_by_user_in_tenant(user_id: str, tenant_id: str, *, session_factory=get_db_session) -> List[int]:
    """Return ``user_id``'s group IDs restricted to ``tenant_id``.

    Joins ``tenant_group_user_t`` with ``tenant_group_info_t`` so a user that
    happens to share a group ID across tenants cannot leak access. Filters on
    ``delete_flag='N'`` for both tables.
    """
    if not user_id or not tenant_id:
        return []
    with session_factory() as session:
        result = (
            session.query(TenantGroupUser.group_id)
            .join(
                TenantGroupInfo,
                TenantGroupInfo.group_id == TenantGroupUser.group_id,
            )
            .filter(
                TenantGroupUser.user_id == user_id,
                TenantGroupUser.delete_flag == "N",
                TenantGroupInfo.tenant_id == tenant_id,
                TenantGroupInfo.delete_flag == "N",
            )
            .all()
        )
    return [row[0] for row in result]


def filter_tenant_group_ids(group_ids: List[int], tenant_id: str, *, session_factory=get_db_session) -> List[int]:
    """Return the subset of ``group_ids`` that exist in ``tenant_id``.

    Used by the AIDP permission service to validate submitted ``group_ids``
    against the current tenant. Returns an empty list when no IDs match.
    """
    if not group_ids or not tenant_id:
        return []
    with session_factory() as session:
        rows = (
            session.query(TenantGroupInfo.group_id)
            .filter(
                TenantGroupInfo.group_id.in_(group_ids),
                TenantGroupInfo.tenant_id == tenant_id,
                TenantGroupInfo.delete_flag == "N",
            )
            .all()
        )
    return [row[0] for row in rows]


def get_user_role_by_tenant(user_id: str, tenant_id: str, *, session_factory=get_db_session) -> str:
    """Return the user's role within the given tenant.

    Joins ``user_tenant_t`` by ``(user_id, tenant_id)`` so the result is
    strictly tenant-scoped. Returns the empty string when no active row
    exists; callers should treat that as "no role".
    """
    if not user_id or not tenant_id:
        return ""
    with session_factory() as session:
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
        return (result.user_role or "") if result is not None else ""
