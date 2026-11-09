# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json

import httpx
import pytest

from local_auth_http import native_runtime, runtime

pytestmark = [pytest.mark.case_id("AUTH-CASDOOR-POLICY-D2-001"), pytest.mark.stage("D2")]


@pytest.mark.asyncio
async def test_grant_and_revoke_skill_read_in_same_session(runtime, monkeypatch):
    client, _, auth, models = runtime
    from consts import const as settings
    from management.api.skill.skill_repository import skill_repository_router
    from management.db.client import db_client, get_db_session
    from management.db.identity.account import create_account
    from management.db.identity.oauth_account import insert_oauth_account
    from management.db.identity.user_tenant import insert_user_tenant
    from management.services.permission.identity import casdoor, casdoor_roles
    from nexent.core.concurrency import LanePolicy, ThreadManager

    for name, value in {
        "CASDOOR_ENDPOINT": "https://door.example.test", "CASDOOR_BACKEND_ENDPOINT": "",
        "CASDOOR_CLIENT_ID": "synthetic-id", "CASDOOR_CLIENT_SECRET": "synthetic-secret",
        "CASDOOR_ROLE_SYNC_ORGANIZATION": "business", "CASDOOR_ROLE_MAP_JSON": '{"member":"USER"}',
        "CASDOOR_PERMISSION_MODEL": "features",
    }.items():
        monkeypatch.setattr(settings, name, value)
    client.app.include_router(skill_repository_router, prefix="/api")
    models.SkillRepository.__table__.create(db_client.engine)
    with get_db_session() as session:
        create_account("member@example.com", user_id="member", auth_provider="casdoor", db_session=session)
        insert_user_tenant("member", "tenant", "USER", "member@example.com", db_session=session)
    insert_oauth_account("member", "casdoor", casdoor.subject_key("stable"), "member@example.com", "member", "tenant")
    headers = {"Authorization": "Bearer " + auth.generate_session_jwt("member")}

    enabled = True
    resource = "nexent"
    decisions = []

    def respond(request):
        if request.url.path.endswith("get-permissions"):
            assert request.url.params["owner"] == "business"
            data = [{"owner": "business", "model": "business/features", "resourceType": "Custom",
                     "name": "member-features", "effect": "Allow", "state": "Approved", "isEnabled": enabled,
                     "resources": [resource], "actions": ["skill.repository:read", "unrecognized:action"]}]
        elif request.url.path.endswith("get-user"):
            assert request.url.params["id"] == "business/member"
            data = {"owner": "business", "name": "member", "id": "stable", "roles": []}
        else:
            assert request.url.path.endswith("batch-enforce")
            assert request.url.params["permissionId"] == "business/member-features"
            decisions.extend(json.loads(request.content))
            data = [[True]]
        return httpx.Response(200, json={"status": "ok", "data": data})

    def info():
        response = client.get("/api/user/current_user_info", headers=headers)
        assert response.status_code == 200
        return response.json()["data"]["user"]

    manager = ThreadManager(service_name="casdoor-policy-test", lane_policies={
        "background-service": LanePolicy(name="background-service", max_workers=1, max_queue_size=0),
    })
    manager.start()
    try:
        async with httpx.AsyncClient(base_url="https://door.example.test", transport=httpx.MockTransport(respond)) as upstream:
            assert client.get("/api/repository/skill", headers=headers).status_code == 403
            await casdoor_roles.reconcile_roles(upstream, "business", {"member": "USER"}, manager)
            assert client.get("/api/repository/skill", headers=headers).status_code == 200
            assert client.post("/api/repository/skill/1/install", headers=headers).status_code == 403
            assert client.get("/api/repository/skill?status=pending_review", headers=headers).status_code == 403
            assert info()["user_role"] == "USER"
            assert info()["casdoor_feature_policy"] is True
            assert "skill.repository:read" in info()["permissions"]
            assert "/skill-space" in info()["accessibleRoutes"]
            enabled = False
            await casdoor_roles.reconcile_roles(upstream, "business", {"member": "USER"}, manager)
            assert client.get("/api/repository/skill", headers=headers).status_code == 403
            assert "skill.repository:read" not in info()["permissions"]
            assert "/skill-space" not in info()["accessibleRoutes"]

            enabled = True
            resource = "nexent:skill-repository"
            await casdoor_roles.reconcile_roles(upstream, "business", {"member": "USER"}, manager)
            assert client.get("/api/repository/skill", headers=headers).status_code == 200
            assert "skill.repository:read" in info()["permissions"]
            resource = "nexent:model"
            await casdoor_roles.reconcile_roles(upstream, "business", {"member": "USER"}, manager)
            assert client.get("/api/repository/skill", headers=headers).status_code == 403
            assert "skill.repository:read" not in info()["permissions"]
            assert decisions == [["business/member", "nexent", "skill.repository:read"],
                                 ["business/member", "nexent:skill-repository", "skill.repository:read"]]
    finally:
        await manager.shutdown(timeout=5)
