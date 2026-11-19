# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Casdoor route behavior with isolated account and provider collaborators."""

from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from consts import const as settings
from management.api.identity import oauth as routes
from management.services.permission.identity import casdoor


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "CASDOOR_ENDPOINT", "https://sso.example.test")
    monkeypatch.setattr(settings, "CASDOOR_BACKEND_ENDPOINT", "https://sso.example.test")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_ID", "synthetic-client")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setattr(casdoor, "JWT_SECRET", "synthetic-signing-secret-with-enough-entropy")
    monkeypatch.setattr(casdoor, "OAUTH_CALLBACK_BASE_URL", "https://app.example.test")
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app, base_url="https://app.example.test", follow_redirects=False) as api:
        yield api


def begin(client):
    response = client.get("/user/oauth/authorize?provider=casdoor")
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


def test_authorize_sets_limited_httponly_browser_cookie(client):
    response = client.get("/user/oauth/authorize?provider=casdoor")
    assert response.status_code == 302
    cookie = response.headers["set-cookie"]
    for expected in ["nexent_casdoor_flow=", "HttpOnly", "SameSite=lax", "Secure", "Max-Age=1800"]:
        assert expected in cookie
    assert "synthetic-secret" not in response.text + response.headers["location"]


def test_registration_entry_redirects_to_casdoor_signup(client):
    response = client.get("/user/oauth/authorize?provider=casdoor&signup=true")
    assert response.status_code == 302
    assert urlparse(response.headers["location"]).path == "/signup/oauth/authorize"
    query = parse_qs(urlparse(response.headers["location"]).query)
    flow = casdoor.validate_flow(query["state"][0], client.cookies[casdoor.FLOW_COOKIE_NAME])
    assert flow["link_user_id"] == ""


def test_new_identity_uses_native_session_without_pending_or_email_autolink(client, monkeypatch):
    state = begin(client)
    claims = jwt.decode(
        client.cookies[casdoor.FLOW_COOKIE_NAME], casdoor.JWT_SECRET,
        algorithms=["HS256"], audience="casdoor-login",
    )
    claims["iat"] -= 660
    claims["exp"] = claims["iat"] + casdoor.FLOW_TTL_SECONDS
    client.cookies.set(
        casdoor.FLOW_COOKIE_NAME, jwt.encode(claims, casdoor.JWT_SECRET, algorithm="HS256"), domain="app.example.test"
    )
    monkeypatch.setattr(
        casdoor,
        "authenticate",
        MagicMock(
            return_value={
                "id": "subject-hash",
                "email": "existing@example.test",
                "username": "alice",
            }
        ),
    )
    lookup = MagicMock(return_value=None)
    monkeypatch.setattr(routes, "get_oauth_account_by_provider", lookup)
    email_lookup = MagicMock()
    monkeypatch.setattr(routes, "find_account_user_id_by_email", email_lookup)
    pending = MagicMock(return_value="synthetic-pending")
    monkeypatch.setattr(routes, "generate_pending_oauth_token", pending)
    onboard = MagicMock(return_value="new-user")
    monkeypatch.setattr(routes, "onboard_casdoor_account", onboard)
    monkeypatch.setattr(routes, "require_active_account", lambda user_id: {"source_metadata": {}})
    monkeypatch.setattr(routes, "record_security_event", MagicMock())
    monkeypatch.setattr(routes, "generate_session_jwt", lambda *args, **kwargs: "native-jwt")
    monkeypatch.setattr(routes, "calculate_expires_at", lambda _: 1234)
    response = client.get("/user/oauth/callback", params={"provider": "casdoor", "code": "code", "state": state})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user"]["id"] == "new-user"
    assert data["session"]["access_token"] == "native-jwt"
    assert "requires_account_completion" not in data
    onboard.assert_called_once_with("subject-hash", "existing@example.test", "alice")
    pending.assert_not_called()
    lookup.assert_called_once_with("casdoor", "subject-hash")
    email_lookup.assert_not_called()
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_bound_identity_uses_native_session(client, monkeypatch):
    state = begin(client)
    monkeypatch.setattr(
        casdoor,
        "authenticate",
        MagicMock(
            return_value={
                "id": "subject-hash",
                "email": "member@example.test",
                "username": "alice",
            }
        ),
    )
    monkeypatch.setattr(routes, "get_oauth_account_by_provider", MagicMock(return_value={"user_id": "local-user"}))
    for name in [
        "require_active_account",
        "ensure_user_tenant_exists",
        "create_or_update_oauth_account",
        "record_security_event",
    ]:
        monkeypatch.setattr(routes, name, MagicMock())
    session = MagicMock(return_value="native-jwt")
    monkeypatch.setattr(routes, "generate_session_jwt", session)
    monkeypatch.setattr(routes, "calculate_expires_at", lambda _token: 1234567890)
    response = client.get("/user/oauth/callback", params={"provider": "casdoor", "code": "code", "state": state})
    assert response.status_code == 200
    assert response.json()["data"]["user"]["id"] == "local-user"
    assert response.json()["data"]["session"]["access_token"] == "native-jwt"
    assert session.call_args.args[0] == "local-user"
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_explicit_link_uses_signed_authenticated_user(client, monkeypatch):
    monkeypatch.setattr(routes, "get_current_user_id", lambda _authorization: ("authenticated-user", "tenant"))
    monkeypatch.setattr(routes, "require_active_account", lambda _user_id: {"source_metadata": {}})
    response = client.get("/user/oauth/link?provider=casdoor", headers={"Authorization": "Bearer local-session"})
    assert response.status_code == 302
    assert "Max-Age=600" in response.headers["set-cookie"]
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    monkeypatch.setattr(
        casdoor,
        "authenticate",
        MagicMock(
            return_value={
                "id": "subject-hash",
                "email": "member@example.test",
                "username": "alice",
            }
        ),
    )
    lookup = MagicMock()
    monkeypatch.setattr(routes, "get_oauth_account_by_provider", lookup)
    for name in ["require_active_account", "ensure_user_tenant_exists", "record_security_event"]:
        monkeypatch.setattr(routes, name, MagicMock())
    bind = MagicMock()
    monkeypatch.setattr(routes, "create_or_update_oauth_account", bind)
    monkeypatch.setattr(routes, "generate_session_jwt", lambda *args, **kwargs: "native-jwt")
    monkeypatch.setattr(routes, "calculate_expires_at", lambda _token: 1234567890)
    callback = client.get("/user/oauth/callback", params={"provider": "casdoor", "code": "code", "state": state})
    assert callback.status_code == 200
    assert callback.json()["data"]["user"]["id"] == "authenticated-user"
    assert bind.call_args.kwargs["user_id"] == "authenticated-user"
    lookup.assert_not_called()


