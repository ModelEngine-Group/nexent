# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authoritative state checks behind the private Gateway lookup interface."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from infrastructure.security.gateway_identity import IdentityError
from management.services.permission.identity.gateway_lookup import resolve_gateway_identity


@pytest.fixture
def store(monkeypatch):
    account = {"account_status": "active", "token_version": 3, "email": "fixture@example.test"}
    membership = {"tenant_id": "tenant-1", "user_role": "admin", "delete_flag": "N"}
    key = {"user_id": "user-1", "token_id": 17, "delete_flag": "N"}
    get_account, get_membership, get_key = MagicMock(return_value=account), MagicMock(return_value=membership), MagicMock(return_value=key)
    cas = MagicMock(return_value=True)
    for name, values in {
        "account": {"get_account": get_account}, "user_tenant": {"get_user_tenant_by_user_id": get_membership},
        "token": {"get_token_by_access_key": get_key}, "cas_session": {"is_cas_session_active": cas},
    }.items():
        monkeypatch.setitem(sys.modules, "management.db.identity." + name, SimpleNamespace(**values))
    return SimpleNamespace(account=account, membership=membership, key=key, cas=cas,
                           get_account=get_account, get_membership=get_membership, get_key=get_key)


def test_session_and_api_key_identity_return_only_public_identity_fields(store):
    identity = resolve_gateway_identity({"kind": "session", "user_id": "user-1", "token_version": 3, "session_id": "sid"})
    assert (identity["user_id"], identity["tenant_id"], identity["role"]) == ("user-1", "tenant-1", "ADMIN")
    store.cas.assert_called_once_with("sid")
    identity = resolve_gateway_identity({"kind": "api_key", "access_key": "opaque-key"})
    assert identity["token_id"] == 17
    assert "access_key" not in identity and "token_version" not in identity
    store.get_key.assert_called_once_with("opaque-key")


@pytest.mark.parametrize("failure", ["disabled", "missing-account", "version", "cas", "membership", "tenant", "role", "deleted-membership"])
def test_session_revocation_and_missing_relationships_are_rejected(store, failure):
    query = {"kind": "session", "user_id": "user-1", "token_version": 3, "session_id": "sid"}
    if failure == "disabled": store.account["account_status"] = "disabled"
    if failure == "missing-account": store.get_account.return_value = None
    if failure == "version": query["token_version"] = 2
    if failure == "cas": store.cas.return_value = False
    if failure == "membership": store.get_membership.return_value = None
    if failure == "tenant": store.membership["tenant_id"] = ""
    if failure == "role": store.membership["user_role"] = ""
    if failure == "deleted-membership": store.membership["delete_flag"] = "Y"
    with pytest.raises(IdentityError):
        resolve_gateway_identity(query)


@pytest.mark.parametrize("failure", ["revoked", "missing", "no-user", "disabled"])
def test_api_key_rejection_checks_active_owner(store, failure):
    if failure == "revoked": store.key["delete_flag"] = "Y"
    if failure == "missing": store.get_key.return_value = None
    if failure == "no-user": store.key["user_id"] = None
    if failure == "disabled": store.account["account_status"] = "disabled"
    with pytest.raises(IdentityError):
        resolve_gateway_identity({"kind": "api_key", "access_key": "fixture"})
