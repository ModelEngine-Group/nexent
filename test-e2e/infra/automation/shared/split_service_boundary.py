# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise isolated downstream HTTP boundaries with case-owned identity keys."""

from secrets import token_hex
from unittest.mock import Mock

import httpx
import pytest
import requests

from contracts.constants import environment
from gateway.identity.downstream import IDENTITY_HEADER, sign_identity


@pytest.fixture
def split_service_apps(monkeypatch, tmp_path):
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", token_hex(32))
    monkeypatch.setattr(environment, "GATEWAY_AUTH_ENABLED", True)
    monkeypatch.setattr(environment, "TRAJECTORY_ROOT_DIR", str(tmp_path / "trajectory"))

    # SDK import can download optional stopwords. These HTTP probes need only
    # the service applications and make no provider requests.
    with monkeypatch.context() as import_config:
        import_config.setattr(requests, "get", Mock(side_effect=OSError("Network disabled during app import")))
        from management.api.application import app as management_app
        from runtime.api.application import app as runtime_app

    apps = {"management": management_app, "runtime": runtime_app}
    for app in apps.values():
        monkeypatch.setattr(app, "middleware_stack", None)
    return apps


def downstream_client(app, audience: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://{audience}")


def signed_headers(audience: str, method: str, path: str) -> dict[str, str]:
    identity = {"kind": "session", "user_id": "split-test-user", "tenant_id": "split-test-tenant"}
    signature = sign_identity(identity, audience, method, path, b"")
    return {IDENTITY_HEADER: signature}
