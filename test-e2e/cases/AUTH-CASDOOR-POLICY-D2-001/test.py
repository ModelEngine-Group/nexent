# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from local_auth_http import native_runtime, runtime

pytestmark = [pytest.mark.case_id("AUTH-CASDOOR-POLICY-D2-001"), pytest.mark.stage("D2")]


@pytest.mark.asyncio
async def test_grant_and_revoke_skill_read_in_same_session(runtime, monkeypatch):
    client, _, auth, models = runtime
    from consts import const as settings
    from management.api.skill.skill_repository import skill_repository_router
    from infrastructure.rdb.client import db_client, get_db_session
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


@pytest.mark.asyncio
async def test_staged_knowledge_actions_follow_policy_edits_in_same_session(runtime, monkeypatch):
    client, _, auth, models = runtime
    from consts import const as settings
    from contracts.constants import environment
    from management.api.knowledge_base import vectordatabase
    from infrastructure.rdb.client import db_client, get_db_session
    from management.db.identity.account import create_account
    from management.db.identity.oauth_account import insert_oauth_account
    from management.db.identity.user_tenant import insert_user_tenant
    from management.services.permission.identity import casdoor, casdoor_roles
    from management.services.tag.library import TagManagementService
    from nexent.core.concurrency import LanePolicy, ThreadManager

    for name, value in {
        "CASDOOR_ENDPOINT": "https://door.example.test", "CASDOOR_BACKEND_ENDPOINT": "",
        "CASDOOR_CLIENT_ID": "synthetic-id", "CASDOOR_CLIENT_SECRET": "synthetic-secret",
        "CASDOOR_ROLE_SYNC_ORGANIZATION": "business", "CASDOOR_ROLE_MAP_JSON": '{"member":"USER"}',
        "CASDOOR_PERMISSION_MODEL": "features",
    }.items():
        monkeypatch.setattr(settings, name, value)
    actions = ["kb:create", "kb:update", "kb:delete"]
    monkeypatch.setattr(environment, "CASDOOR_ADDITIONAL_MANAGED_ACTIONS", frozenset(actions), raising=False)
    client.app.include_router(vectordatabase.router, prefix="/api")
    monkeypatch.setitem(client.app.dependency_overrides, vectordatabase.get_vector_db_core, lambda: object())
    monkeypatch.setattr(vectordatabase, "record_security_event", Mock())
    create = Mock(return_value={"status": "success"})
    update = Mock(return_value=True)
    delete = AsyncMock(return_value={"status": "success"})
    monkeypatch.setattr(vectordatabase.ElasticSearchService, "create_knowledge_base", create)
    monkeypatch.setattr(vectordatabase.ElasticSearchService, "update_knowledge_base", update)
    monkeypatch.setattr(vectordatabase.ElasticSearchService, "full_delete_knowledge_base", delete)
    monkeypatch.setattr(TagManagementService, "cleanup_resource_assignments", Mock())
    monkeypatch.setattr(TagManagementService, "cleanup_document_assignments_for_knowledge_base", Mock())
    models.KnowledgeRecord.__table__.create(db_client.engine)
    with get_db_session() as session:
        create_account("member@example.com", user_id="member", auth_provider="casdoor", db_session=session)
        insert_user_tenant("member", "tenant", "USER", "member@example.com", db_session=session)
        for index, tenant, creator in [
            ("own", "tenant", "member"), ("foreign", "other-tenant", "member"), ("peer", "tenant", "peer"),
        ]:
            session.add(models.KnowledgeRecord(
                index_name=index, tenant_id=tenant, ingroup_permission="PRIVATE",
                created_by=creator, updated_by=creator, delete_flag="N",
            ))
    insert_oauth_account("member", "casdoor", casdoor.subject_key("stable"), "member@example.com", "member", "tenant")
    headers = {"Authorization": "Bearer " + auth.generate_session_jwt("member")}
    associated_roles = ["business/member"]
    allowed_actions = actions[:]

    def respond(request):
        if request.url.path.endswith("get-permissions"):
            data = [{
                "owner": "business", "model": "business/features", "resourceType": "Custom",
                "name": "knowledge", "effect": "Allow", "state": "Approved", "isEnabled": True,
                "resources": ["nexent:knowledge-base"], "actions": allowed_actions, "roles": associated_roles,
            }]
        elif request.url.path.endswith("get-user"):
            data = {"owner": "business", "name": "member", "id": "stable",
                    "roles": [{"owner": "business", "name": "member", "isEnabled": True}]}
        else:
            assert request.url.path.endswith("batch-enforce")
            assert request.url.params["permissionId"] == "business/knowledge"
            requests = json.loads(request.content)
            assert all(sub == "business/member" and resource == "nexent:knowledge-base"
                       for sub, resource, _ in requests)
            data = [[bool(associated_roles) and action in allowed_actions for _, _, action in requests]]
        return httpx.Response(200, json={"status": "ok", "data": data})

    def assert_actions(expected):
        calls = [
            ("POST", "new", {"json": {"embedding_model_id": 1}}, create),
            ("PATCH", "own", {"json": {"knowledge_name": "renamed"}}, update),
            ("DELETE", "own", {}, delete),
        ]
        for action, (method, index, kwargs, mutation) in zip(actions, calls):
            previous_calls = mutation.call_count
            response = client.request(method, f"/api/indices/{index}", headers=headers, **kwargs)
            assert response.status_code == (200 if action in expected else 403), response.text
            assert mutation.call_count - previous_calls == int(action in expected)
        response = client.get("/api/user/current_user_info", headers=headers)
        assert response.status_code == 200
        assert set(response.json()["data"]["user"]["permissions"]).intersection(actions) == set(expected)

    manager = ThreadManager(service_name="casdoor-knowledge-test", lane_policies={
        "background-service": LanePolicy(name="background-service", max_workers=1, max_queue_size=0),
    })
    manager.start()
    try:
        async with httpx.AsyncClient(base_url="https://door.example.test", transport=httpx.MockTransport(respond)) as upstream:
            assert_actions([])
            await casdoor_roles.reconcile_roles(upstream, "business", {"member": "USER"}, manager)
            assert_actions(actions)
            for index in ("foreign", "peer"):
                assert client.patch(f"/api/indices/{index}", headers=headers,
                                    json={"knowledge_name": "forbidden"}).status_code == 403
                assert client.delete(f"/api/indices/{index}", headers=headers).status_code == 403
            assert update.call_count == delete.call_count == 1
            associated_roles.clear()
            await casdoor_roles.reconcile_roles(upstream, "business", {"member": "USER"}, manager)
            assert_actions([])
            associated_roles.append("business/member")
            await casdoor_roles.reconcile_roles(upstream, "business", {"member": "USER"}, manager)
            assert_actions(actions)
            allowed_actions.remove("kb:update")
            await casdoor_roles.reconcile_roles(upstream, "business", {"member": "USER"}, manager)
            assert_actions(["kb:create", "kb:delete"])
    finally:
        await manager.shutdown(timeout=5)


