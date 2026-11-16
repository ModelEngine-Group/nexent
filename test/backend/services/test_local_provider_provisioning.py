# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Native provider provisioning preserves identities and transaction boundaries."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest

from contracts.errors.exceptions import AccountConflictError, OAuthLinkError, OAuthProviderError, TenantResourceLimitError, UnauthorizedError
from infrastructure.security.passwords import verify_password
from management.services.permission.identity import cas, oauth, registration


@pytest.fixture
def principal():
    return SimpleNamespace(cas_user_id="cas-original", email="cas@example.com", username="CAS User", tenant_id="tenant")


@pytest.mark.parametrize("mode", ["bound", "email", "new", "race", "unresolved"])
def test_cas_resolves_original_or_concurrently_created_identity(mocker, principal, mode):
    mocker.patch.object(cas, "get_oauth_account_by_provider", return_value={"user_id": "original"} if mode == "bound" else None)
    lookup = mocker.patch.object(cas, "find_account_user_id_by_email")
    lookup.side_effect = {
        "email": ["original"], "new": [None], "race": [None, "original"], "unresolved": [None, None], "bound": [],
    }[mode]
    create = mocker.patch.object(cas, "create_account", return_value={"user_id": "original"})
    if mode in {"race", "unresolved"}:
        create.side_effect = AccountConflictError("Concurrent creation")
    active = mocker.patch.object(cas, "require_active_account")
    bind = mocker.patch.object(cas, "create_or_update_oauth_account")
    if mode == "unresolved":
        with pytest.raises(AccountConflictError, match="Concurrent creation"):
            cas._resolve_project_user(principal)
        active.assert_not_called()
        bind.assert_not_called()
        return
    assert cas._resolve_project_user(principal) == "original"
    active.assert_called_once_with("original")
    bind.assert_called_once_with(user_id="original", provider=cas.CAS_PROVIDER, provider_user_id="cas-original",
                                 email="cas@example.com", username="CAS User", tenant_id="tenant")
    if mode in {"bound", "email"}:
        create.assert_not_called()
    else:
        create.assert_called_once_with("cas@example.com")


def test_cas_cannot_rebind_disabled_local_identity(mocker, principal):
    mocker.patch.object(cas, "get_oauth_account_by_provider", return_value={"user_id": "disabled"})
    mocker.patch.object(cas, "require_active_account", side_effect=UnauthorizedError("disabled"))
    bind = mocker.patch.object(cas, "create_or_update_oauth_account")
    with pytest.raises(UnauthorizedError):
        cas._resolve_project_user(principal)
    bind.assert_not_called()


@pytest.mark.parametrize("email,stored,expected", [(None, None, None), ("user@example.com", None, None), ("user@example.com", {"user_id": "original"}, "original")])
def test_oauth_email_lookup_uses_local_identity(mocker, email, stored, expected):
    lookup = mocker.patch.object(oauth, "get_account_by_email", return_value=stored)
    assert oauth.find_account_user_id_by_email(email) == expected
    if email:
        lookup.assert_called_once_with(email)
    else:
        lookup.assert_not_called()


def test_pending_oauth_token_uses_local_signing_key(mocker):
    mocker.patch.object(oauth, "JWT_SECRET", "synthetic-local-provider-signing-key-32-bytes")
    token = oauth.generate_pending_oauth_token("github", "remote-id", "user@example.com", "Remote User")
    claims = jwt.decode(token, oauth.JWT_SECRET, algorithms=["HS256"])
    assert claims["provider_user_id"] == "remote-id"
    assert claims["purpose"] == oauth.OAUTH_PENDING_PURPOSE
    mocker.patch.object(oauth, "JWT_SECRET", "")
    with pytest.raises(OAuthProviderError, match="not configured"):
        oauth.generate_pending_oauth_token("github", "remote-id")


