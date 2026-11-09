# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authoritative state checks behind the private Gateway lookup interface."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gateway.downstream.identity import IdentityError
from management.services.permission.identity.gateway_lookup import resolve_gateway_identity


@pytest.fixture
def store(monkeypatch):
    account = {"delete_flag": "N", "token_version": 3, "email": "fixture@example.test"}
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


@pytest.mark.parametrize("tenant", ["", None])
def test_super_admin_session_retains_default_context_for_empty_membership_tenant(store, tenant):
    from contracts.constants.constants import DEFAULT_TENANT_ID

    store.membership.update(tenant_id=tenant, user_role="SU")
    identity = resolve_gateway_identity({"kind": "session", "user_id": "user-1", "token_version": 3})
    assert identity["tenant_id"] == DEFAULT_TENANT_ID
    assert identity["role"] == "SU"
    store.get_membership.assert_called_once_with("user-1")


def test_super_admin_api_key_does_not_gain_a_default_tenant(store):
    store.membership.update(tenant_id="", user_role="SU")
    with pytest.raises(IdentityError, match="No active membership"):
        resolve_gateway_identity({"kind": "api_key", "access_key": "fixture"})


def test_asset_owner_session_keeps_its_existing_virtual_tenant(store):
    from contracts.constants.constants import ASSET_OWNER_ROLE, ASSET_OWNER_TENANT_ID

    store.membership.update(tenant_id="", user_role=ASSET_OWNER_ROLE)
    identity = resolve_gateway_identity({"kind": "session", "user_id": "user-1", "token_version": 3})
    assert identity["tenant_id"] == ASSET_OWNER_TENANT_ID


@pytest.mark.parametrize("role", ["USER", "DEV", "ADMIN"])
def test_ordinary_session_with_empty_tenant_remains_rejected(store, role):
    store.membership.update(tenant_id="", user_role=role)
    with pytest.raises(IdentityError, match="No active membership"):
        resolve_gateway_identity({"kind": "session", "user_id": "user-1", "token_version": 3})


@pytest.mark.parametrize("failure", ["account", "membership", "deleted-membership", "revision"])
def test_super_admin_default_context_does_not_bypass_revocation(store, failure):
    store.membership.update(tenant_id="", user_role="SU")
    if failure == "account": store.account["delete_flag"] = "Y"
    if failure == "membership": store.get_membership.return_value = None
    if failure == "deleted-membership": store.membership["delete_flag"] = "Y"
    if failure == "revision": store.account["token_version"] = 4
    with pytest.raises(IdentityError):
        resolve_gateway_identity({"kind": "session", "user_id": "user-1", "token_version": 3})


@pytest.mark.parametrize("failure", ["disabled", "missing-account", "version", "cas", "membership", "tenant", "role", "deleted-membership"])
def test_session_revocation_and_missing_relationships_are_rejected(store, failure):
    query = {"kind": "session", "user_id": "user-1", "token_version": 3, "session_id": "sid"}
    if failure == "disabled": store.account["delete_flag"] = "Y"
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
    if failure == "disabled": store.account["delete_flag"] = "Y"
    with pytest.raises(IdentityError):
        resolve_gateway_identity({"kind": "api_key", "access_key": "fixture"})
