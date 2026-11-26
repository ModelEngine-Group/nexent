# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Issue Northbound test keys and a same-tenant non-owner in the disposable data domain."""

import json
from secrets import token_hex
import sys
from uuid import UUID, uuid5

from contracts.constants.environment import POSTGRES_HOST
from infrastructure.rdb.client import get_db_session
from management.configuration.runtime import load_system_configuration
from management.db.identity.account import create_account
from management.db.identity.token import create_token, generate_access_key
from management.db.identity.user_tenant import insert_user_tenant
from management.utils.account_passwords import hash_password


def prepare_public_identities(raw_token):
    token = UUID(hex=raw_token)
    if token.hex != raw_token or POSTGRES_HOST not in {
        "nexent-postgresql", "nexent-postgresql.nexent", "nexent-postgresql.nexent.svc",
        "nexent-postgresql.nexent.svc.cluster.local",
    }:
        raise ValueError("Public identity preparation requires the case-owned database")
    tenant = str(uuid5(token, "owner:tenant"))
    peer_id = str(uuid5(token, "peer:user"))
    email = f"runtime-{peer_id}@example.com"
    password = "Runtime-1a-" + token_hex(24)
    peer = {"tenant_id": tenant, "user_id": peer_id, "email": email, "password": password}
    users = {"owner": str(uuid5(token, "owner:user")), "foreign": str(uuid5(token, "foreign:user")), "peer": peer_id}
    load_system_configuration()
    with get_db_session() as session:
        create_account(email, hash_password(password), user_id=peer_id, db_session=session)
        insert_user_tenant(peer_id, tenant, user_role="USER", user_email=email, db_session=session)
        keys = {role: create_token(generate_access_key(), user_id, db_session=session)["access_key"]
                for role, user_id in users.items()}
    return {"peer": peer, "api_keys": keys}


if __name__ == "__main__":
    print("SCALING_PUBLIC_IDENTITIES " + json.dumps(prepare_public_identities(*sys.argv[1:])))
