# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Native auth orchestration unit regressions with isolated persistence."""

from contextlib import nullcontext
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest

from contracts.errors.exceptions import UnauthorizedError, TenantResourceLimitError
from infrastructure.security.passwords import hash_password
from management.services.permission.identity import authentication as auth
from gateway.authentication import auth as helpers


@pytest.fixture
def account():
    return {
        "user_id": "user-native",
        "email": "user@example.com",
        "password_hash": hash_password("Password123"),
        "password_login_enabled": True,
        "account_status": "active",
        "token_version": 0,
        "email_confirmed_at": datetime.now(),
    }


@pytest.mark.asyncio
async def test_native_signin_checks_password_and_local_membership(monkeypatch, account):
    monkeypatch.setattr(auth, "get_account_by_email", lambda email: account)
    monkeypatch.setattr(auth, "require_active_account", lambda uid: account)
    monkeypatch.setattr(
        auth, "get_user_tenant_by_user_id", lambda uid: {"user_role": "DEV"}
    )
    monkeypatch.setattr(
        auth,
        "build_token_response",
        lambda uid: {"access_token": "signed", "refresh_token": ""},
    )
    data = await auth.signin_user("USER@example.com", "Password123")
    assert data["data"]["user"] == {
        "id": "user-native",
        "email": "user@example.com",
        "role": "DEV",
    }
    assert data["data"]["session"]["refresh_token"] == ""
    with pytest.raises(UnauthorizedError):
        await auth.signin_user("user@example.com", "wrong")
    monkeypatch.setattr(auth, "get_user_tenant_by_user_id", lambda uid: None)
    with pytest.raises(UnauthorizedError):
        await auth.signin_user("user@example.com", "Password123")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("password_login_enabled", False), ("email_confirmed_at", None)]
)
async def test_native_signin_rejects_unavailable_password_identity(
    monkeypatch, account, field, value
):
    account[field] = value
    monkeypatch.setattr(auth, "get_account_by_email", lambda email: account)
    with pytest.raises(UnauthorizedError):
        await auth.signin_user("user@example.com", "Password123")


@pytest.mark.asyncio
async def test_registration_account_and_membership_share_transaction(
    monkeypatch, account
):
    session = object()
    create = MagicMock(return_value=account)
    member = MagicMock()
    monkeypatch.setattr(auth, "get_db_session", lambda: nullcontext(session))
    monkeypatch.setattr(auth, "create_account", create)
    monkeypatch.setattr(auth, "insert_user_tenant", member)
    monkeypatch.setattr(auth, "check_invitation_available", lambda code: True)
    monkeypatch.setattr(
        auth,
        "get_invitation_by_code",
        lambda code: {"tenant_id": "t", "code_type": "USER_INVITE"},
    )
    monkeypatch.setattr(auth, "use_invitation_code", lambda *a: {"group_ids": []})
    monkeypatch.setattr(auth, "init_tool_list_for_tenant", AsyncMock())
    monkeypatch.setattr(auth, "init_skill_list_for_tenant", AsyncMock())
    data = await auth.signup_user_with_invitation(
        "user@example.com", "Password123", " invite ", False
    )
    assert data["user"]["id"] == "user-native"
    assert data["session"] is None
    assert create.call_args.kwargs["db_session"] is session
    assert member.call_args.kwargs["db_session"] is session
    member.side_effect = TenantResourceLimitError("limit reached")
    with pytest.raises(TenantResourceLimitError):
        await auth.signup_user_with_invitation(
            "user@example.com", "Password123", "INVITE", False
        )


@pytest.mark.asyncio
async def test_password_change_verifies_old_hash_and_detects_concurrent_updates(
    monkeypatch, account
):
    monkeypatch.setattr(auth, "require_active_account", lambda uid: account)
    update = MagicMock(return_value=True)
    monkeypatch.setattr(auth, "change_password", update)
    with pytest.raises(UnauthorizedError):
        await auth.update_password("user-native", "wrong", "NewPassword456")
    update.assert_not_called()
    assert await auth.update_password("user-native", "Password123", "NewPassword456")
    assert update.call_args.args[1] == account["password_hash"]
    assert "NewPassword456" not in update.call_args.args[2]
    update.return_value = False
    with pytest.raises(UnauthorizedError):
        await auth.update_password("user-native", "Password123", "NewPassword456")


def test_jwt_signature_type_and_account_revision(monkeypatch, account):
    import importlib
    user_account_db = importlib.import_module("management.db.identity.account")

    monkeypatch.setattr(
        helpers, "JWT_SECRET", "native-auth-unit-secret-at-least-32-bytes"
    )
    monkeypatch.setattr(helpers, "JWT_ISSUER", "nexent-unit")
    monkeypatch.setattr(user_account_db, "get_account", lambda uid: account)
    token = helpers.generate_session_jwt(account["user_id"])
    assert helpers._decode_jwt_token(token)["sub"] == account["user_id"]
    claims = jwt.decode(token, options={"verify_signature": False})
    for field, value in [
        ("iss", "another-system"),
        ("aud", "nexent-runtime"),
        ("ver", 1),
    ]:
        wrong = jwt.encode(
            dict(claims, **{field: value}), helpers.JWT_SECRET, algorithm="HS256"
        )
        with pytest.raises(UnauthorizedError):
            helpers._decode_jwt_token(wrong)
    account["account_status"] = "disabled"
    with pytest.raises(UnauthorizedError):
        helpers._decode_jwt_token(token)


@pytest.mark.asyncio
async def test_legacy_refresh_never_mints_a_local_jwt():
    with pytest.raises(UnauthorizedError):
        await auth.refresh_user_token("Bearer old", "old-refresh")


def test_password_policy_enforces_hashing_byte_limit():
    assert not auth.validate_password_strength("Aa1" + "a" * 1024)


@pytest.mark.asyncio
async def test_local_health_reports_unavailable_configuration_or_store(monkeypatch):
    monkeypatch.setattr(auth, "JWT_SECRET", "")
    with pytest.raises(ConnectionError):
        await auth.check_auth_service_health()
    monkeypatch.setattr(auth, "JWT_SECRET", "configured")
    monkeypatch.setattr(auth, "get_db_session", MagicMock(side_effect=RuntimeError("store offline")))
    with pytest.raises(ConnectionError):
        await auth.check_auth_service_health()
