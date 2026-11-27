# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from local_auth_http import native_runtime

pytestmark = [pytest.mark.case_id("AUTH-CASDOOR-IMPORT-D2-001"), pytest.mark.stage("D2")]


def test_import_preserves_super_admin_identity(native_runtime, monkeypatch):
    client, _, _, models = native_runtime
    from consts import const as settings
    from infrastructure.rdb.client import db_client, get_db_session
    from management.api.identity import oauth
    from management.db.configuration.models import TenantConfig
    from management.db.identity.account import create_account, get_account
    from management.db.identity.oauth_account import get_oauth_account_by_provider
    from management.db.identity.user_tenant import insert_user_tenant
    from management.services.permission.identity import casdoor, casdoor_groups
    from management.utils.account_passwords import hash_password
    from scripts import import_nexent_to_casdoor as migration

    org, target_tenant, original_tenant = "org", "business-tenant", "platform-tenant"
    user_id, email = "original-su", "super-admin@example.com"
    monkeypatch.setattr(settings, "CASDOOR_ENDPOINT", "https://door.example.test")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(casdoor, "OAUTH_CALLBACK_BASE_URL", "http://testserver")
    monkeypatch.setattr(oauth, "record_security_event", lambda *args, **kwargs: None)
    client.app.include_router(oauth.router, prefix="/api")

    TenantConfig.__table__.create(db_client.engine)
    local_password = hash_password("SyntheticLocalPassword123!")
    with get_db_session() as session:
        create_account(email, local_password, user_id=user_id, db_session=session)
        insert_user_tenant(user_id, original_tenant, "SU", email, db_session=session)
        create_account("foreign@example.com", local_password, user_id="foreign", db_session=session)
        insert_user_tenant("foreign", "unrelated-tenant", "USER", "foreign@example.com", db_session=session)
        create_account("member@example.com", user_id="member", db_session=session)
        insert_user_tenant("member", target_tenant, "USER", "member@example.com", db_session=session)
        default_group = models.TenantGroupInfo(tenant_id=target_tenant, group_name="Default")
        session.add(default_group)
        session.flush()
        session.add(TenantConfig(tenant_id=target_tenant, config_key="DEFAULT_GROUP_ID",
                                 config_value=str(default_group.group_id)))

    saved = {"username": "nexent-platform-test", "id": "casdoor-platform-id",
             "temporary_password": "TemporarySynthetic123!", "email": email,
             "role": "SU", "tenant_id": original_tenant}
    journal = {"users": {user_id: saved}}
    remote_users = {"org/conflict": {"owner": org, "name": "conflict", "id": "different", "email": email}}
    writes = []

    def upstream(request):
        operation = request.url.path.rsplit("/", 1)[-1]
        data = None
        if operation == "get-users":
            assert request.url.params["owner"] == org
            data = list(remote_users.values())
        elif operation == "get-groups":
            data = []
        elif operation == "get-user":
            data = remote_users.get(request.url.params["id"])
        elif operation == "add-user":
            payload = json.loads(request.content)
            writes.append(operation)
            assert payload["owner"] == org
            assert payload["type"] == "normal-user" and payload["needUpdatePassword"] is True
            assert payload.pop("password") == saved["temporary_password"]
            assert "isAdmin" not in payload and "isGlobalAdmin" not in payload
            remote_users[f"{org}/{payload['name']}"] = payload
        else:
            pytest.fail(f"Unexpected Casdoor operation {operation}")
        return httpx.Response(200, json={"status": "ok", "data": data})

    with httpx.Client(base_url="https://door.example.test", transport=httpx.MockTransport(upstream)) as provider:
        with get_db_session() as session:
            with pytest.raises(migration.ImportConflict, match="email conflict"):
                migration.plan_import(session, target_tenant, org, casdoor_groups, provider, None)
        assert writes == []
        remote_users.clear()
        assert get_oauth_account_by_provider("casdoor", casdoor.subject_key(saved["id"])) is None

        with get_db_session() as session:
            with pytest.raises(migration.ImportConflict, match="member who cannot be migrated"), session.begin_nested():
                group = models.TenantGroupInfo(tenant_id=target_tenant, group_name="Cross-tenant")
                session.add(group)
                session.flush()
                session.add(models.TenantGroupUser(group_id=group.group_id, user_id=user_id))
                migration.plan_import(session, target_tenant, org, casdoor_groups, provider, None)
        assert writes == []

        with pytest.raises(RuntimeError, match="interrupted import"):
            with get_db_session() as session:
                accounts, bound, *_ = migration.plan_import(session, target_tenant, org, casdoor_groups, provider, None)
                assert accounts == {user_id: migration.ImportAccount(email, "SU", original_tenant)}
                migration.import_users(session, provider, org, accounts, bound, journal, casdoor_groups, {})
                raise RuntimeError("interrupted import")
        assert get_oauth_account_by_provider("casdoor", casdoor.subject_key(saved["id"])) is None
        with get_db_session() as session:
            accounts, bound, *_ = migration.plan_import(session, target_tenant, org, casdoor_groups, provider, journal)
            migration.import_users(session, provider, org, accounts, bound, journal, casdoor_groups, {})
        with get_db_session() as session:
            accounts, bound, *_ = migration.plan_import(session, target_tenant, org, casdoor_groups, provider, journal)
            assert accounts == {} and set(bound) == {user_id}
        assert writes == ["add-user"]
    binding = get_oauth_account_by_provider("casdoor", casdoor.subject_key(saved["id"]))
    assert binding["user_id"] == user_id and binding["tenant_id"] == original_tenant
    assert get_account(user_id)["password_hash"] == local_password

    monkeypatch.setattr(casdoor, "authenticate", lambda code, flow: {
        "id": casdoor.subject_key(saved["id"]), "email": email, "username": saved["username"],
    })
    auth = client.get("/api/user/oauth/authorize", params={"provider": "casdoor"}, follow_redirects=False)
    assert auth.status_code == 302
    state = parse_qs(urlsplit(auth.headers["location"]).query)["state"][0]
    completed = client.get("/api/user/oauth/callback", params={"provider": "casdoor", "code": "synthetic", "state": state})
    assert completed.status_code == 200
    data = completed.json()["data"]
    assert data["user"]["id"] == user_id
    header = {"Authorization": f"Bearer {data['session']['access_token']}"}
    profile = client.get("/api/user/current_user_info", headers=header)
    assert profile.status_code == 200
    identity = profile.json()["data"]["user"]
    assert identity["user_role"] == "SU" and identity["tenant_id"] == original_tenant
