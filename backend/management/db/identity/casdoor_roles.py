# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persistence for reconciliation of Casdoor-managed tenant roles."""

from typing import NamedTuple, TypedDict

from sqlalchemy import func, select
from consts import const as settings

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.exceptions import RoleAssignmentConflict
from contracts.roles import normalize_roles
from infrastructure.rdb.client import get_db_session
from management.db.identity.membership import check_admin_removal, lock_tenants
from management.db.identity.roles import write_roles
from management.db.identity.user_tenant import _validate_user_tenant_limit
from management.db.models import UserAccount, UserOAuthAccount, UserTenant

CASDOOR_TENANT_ROLES = ("USER", "DEV", "ADMIN")
ROLE_SNAPSHOT_KEY = "casdoor_assigned_roles"


class CasdoorAssignedRole(TypedDict):
    name: str
    display_name: str


def role_snapshot_scope() -> str:
    return f"{settings.CASDOOR_ENDPOINT}|{settings.CASDOOR_ROLE_SYNC_ORGANIZATION}"


def assigned_roles(metadata: object, subject: str) -> list[CasdoorAssignedRole]:
    snapshot = metadata.get(ROLE_SNAPSHOT_KEY) if isinstance(metadata, dict) else None
    if (isinstance(snapshot, dict) and snapshot.get("subject") == subject
            and snapshot.get("scope") == role_snapshot_scope()):
        roles = snapshot.get("roles")
        if isinstance(roles, list):
            return [
                {"name": role["name"], "display_name": role["display_name"]}
                for role in roles if isinstance(role, dict)
                and isinstance(role.get("name"), str) and isinstance(role.get("display_name"), str)
            ]
    return []


class CasdoorRoleBinding(NamedTuple):
    user_id: str
    tenant_id: str
    role: str
    subject_key: str
    username: str
    initial_role: str | None = None
    sync_role: bool = True


def _bindings(session, *, include_linked: bool = False):
    original_binding = (
        select(func.min(UserOAuthAccount.oauth_account_id))
        .where(UserOAuthAccount.user_id == UserAccount.user_id,
               UserOAuthAccount.provider == "casdoor", UserOAuthAccount.delete_flag == "N")
        .correlate(UserAccount).scalar_subquery()
    )
    membership_count = (
        select(func.count(UserTenant.user_tenant_id))
        .where(UserTenant.user_id == UserAccount.user_id, UserTenant.delete_flag == "N")
        .correlate(UserAccount).scalar_subquery()
    )
    casdoor_registration = UserAccount.source_metadata["auth_provider"].astext == "casdoor"
    primary_role = UserAccount.user_roles[1]
    bindings = (
        session.query(UserAccount.user_id, UserTenant.tenant_id, primary_role,
                      UserOAuthAccount.provider_user_id, UserOAuthAccount.provider_username,
                      UserAccount.source_metadata["casdoor_initial_role"].astext,
                      func.coalesce(casdoor_registration, False))
        .select_from(UserAccount)
        .join(UserTenant, UserTenant.user_id == UserAccount.user_id)
        .join(UserOAuthAccount, UserOAuthAccount.oauth_account_id == original_binding)
        .filter(UserAccount.delete_flag == "N", UserTenant.delete_flag == "N", membership_count == 1,
                UserTenant.tenant_id != ASSET_OWNER_TENANT_ID,
                primary_role.in_(CASDOOR_TENANT_ROLES))
    )
    return bindings if include_linked else bindings.filter(casdoor_registration)


def list_casdoor_role_bindings(*, include_linked: bool = False) -> list[CasdoorRoleBinding]:
    with get_db_session() as session:
        return [CasdoorRoleBinding(*row) for row in _bindings(session, include_linked=include_linked).all()]


def apply_casdoor_role(binding: CasdoorRoleBinding, role: str) -> bool:
    """Update only an eligible identity whose binding, tenant and role still match."""
    if binding.initial_role is not None or role not in CASDOOR_TENANT_ROLES or role == binding.role:
        return False
    with get_db_session() as session:
        lock_tenants(session, [binding.tenant_id])
        current = (_bindings(session).filter(UserAccount.user_id == binding.user_id)
                   .with_for_update(of=UserAccount).one_or_none())
        if current is None or CasdoorRoleBinding(*current) != binding:
            return False
        account = session.query(UserAccount).filter_by(user_id=binding.user_id, delete_flag="N").one()
        old_roles = normalize_roles(account.user_roles)
        new_roles = normalize_roles((set(old_roles) - set(CASDOOR_TENANT_ROLES)) | {role})
        member = {"user_id": binding.user_id, "tenant_id": binding.tenant_id}
        try:
            check_admin_removal(session, member, old_roles, new_roles)
        except RoleAssignmentConflict:
            return False
        if "ADMIN" in new_roles and "ADMIN" not in old_roles:
            _validate_user_tenant_limit(session, binding.tenant_id, "ADMIN", include_user_count=False)
        write_roles(session, member, new_roles, "casdoor-role-sync")
        return True


def clear_initial_casdoor_role(binding: CasdoorRoleBinding) -> None:
    """Finish provisioning only if the original pending assignment is still current."""
    with get_db_session() as session:
        current = (_bindings(session).filter(UserAccount.user_id == binding.user_id)
                   .with_for_update(of=UserAccount).one_or_none())
        if current is not None and CasdoorRoleBinding(*current) == binding:
            account = session.query(UserAccount).filter_by(user_id=binding.user_id, delete_flag="N").one()
            account.source_metadata = {k: v for k, v in account.source_metadata.items() if k != "casdoor_initial_role"}


def store_casdoor_observation(binding: CasdoorRoleBinding, snapshots: dict[str, dict]) -> None:
    """Persist observations only for the active binding and keep newer results."""
    with get_db_session() as session:
        current = (_bindings(session, include_linked=True).filter(UserAccount.user_id == binding.user_id)
                   .with_for_update(of=UserAccount).one_or_none())
        if current is None or CasdoorRoleBinding(*current) != binding:
            return
        account = session.query(UserAccount).filter_by(user_id=binding.user_id, delete_flag="N").one()
        metadata = dict(account.source_metadata or {})
        for key, snapshot in snapshots.items():
            previous = metadata.get(key)
            if (isinstance(previous, dict) and previous.get("scope") == snapshot["scope"]
                    and previous.get("subject") == snapshot["subject"]):
                observed = previous.get("at")
                if type(observed) in (int, float) and observed >= snapshot["at"]:
                    continue
            metadata[key] = snapshot
        if metadata != account.source_metadata:
            account.source_metadata = metadata
