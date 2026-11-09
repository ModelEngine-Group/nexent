# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Passwordless Casdoor onboarding and login restrictions through HTTP and PostgreSQL."""

from unittest.mock import AsyncMock

import pytest

from local_auth_http import native_runtime, runtime

pytestmark = [pytest.mark.case_id("AUTH-CASDOOR-PASSWORDLESS-D2-001"), pytest.mark.stage("D2")]


@pytest.fixture
def api(runtime, monkeypatch):
    client, _, _, _ = runtime
    from consts import const as settings
    from management.api.identity import oauth as routes
    from management.services.permission.identity import oauth
    from management.services.tool import configuration

    if not getattr(client.app.state, "casdoor_routes_added", False):
        client.app.include_router(routes.router, prefix="/api")
        client.app.state.casdoor_routes_added = True
    monkeypatch.setattr(routes, "record_security_event", lambda *a, **kw: None)
    monkeypatch.setattr(settings, "CASDOOR_ROLE_MAP_JSON", "")
    monkeypatch.setattr(configuration, "init_tool_list_for_tenant", AsyncMock())
    return client, oauth


def pending(oauth, email, provider="casdoor"):
    return {"X-OAuth-Pending-Token": oauth.generate_pending_oauth_token(
        provider, "subject-" + email, email, "Synthetic member"
    )}


def assert_passwordless(email):
    from management.db.identity.account import get_account_by_email
    account = get_account_by_email(email)
    assert account["password_hash"] is None
    assert account["password_hash_scheme"] is None
    assert account["password_login_enabled"] is False
    assert account["source_metadata"] == {"auth_provider": "casdoor"}
    return account


def test_passwordless_completion_and_provider_policy(api, monkeypatch):
    client, oauth = api
    headers = pending(oauth, "member@example.com")
    info = client.get("/api/user/oauth/pending", headers=headers)
    assert info.json()["data"]["password_required"] is False
    response = client.post("/api/user/oauth/complete", headers=headers,
                           json={"invite_code": "NATIVE-INVITE"})
    assert response.status_code == 200
    data = response.json()["data"]
    account = assert_passwordless("member@example.com")
    user_id = account["user_id"]
    assert data["user"]["id"] == user_id
    assert data["user"]["role"] == "USER"
    authorization = {"Authorization": "Bearer " + data["session"]["access_token"]}
    assert client.get("/api/user/session", headers=authorization).status_code == 200
    from management.db.identity.user_tenant import get_user_tenant_by_user_id
    from management.db.identity.oauth_account import get_oauth_account_by_provider
    assert get_user_tenant_by_user_id(user_id)["tenant_id"] == "tenant-native"
    assert get_oauth_account_by_provider("casdoor", "subject-member@example.com")["user_id"] == user_id
    assert client.post("/api/user/signin", json={
        "email": "member@example.com", "password": "CasdoorPassword123"
    }).status_code == 401
    assert client.put("/api/user/password", headers=authorization, json={
        "old_password": "CasdoorPassword123", "new_password": "NewPassword456"
    }).status_code == 400
    assert client.get("/api/user/oauth/link?provider=github", headers=authorization).status_code == 400
    assert client.delete("/api/user/oauth/accounts/casdoor", headers=authorization).status_code == 400

    # Control only external provider claims, retaining actual callback policy and persistence.
    from management.api.identity import oauth as routes
    monkeypatch.setattr(routes, "parse_state", lambda _: {})
    monkeypatch.setattr(routes, "exchange_code_for_provider_token", lambda *a: {"access_token": "synthetic"})
    monkeypatch.setattr(routes, "get_provider_user_info", lambda *a, **kw: {
        "id": "alternate-subject", "email": "member@example.com", "username": "Alternate"
    })
    rejected = client.get("/api/user/oauth/callback?provider=github&code=synthetic&state=synthetic")
    assert rejected.status_code == 400
    assert get_oauth_account_by_provider("github", "alternate-subject") is None
    monkeypatch.setattr(routes.casdoor, "validate_flow", lambda *a: {})
    monkeypatch.setattr(routes.casdoor, "authenticate", lambda *a: {
        "id": "subject-member@example.com", "email": "member@example.com", "username": "Synthetic member"
    })
    login = client.get("/api/user/oauth/callback?provider=casdoor&code=synthetic&state=synthetic")
    assert login.status_code == 200
    assert login.json()["data"]["user"]["id"] == user_id
    assert client.get("/api/user/session", headers={
        "Authorization": "Bearer " + login.json()["data"]["session"]["access_token"]
    }).status_code == 200
    assert_passwordless("member@example.com")
    assert get_oauth_account_by_provider("casdoor", "subject-member@example.com")["user_id"] == user_id


def test_completion_input_boundaries(api):
    client, oauth = api
    injected = client.post("/api/user/oauth/complete", headers=pending(oauth, "injected@example.com"),
                           json={"invite_code": "NATIVE-INVITE", "password": "InjectedPassword123"})
    assert injected.status_code == 200
    assert_passwordless("injected@example.com")
    assert client.post("/api/user/signin", json={
        "email": "injected@example.com", "password": "InjectedPassword123"
    }).status_code == 401
    rejected = client.post("/api/user/oauth/complete", headers=pending(oauth, "invalid@example.com"),
                           json={"invite_code": "INVALID"})
    assert rejected.status_code == 400
    from management.db.identity.account import get_account_by_email
    assert get_account_by_email("invalid@example.com") is None
    legacy = client.post("/api/user/oauth/complete", headers=pending(oauth, "legacy@example.com", "github"),
                         json={"invite_code": "NATIVE-INVITE"})
    assert legacy.status_code == 422
    assert get_account_by_email("legacy@example.com") is None
