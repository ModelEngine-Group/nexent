# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Casdoor-only completion and provider policy unit regressions."""

from contextlib import nullcontext
from unittest.mock import AsyncMock, MagicMock

import pytest

from contracts.errors.exceptions import OAuthLinkError
from management.services.permission.identity import oauth, registration


@pytest.fixture
def completion(mocker):
    mocker.patch("consts.const.is_casdoor_role_sync_configured", return_value=False)
    session = MagicMock()
    invite = MagicMock(tenant_id="tenant", status="IN_USE", capacity=2, group_ids=[])
    invite_fields = {"tenant_id": "tenant", "code_type": "USER_INVITE"}
    read_invite = mocker.patch.object(registration, "as_dict", return_value=invite_fields)
    mocker.patch.object(registration, "get_db_session", return_value=nullcontext(session))
    mocker.patch.object(registration, "query_invitation_by_code", return_value=invite_fields)
    mocker.patch.object(registration, "locked_invitation", return_value=invite)
    mocker.patch.object(registration, "invitation_usage", return_value=0)
    create = mocker.patch.object(registration, "create_account", return_value={
        "user_id": "new-user", "email": "member@example.com",
    })
    mocker.patch.object(registration, "insert_user_tenant", side_effect=lambda *args, roles, **kwargs: {
        "tenant_id": invite.tenant_id, "roles": roles,
    })
    hashed = mocker.patch.object(oauth, "hash_password", return_value="hashed-local-password")
    mocker.patch.object(oauth, "get_oauth_account_by_provider", return_value=None)
    mocker.patch.object(oauth, "find_account_user_id_by_email", return_value=None)
    mocker.patch.object(oauth, "create_or_update_oauth_account")
    mocker.patch.object(oauth, "check_invitation_available", return_value=True)
    mocker.patch.object(oauth, "get_invitation_by_code", return_value=invite_fields)
    mocker.patch.object(oauth, "init_tool_list_for_tenant", new_callable=AsyncMock)
    mocker.patch.object(oauth, "generate_session_jwt", return_value="synthetic-session")
    mocker.patch.object(oauth, "calculate_expires_at", return_value=12345)
    return session, create, hashed, read_invite


def identity(provider="casdoor"):
    return {"provider": provider, "provider_user_id": "subject", "provider_email": "member@example.com"}


@pytest.mark.parametrize("password", [None, "", "InjectedPassword123"])
@pytest.mark.asyncio
async def test_casdoor_completion_never_hashes_or_stores_a_local_password(completion, password):
    session, create, hashed, _ = completion
    result = await oauth.complete_pending_oauth_account(identity(), password, "INVITE")
    assert result["session"]["access_token"] == "synthetic-session"
    create.assert_called_once_with("member@example.com", None, db_session=session, auth_provider="casdoor")
    hashed.assert_not_called()


@pytest.mark.asyncio
async def test_configured_casdoor_signup_records_invited_role_for_provisioning(completion, mocker):
    from consts import const as settings
    settings.is_casdoor_role_sync_configured.return_value = True
    mocker.patch.object(settings, "CASDOOR_ROLE_MAP_JSON", '{"nexent-developer":"DEV"}')
    session, create, _, read_invite = completion
    read_invite.return_value = {"tenant_id": "tenant", "roles": ["DEV", "OPS"]}
    await oauth.complete_pending_oauth_account(identity(), None, "INVITE")
    create.assert_called_once_with("member@example.com", None, db_session=session,
                                   auth_provider="casdoor", casdoor_initial_role="DEV")


@pytest.mark.asyncio
async def test_non_casdoor_completion_still_requires_password(completion):
    _, create, _, _ = completion
    with pytest.raises(OAuthLinkError, match="Password"):
        await oauth.complete_pending_oauth_account(identity("github"), None, "INVITE")
    create.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_casdoor_invitation_has_no_account_side_effect(completion, mocker):
    mocker.patch.object(oauth, "check_invitation_available", return_value=False)
    _, create, hashed, _ = completion
    with pytest.raises(OAuthLinkError, match="Invitation"):
        await oauth.complete_pending_oauth_account(identity(), None, "INVALID")
    create.assert_not_called()
    hashed.assert_not_called()


