# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Casdoor-only completion and provider policy unit regressions."""

from contextlib import nullcontext
from unittest.mock import AsyncMock, MagicMock

import pytest

from contracts.errors.exceptions import OAuthLinkError
from management.services.permission.identity import oauth


@pytest.fixture
def completion(mocker):
    mocker.patch("consts.const.is_casdoor_role_sync_configured", return_value=False)
    from gateway.authentication import auth as gateway
    from infrastructure.security import passwords
    from management.db import client
    from management.db.identity import account
    from management.services.permission.identity import invitations
    from management.services.tool import configuration

    session = MagicMock()
    mocker.patch.object(client, "get_db_session", return_value=nullcontext(session))
    create = mocker.patch.object(account, "create_account", return_value={"user_id": "new-user"})
    hashed = mocker.patch.object(passwords, "hash_password", return_value="hashed-local-password")
    mocker.patch.object(oauth, "get_oauth_account_by_provider", return_value=None)
    mocker.patch.object(oauth, "find_account_user_id_by_email", return_value=None)
    mocker.patch.object(oauth, "insert_user_tenant")
    mocker.patch.object(oauth, "create_or_update_oauth_account")
    mocker.patch.object(invitations, "check_invitation_available", return_value=True)
    mocker.patch.object(invitations, "get_invitation_by_code", return_value={"tenant_id": "tenant", "code_type": "USER_INVITE"})
    mocker.patch.object(invitations, "use_invitation_code", return_value={"group_ids": []})
    mocker.patch.object(configuration, "init_tool_list_for_tenant", new_callable=AsyncMock)
    mocker.patch.object(gateway, "generate_session_jwt", return_value="synthetic-session")
    mocker.patch.object(gateway, "calculate_expires_at", return_value=12345)
    return session, create, hashed


def identity(provider="casdoor"):
    return {"provider": provider, "provider_user_id": "subject", "provider_email": "member@example.com"}


@pytest.mark.parametrize("password", [None, "", "InjectedPassword123"])
@pytest.mark.asyncio
async def test_casdoor_completion_never_hashes_or_stores_a_local_password(completion, password):
    session, create, hashed = completion
    result = await oauth.complete_pending_oauth_account(identity(), password, "INVITE")
    assert result["session"]["access_token"] == "synthetic-session"
    create.assert_called_once_with("member@example.com", None, db_session=session, auth_provider="casdoor")
    hashed.assert_not_called()


@pytest.mark.asyncio
async def test_configured_casdoor_signup_records_invited_role_for_provisioning(completion, mocker):
    from consts import const as settings
    from management.services.permission.identity import invitations

    settings.is_casdoor_role_sync_configured.return_value = True
    mocker.patch.object(settings, "CASDOOR_ROLE_MAP_JSON", '{"nexent-developer":"DEV"}')
    mocker.patch.object(invitations, "get_invitation_by_code", return_value={
        "tenant_id": "tenant", "code_type": "DEV_INVITE",
    })
    session, create, _ = completion
    await oauth.complete_pending_oauth_account(identity(), None, "INVITE")
    create.assert_called_once_with("member@example.com", None, db_session=session,
                                   auth_provider="casdoor", casdoor_initial_role="DEV")


@pytest.mark.asyncio
async def test_non_casdoor_completion_still_requires_password(completion):
    _, create, _ = completion
    with pytest.raises(OAuthLinkError, match="Password"):
        await oauth.complete_pending_oauth_account(identity("github"), None, "INVITE")
    create.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_casdoor_invitation_has_no_account_side_effect(completion, mocker):
    from management.services.permission.identity import invitations
    mocker.patch.object(invitations, "check_invitation_available", return_value=False)
    _, create, hashed = completion
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
