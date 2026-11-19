# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise existing-session role and permission changes through real HTTP and storage."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from local_auth_http import native_runtime, runtime

pytestmark = [pytest.mark.case_id("AUTH-CASDOOR-ROLE-SYNC-D2-001"), pytest.mark.stage("D2")]


@pytest.mark.asyncio
async def test_role_changes_apply_to_the_same_session(runtime, monkeypatch):
    client, _, auth, models = runtime
    from consts import const as settings
    from management.api.identity import user
    from infrastructure.rdb.client import get_db_session
    from management.db.identity.account import create_account
    from management.db.identity.oauth_account import insert_oauth_account
    from management.db.identity.user_tenant import insert_user_tenant
    from management.services.permission.identity import casdoor, casdoor_roles
    from nexent.core.concurrency import LanePolicy, ThreadManager

    monkeypatch.setattr(settings, "CASDOOR_ENDPOINT", "https://door.example.test")
    monkeypatch.setattr(settings, "CASDOOR_BACKEND_ENDPOINT", "")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setattr(settings, "CASDOOR_ROLE_SYNC_ORGANIZATION", "business")
    monkeypatch.setattr(settings, "CASDOOR_ROLE_MAP_JSON", '{"tenant-admin":"ADMIN"}')
    monkeypatch.setattr(settings, "CASDOOR_PERMISSION_MODEL", "")
    client.app.include_router(user.router, prefix="/api")

    tenant = "tenant-native"
    with get_db_session() as session:
        create_account("tenant-admin@example.com", user_id="tenant-admin", db_session=session)
        insert_user_tenant("tenant-admin", tenant, "ADMIN", "tenant-admin@example.com", db_session=session)
    for name, origin in [("member", "casdoor"), ("local", None)]:
        email = f"{name}@example.com"
        with get_db_session() as session:
            create_account(email, user_id=name, auth_provider=origin, db_session=session)
            insert_user_tenant(name, tenant, "USER", email, db_session=session,
                               roles=("USER", "OPS") if origin else ("USER",))
        insert_oauth_account(name, "casdoor", casdoor.subject_key(f"{name}-subject"), email, name, tenant)
    insert_oauth_account("member", "casdoor", casdoor.subject_key("secondary-subject"),
                         "other@example.com", "secondary", tenant)
    with get_db_session() as session:
        session.add(models.RolePermission(user_role="ADMIN", permission_category="RESOURCE",
                                          permission_type="USER.ROLE", permission_subtype="READ"))

    session_headers = {"Authorization": "Bearer " + auth.generate_session_jwt("member")}
    local_headers = {"Authorization": "Bearer " + auth.generate_session_jwt("local")}

    def user_info(headers):
        response = client.get("/api/user/current_user_info", headers=headers)
        assert response.status_code == 200
        return response.json()["data"]["user"]

    def list_users():
        return client.post("/api/users/list", headers=session_headers, json={"tenant_id": tenant})

    assert user_info(session_headers)["user_role"] == "USER"
    assert list_users().status_code == 403

    directory = {"id": "member-subject", "owner": "business", "name": "member", "roles": [
        {"owner": "business", "name": "tenant-admin", "isEnabled": True},
    ]}
    requested = []
    status = 200

    def respond(request):
        requested.append(request.url.params["id"])
        return httpx.Response(status, json={"status": "ok", "data": directory})

    manager = ThreadManager(service_name="casdoor-role-test", lane_policies={
        "background-service": LanePolicy(name="background-service", max_workers=1, max_queue_size=0),
    })
    manager.start()
    try:
        async with httpx.AsyncClient(base_url="https://door.example.test", transport=httpx.MockTransport(respond)) as upstream:
            async def sync():
                return await casdoor_roles.reconcile_roles(upstream, "business", {"tenant-admin": "ADMIN"}, manager)

            assert await sync() == 1
            promoted = user_info(session_headers)
            assert promoted["user_role"] == "ADMIN"
            assert promoted["roles"] == ["ADMIN", "OPS"]
            assert promoted["casdoor_role_sync"] is True
            assert "user.role:read" in promoted["permissions"]
            assert list_users().status_code == 200

            status = 503
            assert await sync() == 0
            assert user_info(session_headers)["user_role"] == "ADMIN"
            status = 200

            directory["roles"] = []
            assert await sync() == 1
            demoted = user_info(session_headers)
            assert demoted["user_role"] == "USER"
            assert demoted["roles"] == ["USER", "OPS"]
            assert "user.role:read" not in demoted["permissions"]
            assert list_users().status_code == 403

            directory["id"] = "replacement-subject"
            directory["roles"] = [{"owner": "business", "name": "tenant-admin", "isEnabled": True}]
            assert await sync() == 0
            assert user_info(session_headers)["user_role"] == "USER"
            assert user_info(local_headers)["user_role"] == "USER"
            assert "casdoor_role_sync" not in user_info(local_headers)
            assert requested == ["business/member"] * 4
    finally:
        await manager.shutdown(timeout=5)


