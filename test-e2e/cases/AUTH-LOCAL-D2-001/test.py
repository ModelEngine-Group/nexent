# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""D2: real HTTP router, credentials/JWTs and PostgreSQL without GoTrue."""

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import jwt
import pytest

pytestmark = [pytest.mark.case_id("AUTH-LOCAL-D2-001"), pytest.mark.stage("D2")]
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test-e2e/infra/automation"))


from local_auth_http import native_runtime, runtime, register, bearer, seed_membership_roles  # noqa: F401


def test_api_only_batch_http_and_atomic_rollback(runtime, monkeypatch):
    from sqlalchemy import select, func
    from infrastructure.rdb.client import get_db_session
    from management.db.identity.token import create_token
    from management.db.identity.user_tenant import update_user_tenant_role
    from management.services.permission import api_keys
    from management.api import northbound as routes
    from management.services.permission.identity import northbound as northbound_auth

    client, auth, helpers, models = runtime
    client.app.include_router(routes.router)
    monkeypatch.setattr(routes, "record_security_event", lambda *a, **kw: None)
    admin = register(client)["user"]["id"]
    assert seed_membership_roles(admin, ["ADMIN"])
    admin_key = create_token("nexent-local-admin-key", admin)["access_key"]
    with get_db_session() as session:
        group = models.TenantGroupInfo(tenant_id="tenant-native", group_name="API-only regression", created_by=admin, updated_by=admin)
        session.add(group)
        session.flush()
        group_id = group.group_id
    response = client.post("/nb/v1/api-users/batch", headers=bearer(admin_key), json={"role": "DEV", "group_id": group_id, "count": 2})
    assert response.status_code == 201, response.text
    users = response.json()["data"]
    assert len(users) == 2 and len({u["user_id"] for u in users}) == 2
    for user in users:
        assert northbound_auth.validate_bearer_token(user["api_key"])[0]
        with get_db_session() as session:
            account = session.execute(select(models.UserAccount).where(models.UserAccount.user_id == user["user_id"])).scalar_one()
            assert account.delete_flag == "N" and account.user_roles == ["DEV"]
            assert account.user_email is account.password_hash is account.email_confirmed_at is None
            assert not account.password_login_enabled
            assert session.query(models.TenantGroupUser).filter_by(user_id=user["user_id"], group_id=group_id).count() == 1
    assert client.post("/api/user/signin", json={"email": "", "password": "Password123"}).status_code in {401, 422}

    measured = [models.UserAccount, models.UserTenant, models.UserTokenInfo, models.TenantGroupUser]
    def counts():
        with get_db_session() as session:
            return [session.execute(select(func.count()).select_from(model)).scalar_one() for model in measured]
    before = counts()
    real_create = api_keys.create_token
    writes = []
    def fail_second(*args, **kwargs):
        writes.append(args)
        if len(writes) == 2:
            raise RuntimeError("synthetic second-key failure")
        return real_create(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(api_keys, "create_token", fail_second)
        with pytest.raises(RuntimeError, match="second-key failure"):
            client.post("/nb/v1/api-users/batch", headers=bearer(admin_key), json={"role": "USER", "group_id": group_id, "count": 2})
    assert counts() == before
    refreshed = client.post("/nb/v1/api-keys/refresh", headers=bearer(admin_key), json={"user_id": users[0]["user_id"]})
    assert refreshed.status_code == 200, refreshed.text
    current_key = refreshed.json()["data"]["api_key"]
    assert northbound_auth.validate_bearer_token(current_key)[0]
    assert not northbound_auth.validate_bearer_token(users[0]["api_key"])[0]
    for state in ["disabled", "deleted"]:
        with get_db_session() as session:
            account = session.execute(select(models.UserAccount).where(models.UserAccount.user_id == users[0]["user_id"])).scalar_one()
            account.delete_flag = "Y"
        assert not northbound_auth.validate_bearer_token(current_key)[0]


def test_native_http_identity_password_and_api_keys(runtime):
    client, auth, helpers, models = runtime
    from management.services.permission.identity import northbound
    assert client.get("/api/user/service_health").status_code == 200
    data = register(client)
    token = data["session"]["access_token"]
    assert data["session"]["refresh_token"]
    assert (
        client.get("/api/user/current_user_id", headers=bearer(token)).json()["data"][
            "user_id"
        ]
        == data["user"]["id"]
    )
    profile = client.get("/api/user/current_user_info", headers=bearer(token))
    assert profile.status_code == 200, profile.text
    assert profile.json()["data"]["user"]["tenant_id"] == "tenant-native"
    assert profile.json()["data"]["user"]["auth_provider"] == "local"
    from management.db.identity.user_tenant import update_user_tenant_role
    from management.db.identity.account import get_account

    assert seed_membership_roles(data["user"]["id"], ["DEV"])
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


def test_native_http_rotates_once_and_replays_only_the_same_request(runtime, caplog):
    from contracts.constants import environment
    from sqlalchemy import text
    from infrastructure.rdb.client import get_db_session
    from infrastructure.rdb.identity import IdentityRepository

    client, _, helpers, models = runtime
    original = register(client)["session"]
    second = client.post("/api/user/signin", json={"email": "native@example.com", "password": "Password123"})
    assert second.status_code == 200
    other = second.json()["data"]["session"]
    independent = register(client, email="independent@example.com")
    independent_session = independent["session"]
    independent_user = independent["user"]["id"]

    def session_rows(user_id):
        with get_db_session() as session:
            return [
                dict(row)
                for row in session.execute(
                    text("SELECT * FROM nexent.user_local_session_t WHERE user_id = :user_id ORDER BY session_id"),
                    {"user_id": user_id},
                ).mappings()
            ]

    def account_row(user_id):
        with get_db_session() as session:
            account = models.UserAccount.__table__
            return dict(session.execute(account.select().where(account.c.user_id == user_id)).mappings().one())

    def claims_for(access_token):
        return jwt.decode(access_token, options={"verify_signature": False})

    owner = claims_for(original["access_token"])["sub"]
    original_sid = claims_for(original["access_token"])["sid"]

    def original_row():
        return next(row for row in session_rows(owner) if str(row["session_id"]) == original_sid)

    independent_before = session_rows(independent_user)
    independent_account_before = account_row(independent_user)
    assert len(independent_before) == 1
    issued = original_row()
    assert issued["created_by"] == issued["updated_by"] == owner
    assert issued["create_time"] <= issued["update_time"]
    assert issued["delete_flag"] == "N"

    def refresh(access, refresh_token, request_id):
        return client.post(
            "/api/user/refresh_token",
            headers={**bearer(access), "X-Refresh-Request-Id": request_id},
            json={"refresh_token": refresh_token},
        )

    wrong_device = refresh(original["access_token"], other["refresh_token"], "other-device-request")
    wrong_user = refresh(original["access_token"], independent_session["refresh_token"], "other-user-request")
    assert wrong_device.status_code == wrong_user.status_code == 401
    ids = ["concurrent-refresh-one", "concurrent-refresh-two"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(
            lambda request_id: refresh(original["access_token"], original["refresh_token"], request_id),
            ids,
        ))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(i for i, response in enumerate(responses) if response.status_code == 200)
    replacement = responses[winner].json()["data"]["session"]
    assert replacement["refresh_token"] != original["refresh_token"]
    rotated = original_row()
    assert rotated["created_by"] == rotated["updated_by"] == owner
    assert rotated["create_time"] == issued["create_time"]
    assert rotated["update_time"] >= issued["update_time"]
    retry = refresh(original["access_token"], original["refresh_token"], ids[winner])
    assert retry.status_code == 200
    assert retry.json()["data"]["session"] == replacement
    assert original_row() == rotated
    assert client.get("/api/user/current_user_id", headers=bearer(original["access_token"])).status_code == 200

    claims = jwt.decode(replacement["access_token"], options={"verify_signature": False})
    claims["exp"] = claims["iat"] - 1
    expired = jwt.encode(claims, helpers.JWT_SECRET, algorithm="HS256")
    expired_attempt = refresh(expired, replacement["refresh_token"], "expired-access-request")
    assert expired_attempt.status_code == 401

    async def gateway_session_active():
        repo = await IdentityRepository.open(
            host=environment.POSTGRES_HOST, port=int(environment.POSTGRES_PORT),
            database=environment.POSTGRES_DB, user=environment.POSTGRES_USER,
            password=environment.NEXENT_POSTGRES_PASSWORD,
        )
        try:
            snapshot = await repo.snapshot({"kind": "session", "user_id": claims["sub"], "session_id": claims["sid"]})
            return snapshot["session_active"]
        finally:
            await repo.close()

    assert asyncio.run(gateway_session_active())
    logout = client.post("/api/user/logout", headers=bearer(replacement["access_token"]))
    assert logout.status_code == 200
    assert client.get("/api/user/current_user_id", headers=bearer(replacement["access_token"])).status_code == 401
    revoked_attempt = refresh(replacement["access_token"], replacement["refresh_token"], "revoked-access-request")
    assert revoked_attempt.status_code == 401
    revoked = original_row()
    assert revoked["revoked_at"] is not None
    assert revoked["updated_by"] == owner
    assert revoked["update_time"] >= rotated["update_time"]
    assert client.get("/api/user/current_user_id", headers=bearer(other["access_token"])).status_code == 200
    assert not asyncio.run(gateway_session_active())
    assert session_rows(independent_user) == independent_before
    assert account_row(independent_user) == independent_account_before
    assert client.get(
        "/api/user/current_user_id", headers=bearer(independent_session["access_token"])
    ).json()["data"]["user_id"] == independent_user

    credentials = [expired, "Password123"]
    credentials.extend(
        credential_pair[key]
        for credential_pair in (original, other, replacement, independent_session)
        for key in ("access_token", "refresh_token")
    )
    credentials.append(independent_account_before["password_hash"])
    for failure in (wrong_device, wrong_user, responses[1 - winner], expired_attempt, revoked_attempt):
        assert "set-cookie" not in failure.headers
        response_text = f"{failure.headers!r} {failure.text}"
        assert all(secret not in response_text for secret in credentials)
        assert all(field not in failure.text for field in ('"access_token"', '"refresh_token"', '"password_hash"'))
    assert all(secret not in caplog.text for secret in credentials)


def test_native_http_invalid_duplicate_disabled_and_refresh(runtime):
    client, auth, helpers, models = runtime
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
    from infrastructure.rdb.client import get_db_session

    with get_db_session() as session:
        session.execute(
            models.UserAccount.__table__.update().values(delete_flag="Y")
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
    data = register(client)
    user_id = data["user"]["id"]
    from infrastructure.rdb.client import get_db_session

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
    from management.cli.account import bootstrap_super_admin
    from contracts.errors.exceptions import AccountConflictError
    from management.db.identity.account import get_account_by_email
    from management.utils.account_passwords import verify_password
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
    with pytest.raises(AccountConflictError, match=r"migrate\.sh --apply"):
        bootstrap_super_admin("another-su@example.com", "", check_only=True)
    account = get_account_by_email("suadmin@nexent.com")
    assert verify_password("BootstrapPass123", account["password_hash"])
    register(client)
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
    from management.services.permission.identity import northbound
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