@pytest.mark.asyncio
async def test_linked_administrator_follows_feature_policy_without_role_sync(runtime, monkeypatch):
    client, _, auth, models = runtime
    from consts import const as settings
    from infrastructure.security.passwords import hash_password
    from management.api.identity import oauth
    from management.api.model import model_managment
    from infrastructure.rdb.client import get_db_session
    from management.db.identity.account import create_account, get_account
    from management.db.identity.oauth_account import insert_oauth_account
    from management.db.identity.user_tenant import insert_user_tenant
    from management.services.permission.identity import casdoor, casdoor_roles
    from nexent.core.concurrency import LanePolicy, ThreadManager
    from permissions import rbac

    for name, value in {
        "CASDOOR_ENDPOINT": "https://door.example.test", "CASDOOR_BACKEND_ENDPOINT": "",
        "CASDOOR_CLIENT_ID": "synthetic-id", "CASDOOR_CLIENT_SECRET": "synthetic-secret",
        "CASDOOR_ROLE_SYNC_ORGANIZATION": "business", "CASDOOR_ROLE_MAP_JSON": '{"member":"USER"}',
        "CASDOOR_PERMISSION_MODEL": "features",
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(model_managment, "list_models_for_tenant", AsyncMock(return_value=[]))
    monkeypatch.setattr(oauth, "record_security_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(rbac, "_INITIALIZED", False)
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {})
    client.app.include_router(model_managment.router, prefix="/api")
    client.app.include_router(oauth.router, prefix="/api")

    user = "linked-admin"
    email = "linked@example.test"
    with get_db_session() as session:
        create_account(email, hash_password("SyntheticPassword123!"), user_id=user, db_session=session)
        insert_user_tenant(user, "tenant", "ADMIN", email, db_session=session)
        session.add_all([
            models.RolePermission(user_role="ADMIN", permission_type="LEFT_NAV_MENU", permission_subtype="/models"),
            models.RolePermission(user_role="ADMIN", permission_category="RESOURCE",
                                  permission_type="model", permission_subtype="read"),
        ])
    insert_oauth_account(user, "casdoor", casdoor.subject_key("stable-linked"), email, user, "tenant")
    headers = {"Authorization": "Bearer " + auth.generate_session_jwt(user)}
    actions = ["model:read", "menu:models"]
    remote_subject = "stable-linked"

    def respond(request):
        if request.url.path.endswith("get-permissions"):
            data = [{"owner": "business", "model": "business/features", "name": "model",
                     "resourceType": "Custom", "effect": "Allow", "state": "Approved",
                     "isEnabled": True, "resources": ["nexent:model"], "actions": actions}]
        elif request.url.path.endswith("get-user"):
            assert request.url.params["id"] == "business/linked-admin"
            data = {"owner": "business", "name": user, "id": remote_subject, "roles": []}
        else:
            assert request.url.path.endswith("batch-enforce")
            assert remote_subject == "stable-linked"
            data = [[subject == f"business/{user}" and resource == "nexent:model" and action in actions
                     for subject, resource, action in json.loads(request.content)]]
        return httpx.Response(200, json={"status": "ok", "data": data})

    def info():
        response = client.get("/api/user/current_user_info", headers=headers)
        assert response.status_code == 200
        return response.json()["data"]["user"]

    manager = ThreadManager(service_name="casdoor-policy-linked-test", lane_policies={
        "background-service": LanePolicy(name="background-service", max_workers=1, max_queue_size=0),
    })
    manager.start()
    try:
        async with httpx.AsyncClient(base_url="https://door.example.test", transport=httpx.MockTransport(respond)) as upstream:
            assert client.get("/api/model/list", headers=headers).status_code == 403
            remote_subject = "wrong-subject"
            await casdoor_roles.reconcile_roles(upstream, "business", {"member": "USER"}, manager)
            assert client.get("/api/model/list", headers=headers).status_code == 403

            remote_subject = "stable-linked"
            assert await casdoor_roles.reconcile_roles(upstream, "business", {"member": "USER"}, manager) == 0
            before = info()
            assert before["casdoor_feature_policy"] is True
            assert "casdoor_role_sync" not in before
            assert before["user_role"] == "ADMIN"
            assert "/models" in before["accessibleRoutes"]

            actions.remove("menu:models")
            await casdoor_roles.reconcile_roles(upstream, "business", {"member": "USER"}, manager)
            assert "/models" not in info()["accessibleRoutes"]
            assert "model:read" in info()["permissions"]
            assert client.get("/api/model/list", headers=headers).status_code == 200

            actions.clear()
            await casdoor_roles.reconcile_roles(upstream, "business", {"member": "USER"}, manager)
            assert client.get("/api/model/list", headers=headers).status_code == 403
            assert client.delete("/api/user/oauth/accounts/casdoor", headers=headers).status_code == 200
            after = info()
            assert "casdoor_feature_policy" not in after
            assert "/models" in after["accessibleRoutes"]
            assert client.get("/api/model/list", headers=headers).status_code == 200
            assert get_account(user)["user_role"] == "ADMIN"
            assert get_account(user)["password_login_enabled"] is True
    finally:
        await manager.shutdown(timeout=5)