@pytest.mark.asyncio
async def test_invitation_role_is_published_and_can_be_revoked(runtime, monkeypatch):
    client, _, _, models = runtime
    from consts import const as settings
    from management.api.identity import oauth as routes
    from infrastructure.rdb.client import get_db_session
    from management.services.permission.identity import casdoor, casdoor_roles, oauth
    from nexent.core.concurrency import LanePolicy, ThreadManager

    mapping = {"nexent-developer": "DEV", "old-dev": "DEV"}
    for key, value in {
        "CASDOOR_ENDPOINT": "https://door.example.test", "CASDOOR_BACKEND_ENDPOINT": "",
        "CASDOOR_CLIENT_ID": "test-client", "CASDOOR_CLIENT_SECRET": "test-secret",
        "CASDOOR_ROLE_SYNC_ORGANIZATION": "business",
        "CASDOOR_ROLE_MAP_JSON": '{"nexent-developer":"DEV","old-dev":"DEV"}',
        "CASDOOR_PERMISSION_MODEL": "",
    }.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(routes, "record_security_event", lambda *a, **kw: None)
    monkeypatch.setattr(oauth, "init_tool_list_for_tenant", AsyncMock())
    client.app.include_router(routes.router, prefix="/api")
    with get_db_session() as session:
        session.query(models.TenantInvitationCode).filter_by(invitation_code="NATIVE-INVITE").update(
            {"code_type": "DEV_INVITE", "roles": ["DEV"]}
        )
    token = oauth.generate_pending_oauth_token(
        "casdoor", casdoor.subject_key("new-subject"), "new@example.com", "new-member"
    )
    complete = client.post("/api/user/oauth/complete", headers={"X-OAuth-Pending-Token": token},
                           json={"invite_code": "NATIVE-INVITE"})
    assert complete.status_code == 200
    data = complete.json()["data"]
    headers = {"Authorization": "Bearer " + data["session"]["access_token"]}

    def current_role():
        info = client.get("/api/user/current_user_info", headers=headers)
        assert info.status_code == 200
        return info.json()["data"]["user"]["user_role"]

    role = {"name": "nexent-developer", "owner": "business", "isEnabled": True, "users": ["business/existing"]}
    writes = 0

    def respond(request):
        nonlocal writes
        if request.url.path.endswith("get-user"):
            assert request.url.params["id"] == "business/new-member"
            value = {"id": "new-subject", "owner": "business", "name": "new-member",
                     "roles": [role] if "business/new-member" in role["users"] else []}
        else:
            assert request.url.params["id"] == "business/nexent-developer"
            value = role
            if request.method == "POST":
                writes += 1
                if writes == 1:
                    return httpx.Response(503, json={"status": "error"})
                assert request.url.params["columns"] == "users"
                role["users"] = json.loads(request.content)["users"]
        return httpx.Response(200, json={"status": "ok", "data": value})

    manager = ThreadManager(service_name="casdoor-bootstrap-test", lane_policies={
        "background-service": LanePolicy(name="background-service", max_workers=1, max_queue_size=0),
    })
    manager.start()
    try:
        async with httpx.AsyncClient(base_url="https://door.example.test", transport=httpx.MockTransport(respond)) as upstream:
            assert current_role() == "DEV"
            assert await casdoor_roles.reconcile_roles(upstream, "business", mapping, manager) == 0
            assert current_role() == "DEV"
            assert role["users"] == ["business/existing"]
            assert await casdoor_roles.reconcile_roles(upstream, "business", mapping, manager) == 0
            assert role["users"] == ["business/existing", "business/new-member"]
            role["users"].remove("business/new-member")
            assert await casdoor_roles.reconcile_roles(upstream, "business", mapping, manager) == 1
            assert current_role() == "USER"
            assert writes == 2
    finally:
        await manager.shutdown(timeout=5)
