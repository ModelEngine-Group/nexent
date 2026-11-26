# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Create disposable login accounts inside the case-owned Kubernetes release."""

import json
from secrets import token_hex
import sys
from uuid import UUID, uuid5

from contracts.constants.environment import POSTGRES_HOST
from infrastructure.rdb.client import get_db_session
from management.configuration.runtime import load_system_configuration
from management.db.configuration.tenant import create_tenant_with_default_group
from management.db.identity.account import create_account
from management.db.identity.user_tenant import insert_user_tenant
from management.utils.account_passwords import hash_password


def create_identity(token, role, *, can_create=False):
    tenant = str(uuid5(token, f"{role}:tenant"))
    user = str(uuid5(token, f"{role}:user"))
    email = f"runtime-{user}@example.com"
    password = "Runtime-1a-" + token_hex(24)
    create_tenant_with_default_group(tenant, "Runtime scaling fixture", created_by=user)
    with get_db_session() as session:
        create_account(email, hash_password(password), user_id=user, db_session=session)
        insert_user_tenant(user, tenant, user_role="DEV" if can_create else "USER", user_email=email, db_session=session)
    return {"tenant_id": tenant, "user_id": user, "email": email, "password": password}


def main():
    raw_token, *options = sys.argv[1:]
    token = UUID(hex=raw_token)
    if options not in ([], ["creator"]) or token.hex != raw_token or POSTGRES_HOST not in {
        "nexent-postgresql", "nexent-postgresql.nexent", "nexent-postgresql.nexent.svc",
        "nexent-postgresql.nexent.svc.cluster.local",
    }:
        raise RuntimeError("Identity preparation requires the case-owned database")
    load_system_configuration()
    print("SCALING_IDENTITIES " + json.dumps({role: create_identity(token, role, can_create=bool(options))
                                            for role in ("owner", "foreign")}))


if __name__ == "__main__":
    main()