@pytest.fixture
def completion(mocker):
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(group_id=1)
    transaction = []

    @contextmanager
    def db_session():
        transaction.append("begin")
        try:
            yield session
        except Exception:
            transaction.append("rollback")
            raise
        else:
            transaction.append("commit")

    mocker.patch.object(registration, "get_db_session", db_session)
    mocker.patch.object(oauth, "get_oauth_account_by_provider", return_value=None)
    lookup = mocker.patch.object(oauth, "find_account_user_id_by_email", return_value=None)
    mocker.patch.object(oauth, "check_invitation_available", return_value=True)
    invitation = {"tenant_id": "tenant", "roles": ["DEV", "OPS"]}
    locked = SimpleNamespace(invitation_id=42, capacity=2, status="IN_USE", group_ids=[1], **invitation)
    mocker.patch.object(oauth, "get_invitation_by_code", return_value=invitation)
    mocker.patch.object(registration, "query_invitation_by_code", return_value=invitation)
    mocker.patch.object(registration, "locked_invitation", return_value=locked)
    mocker.patch.object(registration, "invitation_usage", return_value=0)
    mocker.patch.object(registration, "as_dict", side_effect=vars)
    create = mocker.patch.object(
        registration, "create_account", return_value={"user_id": "local-id", "email": "user@example.com"}
    )
    member = mocker.patch.object(registration, "insert_user_tenant")
    add = mocker.patch.object(registration, "add_user_to_group")
    tools = mocker.patch.object(oauth, "init_tool_list_for_tenant", new_callable=AsyncMock)
    bind = mocker.patch.object(oauth, "create_or_update_oauth_account")
    token = mocker.patch.object(oauth, "generate_session_jwt", return_value="local-token")
    mocker.patch.object(oauth, "calculate_expires_at", return_value=12345)
    mocker.patch.object(oauth, "require_asset_owner_enabled")
    identity = {"provider": "github", "provider_user_id": "remote-id", "provider_email": "User@Example.com", "provider_username": "Remote User"}
    return SimpleNamespace(**locals())


@pytest.mark.asyncio
@pytest.mark.parametrize("asset_owner", [False, True])
async def test_oauth_completion_creates_native_credentials_and_membership_together(completion, asset_owner):
    c = completion
    if asset_owner:
        c.invitation.update(
            code_type=oauth.ASSET_OWNER_INVITE_CODE_TYPE, roles=[oauth.ASSET_OWNER_ROLE],
            tenant_id=oauth.ASSET_OWNER_TENANT_ID,
        )
        c.locked.tenant_id = oauth.ASSET_OWNER_TENANT_ID
        c.locked.roles = [oauth.ASSET_OWNER_ROLE]
        c.locked.group_ids = []
    result = await oauth.complete_pending_oauth_account(c.identity, "Password123", "invite")
    assert c.transaction == ["begin", "commit"]
    email, encoded = c.create.call_args.args
    assert email == "user@example.com"
    assert verify_password("Password123", encoded)
    assert c.create.call_args.kwargs["db_session"] is c.session
    tenant = oauth.ASSET_OWNER_TENANT_ID if asset_owner else "tenant"
    role = oauth.ASSET_OWNER_ROLE if asset_owner else "DEV"
    roles = (role,) if asset_owner else ("DEV", "OPS")
    c.member.assert_called_once_with("local-id", tenant, role, email, db_session=c.session, roles=roles)
    c.session.add.assert_called_once()
    usage = c.session.add.call_args.args[0]
    assert (usage.invitation_id, usage.user_id) == (42, "local-id")
    if asset_owner:
        c.add.assert_not_called()
        c.tools.assert_not_awaited()
    else:
        c.add.assert_called_once_with(1, "local-id", "local-id", db_session=c.session)
        c.tools.assert_awaited_once_with(tenant, "local-id")
    assert result["user"] == {"id": "local-id", "email": email, "role": role, "roles": list(roles)}
    assert result["session"]["access_token"] == "local-token"
    assert result["session"]["refresh_token"] == ""
    c.bind.assert_called_once_with(user_id="local-id", provider="github", provider_user_id="remote-id", email=email, username="Remote User", tenant_id=tenant)


@pytest.mark.asyncio
@pytest.mark.parametrize("password,duplicate", [("passwordonly", False), ("Password123", True)])
async def test_oauth_completion_rejects_weak_password_and_existing_local_email(completion, password, duplicate):
    c = completion
    c.lookup.return_value = "existing" if duplicate else None
    with pytest.raises(OAuthLinkError, match="Email already exists" if duplicate else "uppercase"):
        await oauth.complete_pending_oauth_account(c.identity, password, "invite")
    c.create.assert_not_called()
    c.member.assert_not_called()
    assert c.transaction == []


@pytest.mark.asyncio
async def test_oauth_membership_limit_rolls_back_before_invitation_or_binding(completion):
    c = completion
    c.member.side_effect = TenantResourceLimitError("tenant full")
    with pytest.raises(TenantResourceLimitError):
        await oauth.complete_pending_oauth_account(c.identity, "Password123", "invite")
    assert c.transaction == ["begin", "rollback"]
    c.session.add.assert_not_called()
    c.bind.assert_not_called()
    c.token.assert_not_called()
