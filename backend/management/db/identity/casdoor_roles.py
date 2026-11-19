# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persistence for reconciliation of Casdoor-managed tenant roles."""

from typing import NamedTuple

from sqlalchemy import func, select

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from management.db.client import get_db_session
from management.db.identity.user_tenant import _validate_user_tenant_limit, _write_user_tenant_role
from management.db.models import UserAccount, UserOAuthAccount, UserTenant

CASDOOR_TENANT_ROLES = ("USER", "DEV", "ADMIN")


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
    bindings = (
        session.query(UserAccount.user_id, UserTenant.tenant_id, UserAccount.user_role,
                      UserOAuthAccount.provider_user_id, UserOAuthAccount.provider_username,
                      UserAccount.source_metadata["casdoor_initial_role"].astext,
                      func.coalesce(casdoor_registration, False))
        .select_from(UserAccount)
        .join(UserTenant, UserTenant.user_id == UserAccount.user_id)
        .join(UserOAuthAccount, UserOAuthAccount.oauth_account_id == original_binding)
        .filter(UserAccount.delete_flag == "N", UserTenant.delete_flag == "N", membership_count == 1,
                UserTenant.tenant_id != ASSET_OWNER_TENANT_ID,
                UserAccount.user_role.in_(CASDOOR_TENANT_ROLES))
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
        if role == "ADMIN":
            _validate_user_tenant_limit(session, binding.tenant_id, role, include_user_count=False)
        current = (_bindings(session).filter(UserAccount.user_id == binding.user_id)
                   .with_for_update(of=UserAccount).one_or_none())
        if current is None or CasdoorRoleBinding(*current) != binding:
            return False
        return _write_user_tenant_role(session, binding.user_id, role, "casdoor-role-sync")


def clear_initial_casdoor_role(binding: CasdoorRoleBinding) -> None:
    """Finish provisioning only if the original pending assignment is still current."""
    with get_db_session() as session:
        current = (_bindings(session).filter(UserAccount.user_id == binding.user_id)
                   .with_for_update(of=UserAccount).one_or_none())
        if current is not None and CasdoorRoleBinding(*current) == binding:
            account = session.query(UserAccount).filter_by(user_id=binding.user_id, delete_flag="N").one()
            account.source_metadata = {k: v for k, v in account.source_metadata.items() if k != "casdoor_initial_role"}


def store_feature_grants(binding: CasdoorRoleBinding, snapshot: dict) -> None:
    """Persist only decisions that still belong to the verified active binding."""
    from permissions.casdoor_policy import SNAPSHOT_KEY

    with get_db_session() as session:
        current = (_bindings(session, include_linked=True).filter(UserAccount.user_id == binding.user_id)
                   .with_for_update(of=UserAccount).one_or_none())
        if current is None or CasdoorRoleBinding(*current) != binding:
            return
        account = session.query(UserAccount).filter_by(user_id=binding.user_id, delete_flag="N").one()
        previous = account.source_metadata.get(SNAPSHOT_KEY)
        if (isinstance(previous, dict) and previous.get("scope") == snapshot["scope"]
                and previous.get("subject") == snapshot["subject"]):
            observed = previous.get("at")
            if type(observed) in (int, float) and observed >= snapshot["at"]:
                return
        account.source_metadata = {**account.source_metadata, SNAPSHOT_KEY: snapshot}
