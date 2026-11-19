# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Passwordless Casdoor onboarding and login restrictions through HTTP and PostgreSQL."""

from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from local_auth_http import native_runtime, runtime

pytestmark = [pytest.mark.case_id("AUTH-CASDOOR-PASSWORDLESS-D2-001"), pytest.mark.stage("D2")]


@pytest.fixture
def api(runtime, monkeypatch):
    client, _, _, _ = runtime
    from consts import const as settings
    from management.api.identity import oauth as routes
    from management.services.permission.identity import oauth

    if not getattr(client.app.state, "casdoor_routes_added", False):
        client.app.include_router(routes.router, prefix="/api")
        client.app.state.casdoor_routes_added = True
    monkeypatch.setattr(routes, "record_security_event", lambda *a, **kw: None)
    monkeypatch.setattr(settings, "CASDOOR_ROLE_MAP_JSON", "")
    monkeypatch.setattr(oauth, "init_tool_list_for_tenant", AsyncMock())
    monkeypatch.setattr(oauth, "CASDOOR_SIGNUP_TENANT_ID", "tenant-native")
    monkeypatch.setattr(routes.casdoor, "OAUTH_CALLBACK_BASE_URL", "http://testserver")
    for name, value in {
        "CASDOOR_ENDPOINT": "https://door.example.test",
        "CASDOOR_BACKEND_ENDPOINT": "",
        "CASDOOR_CLIENT_ID": "test-client",
        "CASDOOR_CLIENT_SECRET": "synthetic-secret",
    }.items():
        monkeypatch.setattr(settings, name, value)
    from management.db.identity.account import create_account
    from management.db.identity.user_tenant import insert_user_tenant

    administrator = create_account("admin@example.com")
    insert_user_tenant(administrator["user_id"], "tenant-native", "ADMIN", administrator["email"])
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


def begin(client):
    response = client.get("/api/user/oauth/authorize", params={"provider": "casdoor"}, follow_redirects=False)
    assert response.status_code == 302
    assert "Max-Age=1800" in response.headers["set-cookie"]
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


def callback(client, state):
    return client.get(
        "/api/user/oauth/callback", params={"provider": "casdoor", "code": "synthetic", "state": state}
    )


def test_passwordless_completion_and_provider_policy(api, monkeypatch):
    client, oauth = api
    from management.api.identity import oauth as routes
    monkeypatch.setattr(routes.casdoor, "authenticate", lambda *a: {
        "id": "subject-member@example.com", "email": "member@example.com", "username": "Synthetic member",
    })
    response = callback(client, begin(client))
    assert response.status_code == 200
    data = response.json()["data"]
    account = assert_passwordless("member@example.com")
    user_id = account["user_id"]
    assert data["user"]["id"] == user_id
    assert "pending_token" not in data and "requires_account_completion" not in data
    authorization = {"Authorization": "Bearer " + data["session"]["access_token"]}
    assert client.get("/api/user/session", headers=authorization).status_code == 200
    from management.db.identity.user_tenant import get_user_tenant_by_user_id
    from management.db.identity.oauth_account import get_oauth_account_by_provider
    membership = get_user_tenant_by_user_id(user_id)
    assert membership["tenant_id"] == "tenant-native"
    assert membership["roles"] == ["USER"]
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
    monkeypatch.setattr(routes, "parse_state", lambda _: {})
    monkeypatch.setattr(routes, "exchange_code_for_provider_token", lambda *a: {"access_token": "synthetic"})
    monkeypatch.setattr(routes, "get_provider_user_info", lambda *a, **kw: {
        "id": "alternate-subject", "email": "member@example.com", "username": "Alternate"
    })
    rejected = client.get("/api/user/oauth/callback?provider=github&code=synthetic&state=synthetic")
    assert rejected.status_code == 400
    assert get_oauth_account_by_provider("github", "alternate-subject") is None
    login = callback(client, begin(client))
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


def test_expired_or_unusable_identity_cannot_provision(api, monkeypatch):
    from unittest.mock import Mock

    from management.api.identity import oauth as routes
    from management.db.identity.oauth_account import get_oauth_account_by_provider

    client, _ = api
    exchange = Mock(return_value={"id": "unbound-subject", "email": "", "username": "member"})
    monkeypatch.setattr(routes.casdoor, "authenticate", exchange)
    stale = begin(client)
    client.cookies.clear()
    expired = callback(client, stale)
    assert expired.status_code == 400
    assert expired.json()["data"]["oauth_error"] == "casdoor_flow_expired"
    exchange.assert_not_called()
    fresh = begin(client)
    assert fresh != stale
    assert callback(client, fresh).json()["data"]["oauth_error"] == "casdoor_email_required"
    exchange.return_value["email"] = "admin@example.com"
    assert callback(client, begin(client)).json()["data"]["oauth_error"] == "casdoor_email_conflict"
    assert get_oauth_account_by_provider("casdoor", "unbound-subject") is None
