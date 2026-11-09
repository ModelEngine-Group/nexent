# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Gateway identity policy over an infrastructure database snapshot."""

from gateway.security.identity import IdentityError
from gateway.security.management_client import IdentityUnavailable
from infrastructure.rdb.identity import IdentityRejected, IdentityStoreUnavailable


class DatabaseIdentityProvider:
    def __init__(self, repository):
        self.repository = repository

    async def __call__(self, query):
        try:
            snapshot = await self.repository.snapshot(query)
        except IdentityRejected:
            raise IdentityError("Invalid or revoked credentials") from None
        except IdentityStoreUnavailable:
            raise IdentityUnavailable("Identity database unavailable") from None
        account, membership = snapshot["account"], snapshot["membership"]
        kind = query["kind"]
        if kind == "session" and (type(query.get("token_version")) is not int
                                  or query["token_version"] != account["token_version"]
                                  or not snapshot["session_active"]):
            raise IdentityError("Invalid or revoked session")
        role = str(account.get("user_role") or "").upper()
        tenant_id = membership.get("tenant_id")
        if kind == "session" and not tenant_id:
            tenant_id = {"SU": "tenant_id", "ASSET_OWNER": "asset_owner_tenant_id"}.get(role)
        if not isinstance(tenant_id, str) or not tenant_id or not role:
            raise IdentityError("No active membership")
        return {"user_id": account["user_id"], "tenant_id": tenant_id, "role": role,
                "kind": kind, "token_id": snapshot["token_id"], "language": query.get("language", "zh"),
                "email": account.get("user_email", ""),
                "session_id": query.get("session_id") if kind == "session" else None}
