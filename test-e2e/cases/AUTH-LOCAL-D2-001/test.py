# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""D2: real HTTP router, credentials/JWTs and PostgreSQL without GoTrue."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import jwt
import pytest

pytestmark = [pytest.mark.case_id("AUTH-LOCAL-D2-001"), pytest.mark.stage("D2")]
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test-e2e/infra/automation"))


from local_auth_http import native_runtime, runtime, register, bearer  # noqa: F401


def test_native_http_identity_password_and_api_keys(runtime):
    client, auth, helpers, models = runtime
    from gateway.authentication import northbound_auth as northbound
    assert client.get("/api/user/service_health").status_code == 200
    data = register(client)
    token = data["session"]["access_token"]
    assert data["session"]["refresh_token"] == ""
    assert (
        client.get("/api/user/current_user_id", headers=bearer(token)).json()["data"][
            "user_id"
        ]
        == data["user"]["id"]
    )
    profile = client.get("/api/user/current_user_info", headers=bearer(token))
    assert profile.status_code == 200, profile.text
    assert profile.json()["data"]["user"]["tenant_id"] == "tenant-native"
    from management.db.identity.user_tenant import update_user_tenant_role
    from management.db.identity.account import get_account

    assert update_user_tenant_role(data["user"]["id"], "DEV", data["user"]["id"])
    assert get_account(data["user"]["id"])["user_role"] == "DEV"
    updated_profile = client.get("/api/user/current_user_info", headers=bearer(token)).json()
    assert updated_profile["data"]["user"]["user_role"] == "DEV"
    assert {"user_role", "user_email"}.isdisjoint(models.UserTenant.__table__.columns.keys())

    assert client.get("/api/user/session", headers=bearer(token)).status_code == 200
    key_response = client.post("/api/user/tokens", headers=bearer(token))
    assert key_response.status_code == 200, key_response.text
    key = key_response.json()["data"]
    assert (
        client.delete(
            "/api/user/tokens/" + str(key["token_id"]), headers=bearer(token)
        ).status_code
        == 200
    )
    assert not northbound.validate_bearer_token(key["access_key"])[0]
    changed = client.put(
        "/api/user/password",
        headers=bearer(token),
        json={"old_password": "Password123", "new_password": "NewPassword456"},
    )
    assert changed.status_code == 200, changed.text
    assert (
        client.get("/api/user/current_user_id", headers=bearer(token)).status_code
        == 401
    )
    assert (
        client.post(
            "/api/user/signin",
            json={"email": "native@example.com", "password": "Password123"},
        ).status_code
        == 401
    )
    signin = client.post(
        "/api/user/signin",
        json={"email": "native@example.com", "password": "NewPassword456"},
    )
    assert signin.status_code == 200, signin.text
    assert signin.json()["data"]["user"]["id"] == data["user"]["id"]
    assert "password_hash" not in signin.text
    assert "NewPassword456" not in signin.text


