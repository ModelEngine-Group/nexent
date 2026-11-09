# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Casdoor configuration, browser-flow and provider boundary unit tests."""

import base64
import hashlib
import json
import urllib.error
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import jwt
import pytest

from consts import const as settings
from contracts.errors.exceptions import OAuthProviderError
from management.services.permission.identity import casdoor
from management.utils import oauth_providers


@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    monkeypatch.setattr(settings, "CASDOOR_ENDPOINT", "https://sso.example.test")
    monkeypatch.setattr(settings, "CASDOOR_BACKEND_ENDPOINT", "http://casdoor:8000")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_ID", "synthetic-client")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_SECRET", "synthetic-private-secret")
    monkeypatch.setattr(casdoor, "JWT_SECRET", "synthetic-signing-secret-with-enough-entropy")
    monkeypatch.setattr(casdoor, "OAUTH_CALLBACK_BASE_URL", "https://app.example.test/nexent")


def test_configuration_enables_provider():
    assert settings.is_casdoor_enabled()
    definition = oauth_providers.get_provider_definition("casdoor")
    assert definition.display_name == "Casdoor"
    assert oauth_providers.is_provider_enabled(definition)


@pytest.mark.parametrize(
    "name,value",
    [
        ("CASDOOR_ENDPOINT", ""),
        ("CASDOOR_ENDPOINT", "sso.example.test"),
        ("CASDOOR_ENDPOINT", "ftp://sso.example.test"),
        ("CASDOOR_ENDPOINT", "https://user:password@sso.example.test"),
        ("CASDOOR_ENDPOINT", "https://sso.example.test?query=1"),
        ("CASDOOR_BACKEND_ENDPOINT", "http://casdoor:bad"),
        ("CASDOOR_CLIENT_ID", ""),
        ("CASDOOR_CLIENT_SECRET", ""),
    ],
)
def test_incomplete_or_invalid_configuration_is_disabled(monkeypatch, name, value):
    monkeypatch.setattr(settings, name, value)
    assert not settings.is_casdoor_enabled()
    with pytest.raises(OAuthProviderError):
        casdoor.create_authorization()


