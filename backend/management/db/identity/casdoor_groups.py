# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persist Casdoor groups using existing Nexent group and membership IDs."""

from management.db.identity.group import add_group
from management.db.identity.models import TenantGroupInfo, TenantGroupUser, UserOAuthAccount, UserTenant
from management.db.models import UserAccount

_ACTOR = "casdoor-group-sync"


def has_tenant_members(session, tenant_id: str) -> bool:
    return session.query(UserTenant.user_id).filter_by(tenant_id=tenant_id, delete_flag="N").first() is not None


def tenant_bindings(session, tenant_id: str) -> list[tuple[str, str]]:
    return session.query(UserOAuthAccount.user_id, UserOAuthAccount.provider_user_id).join(
        UserTenant, UserTenant.user_id == UserOAuthAccount.user_id,
    ).join(UserAccount, UserAccount.user_id == UserOAuthAccount.user_id).filter(
        UserOAuthAccount.provider == "casdoor", UserOAuthAccount.delete_flag == "N",
        UserTenant.tenant_id == tenant_id, UserTenant.delete_flag == "N", UserAccount.delete_flag == "N",
    ).distinct().all()


def mirror_groups(session, tenant_id: str, scope: str, records: dict[str, dict],
                  members: dict[str, set[str]]) -> dict[str, int]:
    """Apply one complete validated directory under the tenant group lock."""
    rows = session.query(TenantGroupInfo).filter_by(tenant_id=tenant_id, delete_flag="N").all()
    by_key = {row.casdoor_group_key: row for row in rows if row.casdoor_scope == scope}
    live_keys = {record["key"] for record in records.values()}
    removed_ids = set()
    for key in by_key.keys() - live_keys:
        row = by_key.pop(key)
        row.delete_flag = "Y"
        row.updated_by = _ACTOR
        removed_ids.add(row.group_id)
    if removed_ids:
        session.flush()
    by_name = {}
    for name, record in records.items():
        key = record["key"]
        row = by_key.pop(key, None)
        if row is None:
            group_id = add_group(tenant_id, record["name"], record["description"], _ACTOR, db_session=session)
            row = session.get(TenantGroupInfo, group_id)
            row.casdoor_scope = scope
            row.casdoor_group_key = key
        by_name[name] = row

    for row in rows:
        if row.parent_group_id in removed_ids:
            row.parent_group_id = None
            row.updated_by = _ACTOR
    for name, record in records.items():
        row = by_name[name]
        parent = by_name.get(record["parent"])
        parent_id = parent.group_id if parent else None
        if (row.group_name, row.group_description, row.parent_group_id) != (
            record["name"], record["description"], parent_id,
        ):
            row.group_name = record["name"]
            row.group_description = record["description"]
            row.parent_group_id = parent_id
            row.updated_by = _ACTOR

    desired = {row.group_id: members.get(name, set()) for name, row in by_name.items()}
    group_ids = set(desired) | removed_ids
    if group_ids:
        existing = session.query(TenantGroupUser).filter(
            TenantGroupUser.group_id.in_(group_ids), TenantGroupUser.delete_flag == "N",
        ).all()
        retained = set()
        for relation in existing:
            pair = (relation.group_id, relation.user_id)
            if relation.user_id not in desired.get(relation.group_id, set()) or pair in retained:
                relation.delete_flag = "Y"
                relation.updated_by = _ACTOR
            else:
                retained.add(pair)
        session.add_all([
            TenantGroupUser(group_id=group_id, user_id=user_id, created_by=_ACTOR, updated_by=_ACTOR)
            for group_id, user_ids in desired.items() for user_id in user_ids
            if (group_id, user_id) not in retained
        ])
    return {name: row.group_id for name, row in by_name.items()}