def test_link_requires_existing_session(client):
    assert client.get("/user/oauth/link?provider=casdoor").status_code == 401


@pytest.mark.parametrize(
    "params",
    [
        {"code": "code", "state": "unrelated"},
        {"code": "code", "state": ""},
        {"error": "access_denied"},
    ],
)
def test_invalid_callback_never_contacts_provider_or_writes(client, monkeypatch, params):
    provider = MagicMock()
    write = MagicMock()
    monkeypatch.setattr(casdoor, "authenticate", provider)
    monkeypatch.setattr(routes, "create_or_update_oauth_account", write)
    response = client.get("/user/oauth/callback", params={"provider": "casdoor", **params})
    assert response.status_code == 400
    provider.assert_not_called()
    write.assert_not_called()
    assert "Max-Age=0" in response.headers["set-cookie"]


@pytest.mark.parametrize("cookie_available", [True, False])
def test_expired_login_requests_a_fresh_flow_before_any_exchange(client, monkeypatch, cookie_available):
    state = begin(client)
    token = client.cookies[casdoor.FLOW_COOKIE_NAME]
    client.cookies.clear()
    if cookie_available:
        claims = jwt.decode(token, casdoor.JWT_SECRET, algorithms=["HS256"], audience="casdoor-login")
        claims["exp"] = 0
        client.cookies.set(casdoor.FLOW_COOKIE_NAME, jwt.encode(claims, casdoor.JWT_SECRET, algorithm="HS256"))
    authenticate = MagicMock()
    monkeypatch.setattr(casdoor, "authenticate", authenticate)
    response = client.get("/user/oauth/callback", params={"provider": "casdoor", "code": "code", "state": state})
    assert response.status_code == 400
    assert response.json()["data"]["oauth_error"] == "casdoor_flow_expired"
    authenticate.assert_not_called()
    assert begin(client) != state
