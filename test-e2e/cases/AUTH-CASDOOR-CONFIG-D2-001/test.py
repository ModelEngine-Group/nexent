# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public Casdoor metadata contract through the actual Nexent HTTP routes."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from consts import const as settings
from management.api.identity import oauth as routes
from management.services.permission.identity import casdoor
from management.services.permission.identity import oauth as service
from management.utils import oauth_providers

pytestmark = [pytest.mark.case_id("AUTH-CASDOOR-CONFIG-D2-001"), pytest.mark.stage("D2")]


@pytest.fixture
def client(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Public configuration must not contact a provider or write accounts")

    monkeypatch.setattr(casdoor, "_request_json", forbidden)
    monkeypatch.setattr(routes, "create_or_update_oauth_account", forbidden)
    monkeypatch.setattr(routes, "generate_pending_oauth_token", forbidden)
    monkeypatch.setattr(routes, "exchange_code_for_provider_token", forbidden)
    monkeypatch.setattr(settings, "CASDOOR_ENDPOINT", "https://sso.example.test")
    monkeypatch.setattr(settings, "CASDOOR_BACKEND_ENDPOINT", "")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_ID", "synthetic-client")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_SECRET", "synthetic-contract-secret")
    monkeypatch.setattr(oauth_providers, "get_oauth_setting", lambda _name, default="": default)
    monkeypatch.setattr(service, "OAUTH_LOGIN_MODE", "button")
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    with TestClient(app) as api:
        yield api


def test_public_casdoor_configuration(client):
    config = client.get("/api/user/oauth/config")
    providers = client.get("/api/user/oauth/providers")
    assert config.status_code == providers.status_code == 200
    expected = {"name": "casdoor", "display_name": "Casdoor", "icon": "casdoor", "enabled": True}
    assert config.json() == {
        "message": "success",
        "data": {
            "enabled": True,
            "login_mode": "button",
            "auto_login_provider": None,
            "providers": [expected],
        },
    }
    assert providers.json() == {"message": "success", "data": [expected]}
    assert "synthetic-contract-secret" not in config.text + providers.text
    assert "client_secret" not in config.text + providers.text


@pytest.mark.parametrize(
    "setting,value",
    [
        ("CASDOOR_CLIENT_ID", ""),
        ("CASDOOR_CLIENT_SECRET", ""),
        ("CASDOOR_ENDPOINT", ""),
        ("CASDOOR_ENDPOINT", "not-a-url"),
        ("CASDOOR_BACKEND_ENDPOINT", "https://user:secret@example.test"),
    ],
)
def test_incomplete_casdoor_configuration(client, monkeypatch, setting, value):
    monkeypatch.setattr(settings, setting, value)
    response = client.get("/api/user/oauth/config")
    assert response.status_code == 200
    assert response.json()["data"] == {
        "enabled": False,
        "login_mode": "disabled",
        "auto_login_provider": None,
        "providers": [],
    }
    assert client.get("/api/user/oauth/providers").json()["data"] == []
    assert "synthetic-contract-secret" not in response.text


@pytest.mark.parametrize("mode,auto", [("disabled", None), ("force", "casdoor")])
def test_casdoor_login_modes(client, monkeypatch, mode, auto):
    monkeypatch.setattr(service, "OAUTH_LOGIN_MODE", mode)
    response = client.get("/api/user/oauth/config")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["login_mode"] == mode
    assert data["auto_login_provider"] == auto
    assert data["providers"][0]["name"] == "casdoor"
    assert "synthetic-contract-secret" not in response.text
