# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""One authentication attempt uses one authoritative API-key record."""

from management.services.permission.identity import northbound as northbound_auth


def test_api_key_authentication_queries_credential_and_account_once(monkeypatch):
    from service_common.service_identity.gateway import identity_context

    calls = []

    def key_record(value):
        calls.append(("key", value))
        return {"user_id": "u1", "token_id": 7, "delete_flag": "N"}

    def account(user):
        calls.append(("account", user))
        return {"delete_flag": "N"}

    monkeypatch.setattr(northbound_auth, "get_token_by_access_key", key_record)
    monkeypatch.setattr(northbound_auth, "require_active_account", account)
    monkeypatch.setattr(northbound_auth, "get_user_tenant_by_user_id", lambda user: {"tenant_id": "t1"})
    token = identity_context.set(None)
    try:
        principal = northbound_auth.authenticate_api_key("Bearer fixture-key")
    finally:
        identity_context.reset(token)
    assert (principal.user_id, principal.tenant_id, principal.token_id) == ("u1", "t1", 7)
    assert calls == [("key", "fixture-key"), ("account", "u1")]
