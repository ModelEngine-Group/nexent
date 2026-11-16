# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Native authentication orchestration and authorization boundary regressions."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from contracts.errors.exceptions import OAuthProviderError, UnauthorizedError
from gateway.authentication import auth as gateway
from management.db.identity import user_tenant
from management.services.permission.identity import authentication as auth


@pytest.fixture
def signup(mocker):
    mocker.patch.object(
        auth,
        "get_invitation_by_code",
        return_value={"tenant_id": "tenant", "code_type": "USER_INVITE"},
    )
    mocker.patch.object(auth, "hash_password", return_value="encoded-password")
    register = mocker.patch.object(
        auth,
        "register_invited_account",
        return_value=(
            {"user_id": "native", "email": "user@example.com"},
            {"tenant_id": "tenant", "roles": ["USER"]},
        ),
    )
    tools = mocker.patch.object(auth, "init_tool_list_for_tenant", new_callable=AsyncMock)
    skills = mocker.patch.object(auth, "init_skill_list_for_tenant", new_callable=AsyncMock)
    mint = mocker.patch.object(auth, "generate_session_jwt", return_value="signed-jwt")
    mocker.patch.object(auth, "calculate_expires_at", return_value=12345)
    mocker.patch.object(auth, "get_jwt_expiry_seconds", return_value=3600)
    return SimpleNamespace(register=register, tools=tools, skills=skills, mint=mint)


@pytest.mark.asyncio
@pytest.mark.parametrize("auto_login", [True, False])
async def test_signup_uses_atomic_registration_and_optional_session(signup, auto_login):
    result = await auth.signup_user_with_invitation(
        "user@example.com",
        "Password123",
        " invite ",
        auto_login,
    )
    signup.register.assert_called_once_with("user@example.com", "encoded-password", " invite ")
    assert result["user"]["roles"] == ["USER"]
    if auto_login:
        assert result["session"] == {
            "access_token": "signed-jwt",
            "refresh_token": "",
            "expires_at": 12345,
            "expires_in_seconds": 3600,
        }
        signup.mint.assert_called_once_with("native")
    else:
        assert result["session"] is None
        signup.mint.assert_not_called()
    signup.tools.assert_awaited_once_with("tenant", "native")
    signup.skills.assert_awaited_once_with("tenant", "native")


@pytest.mark.asyncio
async def test_signup_stops_after_atomic_invitation_write_failure(signup):
    signup.register.side_effect = RuntimeError("Atomic registration failed")
    with pytest.raises(RuntimeError, match="Atomic registration failed"):
        await auth.signup_user_with_invitation("user@example.com", "Password123", "INVITE", True)
    signup.mint.assert_not_called()
    signup.tools.assert_not_awaited()
    signup.skills.assert_not_awaited()