def test_authorization_uses_pkce_callback_and_signed_flow():
    url, cookie = casdoor.create_authorization(link_user_id="local-user")
    query = parse_qs(urlparse(url).query)
    flow = casdoor.validate_flow(query["state"][0], cookie)
    assert url.startswith("https://sso.example.test/login/oauth/authorize?")
    assert query["redirect_uri"] == ["https://app.example.test/nexent/api/user/oauth/callback?provider=casdoor"]
    assert query["client_id"] == ["synthetic-client"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid profile email"]
    assert query["code_challenge_method"] == ["S256"]
    expected = base64.urlsafe_b64encode(hashlib.sha256(flow["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [expected]
    assert flow["link_user_id"] == "local-user"
    assert "synthetic-private-secret" not in url
    assert flow["verifier"] not in url
    other_url, other_cookie = casdoor.create_authorization()
    assert other_url != url and other_cookie != cookie


def test_signup_authorization_preserves_browser_flow_security():
    url, cookie = casdoor.create_authorization(signup=True)
    query = parse_qs(urlparse(url).query)
    assert urlparse(url).path == "/signup/oauth/authorize"
    flow = casdoor.validate_flow(query["state"][0], cookie)
    expected = base64.urlsafe_b64encode(hashlib.sha256(flow["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [expected]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["https://app.example.test/nexent/api/user/oauth/callback?provider=casdoor"]
    assert flow["link_user_id"] == ""


@pytest.mark.parametrize("condition", ["missing", "tampered", "expired", "mismatch", "purpose", "other_browser"])
def test_invalid_browser_flow_is_rejected(condition):
    url, cookie = casdoor.create_authorization()
    state = parse_qs(urlparse(url).query)["state"][0]
    if condition == "missing":
        cookie = ""
    elif condition == "tampered":
        cookie = "invalid." + cookie
    elif condition in {"expired", "purpose"}:
        claims = jwt.decode(cookie, casdoor.JWT_SECRET, algorithms=["HS256"], audience="casdoor-login")
        claims["exp" if condition == "expired" else "aud"] = 0 if condition == "expired" else "another-purpose"
        cookie = jwt.encode(claims, casdoor.JWT_SECRET, algorithm="HS256")
    elif condition == "mismatch":
        state = "unrelated-state"
    else:
        _, cookie = casdoor.create_authorization()
    with pytest.raises(OAuthProviderError, match="flow"):
        casdoor.validate_flow(state, cookie)


def test_authenticate_exchanges_form_and_maps_stable_identity(monkeypatch):
    responses = [
        {"access_token": "synthetic-access"},
        {
            "sub": "subject-1",
            "email": "new@example.test",
            "preferred_username": "alice",
        },
    ]
    request = MagicMock(side_effect=responses)
    monkeypatch.setattr(casdoor, "_request_json", request)
    identity = casdoor.authenticate("authorization-code", {"verifier": "test-verifier"})
    assert identity == {
        "id": hashlib.sha256(b"https://sso.example.test\0subject-1").hexdigest(),
        "email": "new@example.test",
        "username": "alice",
    }
    token_call, user_call = request.call_args_list
    assert token_call.args == ("http://casdoor:8000/api/login/oauth/access_token",)
    assert token_call.kwargs["data"] == {
        "grant_type": "authorization_code",
        "client_id": "synthetic-client",
        "client_secret": "synthetic-private-secret",
        "code": "authorization-code",
        "redirect_uri": "https://app.example.test/nexent/api/user/oauth/callback?provider=casdoor",
        "code_verifier": "test-verifier",
    }
    assert user_call.args == ("http://casdoor:8000/api/userinfo",)
    assert user_call.kwargs["headers"] == {"Authorization": "Bearer synthetic-access"}


@pytest.mark.parametrize(
    "responses",
    [
        [{"error": "invalid_grant", "error_description": "synthetic-private-secret"}],
        [{"access_token": ""}],
        [{"access_token": "synthetic-access"}, {"email": "new@example.test"}],
        [{"access_token": "synthetic-access"}, {"sub": ""}],
    ],
)
def test_invalid_provider_payload_is_rejected_without_secret(monkeypatch, responses):
    monkeypatch.setattr(casdoor, "_request_json", MagicMock(side_effect=responses))
    with pytest.raises(OAuthProviderError) as error:
        casdoor.authenticate("authorization-code", {"verifier": "test-verifier"})
    assert "synthetic-private-secret" not in str(error.value)


def test_subject_is_scoped_to_endpoint(monkeypatch):
    monkeypatch.setattr(
        casdoor,
        "_request_json",
        MagicMock(
            side_effect=[
                {"access_token": "synthetic-access"},
                {"sub": "same-subject"},
                {"access_token": "synthetic-access"},
                {"sub": "same-subject"},
            ]
        ),
    )
    first = casdoor.authenticate("code", {"verifier": "verifier"})
    monkeypatch.setattr(settings, "CASDOOR_ENDPOINT", "https://other.example.test")
    second = casdoor.authenticate("code", {"verifier": "verifier"})
    assert first["id"] != second["id"]
    assert first["email"] == first["username"] == ""


def test_http_helper_form_encoding(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({"access_token": "value"}).encode()
    open_url = MagicMock(return_value=response)
    monkeypatch.setattr(casdoor.urllib.request, "urlopen", open_url)
    assert casdoor._request_json("https://sso.example.test/token", data={"code": "a+b&c"}) == {"access_token": "value"}
    request = open_url.call_args.args[0]
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/x-www-form-urlencoded"
    assert parse_qs(request.data.decode()) == {"code": ["a+b&c"]}


def test_http_helper_hides_provider_transport_errors(monkeypatch):
    monkeypatch.setattr(
        casdoor.urllib.request,
        "urlopen",
        MagicMock(
            side_effect=urllib.error.URLError("synthetic-private-secret"),
        ),
    )
    with pytest.raises(OAuthProviderError, match="request failed") as error:
        casdoor._request_json("https://sso.example.test/token", data={"client_secret": "synthetic-private-secret"})
    assert "synthetic-private-secret" not in str(error.value)
