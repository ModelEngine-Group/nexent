# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Initial registration redirect contract without executing an OAuth journey."""

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from consts import const as settings
from management.api.identity import oauth as routes
from management.services.permission.identity import casdoor

pytestmark = [pytest.mark.case_id("AUTH-CASDOOR-SIGNUP-D2-001"), pytest.mark.stage("D2")]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "CASDOOR_ENDPOINT", "https://sso.example.test")
    monkeypatch.setattr(settings, "CASDOOR_BACKEND_ENDPOINT", "")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_ID", "synthetic-client")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_SECRET", "synthetic-signup-secret")
    monkeypatch.setattr(casdoor, "JWT_SECRET", "synthetic-signing-secret-with-enough-entropy")
    monkeypatch.setattr(casdoor, "OAUTH_CALLBACK_BASE_URL", "https://app.example.test")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Initial redirects must not call providers or write accounts")

    monkeypatch.setattr(casdoor, "_request_json", forbidden)
    monkeypatch.setattr(routes, "create_or_update_oauth_account", forbidden)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app, base_url="https://app.example.test", follow_redirects=False) as api:
        yield api


@pytest.mark.parametrize("signup,page", [("true", "signup"), ("false", "login"), (None, "login")])
def test_signup_and_login_redirect_contract(client, signup, page):
    params = {"provider": "casdoor"}
    if signup is not None:
        params["signup"] = signup
    response = client.get("/user/oauth/authorize", params=params)
    assert response.status_code == 302
    location = response.headers["location"]
    assert urlparse(location).path == f"/{page}/oauth/authorize"
    query = parse_qs(urlparse(location).query)
    flow = casdoor.validate_flow(query["state"][0], client.cookies[casdoor.FLOW_COOKIE_NAME])
    assert query["redirect_uri"] == ["https://app.example.test/api/user/oauth/callback?provider=casdoor"]
    assert query["client_id"] == ["synthetic-client"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(flow["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [challenge]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "synthetic-signup-secret" not in location
    assert flow["verifier"] not in location
