# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authoritative account, membership and credential-state lookup for Gateway."""

from infrastructure.security.gateway_identity import IdentityError


def resolve_gateway_identity(query: dict) -> dict:
    from management.db.identity.account import get_account
    from management.db.identity.token import get_token_by_access_key
    from management.db.identity.user_tenant import get_user_tenant_by_user_id
    from management.db.identity.cas_session import is_cas_session_active
    from contracts.constants.constants import ASSET_OWNER_ROLE, ASSET_OWNER_TENANT_ID

    kind = query.get("kind")
    token_id = None
    if kind == "api_key":
        record = get_token_by_access_key(query.get("access_key"))
        if not record or record.get("delete_flag") == "Y":
            raise IdentityError("Invalid credential")
        user_id, token_id = record.get("user_id"), record.get("token_id")
    elif kind == "session":
        user_id = query.get("user_id")
    else:
        raise IdentityError("Invalid credential policy")
    if not isinstance(user_id, str) or not user_id:
        raise IdentityError("Missing account")
    account = get_account(user_id)
    if not account or account.get("account_status") != "active":
        raise IdentityError("Account is unavailable")
    if kind == "session":
        if type(query.get("token_version")) is not int or query["token_version"] != account.get("token_version"):
            raise IdentityError("Credentials have changed")
        if query.get("session_id") and not is_cas_session_active(query["session_id"]):
            raise IdentityError("Session is unavailable")
    membership = get_user_tenant_by_user_id(user_id)
    if not membership or membership.get("delete_flag") == "Y":
        raise IdentityError("No active membership")
    role = str(membership.get("user_role") or "").upper()
    tenant_id = membership.get("tenant_id")
    if kind == "session" and role == ASSET_OWNER_ROLE and not tenant_id:
        tenant_id = ASSET_OWNER_TENANT_ID
    if not tenant_id or not role:
        raise IdentityError("No active membership")
    return {"user_id": user_id, "tenant_id": tenant_id, "role": role, "token_id": token_id,
            "kind": kind, "language": query.get("language", "zh"), "email": account.get("email", ""),
            "session_id": query.get("session_id") if kind == "session" else None}
