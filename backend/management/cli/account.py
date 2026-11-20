# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local super-administrator bootstrap."""

import argparse
import json
import sys
import uuid

from contracts.errors.exceptions import AccountConflictError
from infrastructure.system_configuration.runtime import load_system_configuration


def _resolve_or_create_default_tenant(session) -> str:
    """Find an active tenant or provision a default one for the bootstrap SU.

    The bootstrap CLI runs before any tenant has been created, so we cannot
    leave the SU membership with an empty tenant_id. Every downstream API
    (monitoring, model list, agent list, ...) scopes data by tenant_id and
    would silently return empty results when tenant_id is an empty string.

    Returns the tenant_id (UUID string) to bind the SU to.
    """
    from contracts.constants.constants import (
        ASSET_OWNER_TENANT_ID,
        DEFAULT_GROUP_ID,
        DEFAULT_TENANT_ID,
        TENANT_ID,
        TENANT_NAME,
    )
    from management.db.models import TenantConfig, TenantGroupInfo
    from sqlalchemy import select

    # Exclude placeholder rows seeded by the deployment scripts ("" / "tenant_id"),
    # and the virtual asset-owner tenant, so a fresh install does not bind the SU
    # to a fake tenant and skip real provisioning. Mirrors _count_real_tenants.
    existing = (
        session.execute(
            select(TenantConfig.tenant_id)
            .where(
                TenantConfig.config_key == TENANT_ID,
                TenantConfig.delete_flag == "N",
                TenantConfig.tenant_id.isnot(None),
                TenantConfig.tenant_id.notin_(
                    ("", DEFAULT_TENANT_ID, ASSET_OWNER_TENANT_ID)
                ),
            )
            .limit(1)
        )
        .scalar_one_or_none()
    )
    if existing:
        return existing

    tenant_id = str(uuid.uuid4())
    created_by = "system"

    session.add(
        TenantConfig(
            tenant_id=tenant_id,
            config_key=TENANT_ID,
            config_value=tenant_id,
            created_by=created_by,
            updated_by=created_by,
        )
    )
    default_group = TenantGroupInfo(
        tenant_id=tenant_id,
        group_name="Default Group",
        group_description="Default group created automatically during super-admin bootstrap",
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(default_group)
    session.flush()
    session.add_all(
        [
            TenantConfig(
                tenant_id=tenant_id,
                config_key=TENANT_NAME,
                config_value="Default Tenant",
                created_by=created_by,
                updated_by=created_by,
            ),
            TenantConfig(
                tenant_id=tenant_id,
                config_key=DEFAULT_GROUP_ID,
                config_value=str(default_group.group_id),
                created_by=created_by,
                updated_by=created_by,
            ),
        ]
    )
    session.flush()
    return tenant_id


def bootstrap_super_admin(email: str, password: str, *, check_only=False):
    from infrastructure.rdb.client import get_db_session
    from management.db.identity.account import (
        create_account,
        get_account_by_email,
        lock_account_keys,
    )
    from management.db.identity.user_tenant import insert_user_tenant
    from management.utils.account_passwords import hash_password
    from sqlalchemy import select
    from management.db.models import UserTenant

    email = email.strip().lower()
    with get_db_session() as session:
        lock_account_keys(session, "super-admin-bootstrap", email)
        account = get_account_by_email(email, session)
        if account:
            members = (
                session.execute(
                    select(UserTenant).where(
                        UserTenant.user_id == account["user_id"],
                        UserTenant.delete_flag == "N",
                    )
                )
                .scalars()
                .all()
            )
            if (
                account["delete_flag"] != "N"
                or not members
                or any(tuple(m.roles or ()) != ("SU",) for m in members)
            ):
                raise AccountConflictError(
                    "Bootstrap email belongs to an unavailable or non-SU identity"
                )
            return {"exists": True}
        # A pre-cutover SU membership must be migrated, never replaced by a new ID.
        if session.execute(
            select(UserTenant.user_id).where(
                UserTenant.roles.contains(["SU"]), UserTenant.delete_flag == "N"
            )
        ).first():
            raise AccountConflictError(
                "An SU membership already exists. Verify its account and email; if not migrated, run the host migrate.sh --apply against this PostgreSQL database first"
            )
        # Historical inactive associations intentionally have no local account.
        # Only an available account can reserve the current SU identity.
        if check_only:
            return {"exists": False}
        if (
            len(password) < 8
            or not any(c.isupper() for c in password)
            or not any(c.islower() for c in password)
            or not any(c.isdigit() for c in password)
        ):
            raise ValueError(
                "Password must contain uppercase, lowercase and digit and be at least 8 characters"
            )
        load_system_configuration()
        account = create_account(email, hash_password(password), db_session=session)
        tenant_id = _resolve_or_create_default_tenant(session)
        insert_user_tenant(
            account["user_id"], tenant_id, "SU", email,
            created_by="system", db_session=session,
        )
        return {"created": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser("bootstrap-su")
    bootstrap.add_argument("--email", default="suadmin@nexent.com")
    bootstrap.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "bootstrap-su":
            result = bootstrap_super_admin(
                args.email,
                "" if args.check else sys.stdin.readline().rstrip("\r\n"),
                check_only=args.check,
            )
            print(json.dumps(result))
            return 0 if result.get("exists") or result.get("created") else 3
    except AccountConflictError as exc:
        # Domain messages contain fixed descriptions, never source values.
        print("Account preflight rejected: " + str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        # Driver errors can embed DSNs or query values. Report only a safe class.
        print(
            "Account operation failed ("
            + type(exc).__name__
            + "); inspect prerequisites and run preflight again.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
