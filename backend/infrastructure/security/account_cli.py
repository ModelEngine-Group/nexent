# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local super-administrator bootstrap."""

import argparse
import json
import sys


from contracts.errors.exceptions import AccountConflictError


def bootstrap_super_admin(email: str, password: str, *, check_only=False):
    from management.db.client import get_db_session
    from management.db.identity.account import (
        create_account,
        get_account_by_email,
        lock_account_keys,
    )
    from management.db.identity.user_tenant import insert_user_tenant
    from infrastructure.security.passwords import hash_password
    from sqlalchemy import select
    from management.db.models import UserTenant, UserAccount

    email = email.strip().lower()
    with get_db_session() as session:
        lock_account_keys(session, "super-admin-bootstrap", email)
        account = get_account_by_email(email, session)
        if account:
            if (account.get("source_metadata") or {}).get("credential_migration_pending"):
                raise AccountConflictError("Account credentials await migration; run the host migrate.py --apply first")
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
                account["account_status"] != "active"
                or not members
                or any(m.user_role != "SU" for m in members)
            ):
                raise AccountConflictError(
                    "Bootstrap email belongs to an unavailable or non-SU identity"
                )
            return {"exists": True}
        # A pre-cutover SU membership must be migrated, never replaced by a new ID.
        if session.execute(
            select(UserTenant.user_id).where(
                UserTenant.user_role == "SU", UserTenant.delete_flag == "N"
            )
        ).first():
            raise AccountConflictError(
                "An SU membership already exists. Verify its account and email; if not migrated, run the host migrate.py --apply against this PostgreSQL database first"
            )
        if session.execute(
            select(UserTenant.user_id).where(
                UserTenant.delete_flag == "N",
                UserTenant.user_id.notin_(select(UserAccount.user_id).where(UserAccount.delete_flag == "N")),
            )
        ).first():
            raise AccountConflictError("Active membership has no account profile; restore the original account before bootstrap")
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
        account = create_account(email, hash_password(password), db_session=session)
        insert_user_tenant(
            account["user_id"], "", "SU", email, created_by="system", db_session=session
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