def test_native_http_invalid_duplicate_disabled_and_refresh(runtime):
    client, auth, helpers, models = runtime
    from gateway.authentication import northbound_auth as northbound
    data = register(client)
    token = data["session"]["access_token"]
    duplicate = client.post(
        "/api/user/signup",
        json={
            "email": "Native@example.com",
            "password": "Password123",
            "invite_code": "NATIVE-INVITE",
        },
    )
    assert duplicate.status_code == 409, duplicate.text
    assert (
        client.post(
            "/api/user/signin",
            json={"email": "native@example.com", "password": "wrong"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/user/refresh_token",
            headers=bearer(token),
            json={"refresh_token": "retired-credential"},
        ).status_code
        == 401
    )
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["exp"] = claims["iat"] - 1
    expired = jwt.encode(claims, helpers.JWT_SECRET, algorithm="HS256")
    assert (
        client.get("/api/user/current_user_id", headers=bearer(expired)).status_code
        == 401
    )
    assert (
        client.get(
            "/api/user/current_user_id", headers=bearer(token + "corrupt")
        ).status_code
        == 401
    )
    from management.db.client import get_db_session

    with get_db_session() as session:
        session.execute(
            models.UserAccount.__table__.update().values(account_status="disabled")
        )
    assert (
        client.get("/api/user/current_user_info", headers=bearer(token)).status_code
        == 401
    )
    assert (
        client.post(
            "/api/user/signin",
            json={"email": "native@example.com", "password": "Password123"},
        ).status_code
        == 401
    )


def test_native_http_cas_sid_revocation_remains_effective(runtime):
    client, auth, helpers, models = runtime
    from gateway.authentication import northbound_auth as northbound
    data = register(client)
    user_id = data["user"]["id"]
    from management.db.client import get_db_session

    with get_db_session() as session:
        session.add(
            models.UserCasSession(
                session_id="native-cas",
                user_id=user_id,
                cas_user_id="cas-user",
                cas_session_index="ST-native",
                status="active",
                expires_at=datetime.now() + timedelta(hours=1),
                delete_flag="N",
                created_by=user_id,
                updated_by=user_id,
            )
        )
    token = helpers.generate_session_jwt(user_id, session_id="native-cas")
    assert (
        client.get("/api/user/current_user_id", headers=bearer(token)).status_code
        == 200
    )
    with get_db_session() as session:
        session.execute(
            models.UserCasSession.__table__.update().values(status="revoked")
        )
    assert (
        client.get("/api/user/current_user_id", headers=bearer(token)).status_code
        == 401
    )


def test_native_account_bootstrap_and_cas_provisioning(runtime):
    client, auth, helpers, models = runtime
    from gateway.authentication import northbound_auth as northbound
    from infrastructure.security.account_cli import bootstrap_super_admin
    from contracts.errors.exceptions import AccountConflictError
    from management.db.identity.account import get_account_by_email
    from infrastructure.security.passwords import verify_password
    from management.services.permission.identity.cas import (
        CasPrincipal,
        _resolve_project_user,
    )

    assert bootstrap_super_admin("suadmin@nexent.com", "", check_only=True) == {
        "exists": False
    }
    assert bootstrap_super_admin("suadmin@nexent.com", "BootstrapPass123") == {
        "created": True
    }
    assert bootstrap_super_admin("suadmin@nexent.com", "DifferentPass123") == {
        "exists": True
    }
    with pytest.raises(AccountConflictError, match="migrate.py --apply"):
        bootstrap_super_admin("another-su@example.com", "", check_only=True)
    account = get_account_by_email("suadmin@nexent.com")
    assert verify_password("BootstrapPass123", account["password_hash"])
    data = register(client)
    with pytest.raises(AccountConflictError):
        bootstrap_super_admin("native@example.com", "Password123")
    principal = CasPrincipal(
        "cas-first",
        "cas-first@example.com",
        "CAS First",
        "USER",
        "tenant-native",
        "ST-first",
        datetime.now() + timedelta(hours=1),
    )
    first = _resolve_project_user(principal)
    assert _resolve_project_user(principal) == first
    cas_account = get_account_by_email(principal.email)
    assert cas_account["user_id"] == first
    assert cas_account["password_hash"] is None
    assert not cas_account["password_login_enabled"]


def test_native_http_revoke_disables_credentials_and_api_keys(runtime):
    client, auth, helpers, models = runtime
    from gateway.authentication import northbound_auth as northbound
    data = register(client)
    token = data["session"]["access_token"]
    issued_key = client.post("/api/user/tokens", headers=bearer(token))
    assert issued_key.status_code == 200
    key = issued_key.json()["data"]["access_key"]
    assert northbound.validate_bearer_token(key)[0]
    response = client.post("/api/user/revoke", headers=bearer(token))
    assert response.status_code == 200, response.text
    assert (
        client.get("/api/user/current_user_id", headers=bearer(token)).status_code
        == 401
    )
    assert not northbound.validate_bearer_token(key)[0]
    assert (
        client.post(
            "/api/user/signin",
            json={"email": "native@example.com", "password": "Password123"},
        ).status_code
        == 401
    )