@pytest.mark.asyncio
async def test_health_checks_local_account_table(mocker):
    session = MagicMock()
    mocker.patch.object(auth, "JWT_SECRET", "test-only-configured")
    mocker.patch.object(auth, "get_db_session", return_value=nullcontext(session))
    await auth.check_auth_service_health()
    assert "user_account_t" in str(session.execute.call_args.args[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", [None, {"password_hash": None}])
async def test_unknown_or_passwordless_identity_does_dummy_password_work(mocker, stored):
    mocker.patch.object(auth, "get_account_by_email", return_value=stored)
    create_dummy = mocker.patch.object(auth, "hash_password", return_value="dummy-hash")
    verify = mocker.patch.object(auth, "verify_password", return_value=False)
    with pytest.raises(UnauthorizedError):
        await auth.signin_user("unknown@example.com", "Password123")
    create_dummy.assert_called_once_with("invalid-account-placeholder")
    verify.assert_called_once_with("Password123", "dummy-hash")


@pytest.mark.asyncio
async def test_asset_owner_signin_checks_feature_before_minting_jwt(mocker):
    mocker.patch.object(
        auth,
        "get_account_by_email",
        return_value={
            "user_id": "owner",
            "email": "owner@example.com",
            "password_hash": "stored",
            "password_login_enabled": True,
            "email_confirmed_at": "confirmed",
        },
    )
    mocker.patch.object(auth, "verify_password", return_value=True)
    mocker.patch.object(auth, "require_active_account")
    mocker.patch.object(auth, "get_user_tenant_by_user_id", return_value={"user_role": auth.ASSET_OWNER_ROLE})
    enabled = mocker.patch.object(auth, "require_asset_owner_enabled")
    mint = mocker.patch.object(auth, "build_token_response", return_value={"access_token": "native"})
    assert (await auth.signin_user("owner@example.com", "Password123"))["data"]["session"]["access_token"] == "native"
    enabled.assert_called_once_with()
    mint.reset_mock()
    enabled.side_effect = UnauthorizedError("feature unavailable")
    with pytest.raises(UnauthorizedError):
        await auth.signin_user("owner@example.com", "Password123")
    mint.assert_not_called()


@pytest.mark.asyncio
async def test_user_info_without_active_membership_returns_no_identity(mocker):
    mocker.patch.object(auth, "get_user_tenant_by_user_id", return_value=None)
    assert await auth.get_user_info("orphan") is None


@pytest.mark.parametrize("allowed", [True, False])
def test_token_validation_preserves_identity_contract_or_returns_no_user(mocker, allowed):
    current = mocker.patch.object(gateway, "get_current_user_id", return_value=("native", "tenant"))
    mocker.patch.object(gateway, "require_active_account", return_value={"email": "user@example.com"})
    mocker.patch.object(gateway, "get_user_tenant_by_user_id", return_value={"user_role": "DEV"})
    if not allowed:
        current.side_effect = UnauthorizedError("expired")
    valid, user = gateway.validate_token("Bearer native-token")
    assert valid is allowed
    if allowed:
        assert (user.id, user.email, user.user_metadata) == ("native", "user@example.com", {"role": "DEV"})
    else:
        assert user is None


def test_session_minting_rejects_missing_key(mocker):
    mocker.patch.object(gateway, "JWT_SECRET", "")
    with pytest.raises(UnauthorizedError, match="signing is not configured"):
        gateway.generate_session_jwt("native", expires_in=60)


@pytest.mark.parametrize("membership", [None, {"tenant_id": "", "user_role": "SU"}])
def test_session_resolution_rejects_missing_membership_or_resolves_default_tenant(mocker, membership):
    mocker.patch.object(gateway, "_decode_jwt_token", return_value={"sub": "native"})
    mocker.patch.object(gateway, "ensure_cas_session_active_from_authorization")
    mocker.patch.object(gateway, "get_user_tenant_by_user_id", return_value=membership)
    if membership is None:
        with pytest.raises(UnauthorizedError, match="No active tenant"):
            gateway._resolve_session_user("Bearer signed")
    else:
        assert gateway._resolve_session_user("Bearer signed") == ("native", gateway.DEFAULT_TENANT_ID)


def test_pending_token_verification_requires_signing_key(mocker):
    mocker.patch.object(gateway, "JWT_SECRET", "")
    with pytest.raises(OAuthProviderError, match="not configured"):
        gateway.parse_pending_oauth_token("pending")


@pytest.mark.parametrize("exists", [False, True])
def test_membership_upsert_writes_profile_and_refreshes_read_projection(mocker, exists):
    session = MagicMock()
    row = (
        SimpleNamespace(tenant_id="tenant", user_role="USER", user_id="native", updated_by="before")
        if exists
        else None
    )
    session.query.return_value.filter.return_value.first.return_value = row
    mocker.patch.object(user_tenant, "get_db_session", return_value=nullcontext(session))
    profile = mocker.patch.object(user_tenant, "set_account_profile")
    mocker.patch.object(
        user_tenant, "get_user_tenant_by_user_id", return_value={"tenant_id": "tenant"} if exists else None
    )
    mocker.patch.object(user_tenant, "as_dict", return_value={"user_id": "native", "user_role": "USER"})
    result = user_tenant.upsert_user_tenant("native", "tenant", "USER", "user@example.com")
    profile.assert_called_once_with("native", "USER", "user@example.com", "native", session, roles=("USER",))
    session.flush.assert_called_once_with()
    session.expire.assert_called_once()
    assert session.expire.call_args.args[0] is (row if exists else session.add.call_args.args[0])
    assert result["user_role"] == "USER"