@pytest.mark.parametrize("provider,required", [("casdoor", False), ("github", True)])
def test_pending_info_reports_password_requirement_from_trusted_provider(provider, required):
    assert oauth.get_pending_oauth_info(identity(provider))["password_required"] is required


def test_casdoor_only_provider_policy_preserves_existing_local_accounts():
    restricted = {"source_metadata": {"auth_provider": "casdoor"}}
    oauth.require_provider_authentication(restricted, "casdoor")
    with pytest.raises(OAuthLinkError, match="only"):
        oauth.require_provider_authentication(restricted, "github")
    oauth.require_provider_authentication({"source_metadata": {}}, "github")
    with pytest.raises(OAuthLinkError, match="unlink"):
        oauth.require_provider_unlink(restricted, "casdoor")


def test_cas_cannot_auto_link_a_casdoor_only_account(mocker):
    from management.services.permission.identity import cas
    mocker.patch.object(cas, "require_active_account", return_value={
        "source_metadata": {"auth_provider": "casdoor"}
    })
    with pytest.raises(cas.CasAuthenticationError, match="only supports Casdoor"):
        cas._require_cas_account("casdoor-user")


@pytest.fixture
def onboarding(mocker, monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(oauth, "CASDOOR_SIGNUP_TENANT_ID", "business-tenant")
    mocker.patch.object(oauth, "get_all_tenant_ids", return_value=["business-tenant"])
    mocker.patch.object(oauth, "get_db_session", return_value=nullcontext(session))
    for name in ("get_oauth_account_by_provider", "get_soft_deleted_oauth_account"):
        mocker.patch.object(oauth, name, return_value=None)
    mocker.patch.object(oauth, "lock_tenants")
    mocker.patch.object(oauth, "create_account", return_value={"user_id": "new-user"})
    mocker.patch.object(oauth, "insert_user_tenant")
    mocker.patch.object(oauth, "insert_oauth_account")
    return session


def test_first_login_creates_passwordless_user_membership_and_binding_in_one_session(onboarding):
    assert oauth.onboard_casdoor_account("subject", "Member@example.com", "member") == "new-user"
    oauth.create_account.assert_called_once_with("member@example.com", db_session=onboarding, auth_provider="casdoor")
    oauth.insert_user_tenant.assert_called_once_with(
        "new-user", "business-tenant", "USER", "member@example.com", db_session=onboarding
    )
    oauth.insert_oauth_account.assert_called_once_with(
        "new-user", "casdoor", "subject", "member@example.com", "member", "business-tenant", db_session=onboarding
    )


@pytest.mark.parametrize("mode", ["existing", "deleted", "conflict", "missing-email", "missing-tenant"])
def test_first_login_reuses_only_active_subject_bindings_and_rejects_unavailable_signup(
    onboarding, monkeypatch, mode
):
    from contracts.errors.exceptions import AccountConflictError

    email = "member@example.com"
    if mode == "existing":
        oauth.get_oauth_account_by_provider.return_value = {"user_id": "existing"}
        assert oauth.onboard_casdoor_account("subject", email, "member") == "existing"
    else:
        if mode == "deleted":
            oauth.get_soft_deleted_oauth_account.return_value = {"user_id": "deleted"}
        elif mode == "conflict":
            oauth.create_account.side_effect = AccountConflictError("duplicate")
        elif mode == "missing-email":
            email = ""
        else:
            monkeypatch.setattr(oauth, "CASDOOR_SIGNUP_TENANT_ID", "asset_owner_tenant_id")
        with pytest.raises(oauth.CasdoorOnboardingError):
            oauth.onboard_casdoor_account("subject", email, "member")
    oauth.insert_user_tenant.assert_not_called()
    oauth.insert_oauth_account.assert_not_called()
