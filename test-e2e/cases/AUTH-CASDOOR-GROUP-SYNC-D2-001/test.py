# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json

import httpx
import pytest

from local_auth_http import native_runtime

pytestmark = [pytest.mark.case_id("AUTH-CASDOOR-GROUP-SYNC-D2-001"), pytest.mark.stage("D2")]


def test_group_directory_round_trip(native_runtime, monkeypatch):
    client, _, auth, _ = native_runtime
    from consts import const as settings
    from contracts.constants import environment
    from management.api.identity import group as group_api
    from infrastructure.rdb.client import get_db_session
    from management.db.identity.account import create_account
    from management.db.identity.oauth_account import insert_oauth_account
    from management.db.identity.user_tenant import insert_user_tenant
    from management.services.permission.identity import casdoor_groups
    from management.services.permission.identity.casdoor import subject_key

    organization = "directory"
    tenant = "test-tenant"
    monkeypatch.setattr(environment, "CASDOOR_GROUP_SYNC_TENANT_ID", tenant)
    monkeypatch.setattr(settings, "CASDOOR_ROLE_SYNC_ORGANIZATION", organization)
    monkeypatch.setattr(settings, "CASDOOR_ENDPOINT", "https://door.example.test")
    monkeypatch.setattr(settings, "CASDOOR_BACKEND_ENDPOINT", "")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_ID", "synthetic-id")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setattr(group_api, "get_tenant_info", lambda tenant_id: {"tenant_id": tenant_id})
    monkeypatch.setattr(group_api, "record_security_event", lambda *args, **kwargs: None)
    client.app.include_router(group_api.router, prefix="/api")
    with get_db_session() as session:
        for user, role, tenant_id in (
            ("admin", "ADMIN", tenant), ("member", "USER", tenant), ("local", "USER", tenant),
            ("foreign", "ADMIN", "other-tenant"),
        ):
            email = f"{user}@example.test"
            create_account(email, user_id=user, db_session=session)
            insert_user_tenant(user, tenant_id, role, email, db_session=session)
    insert_oauth_account("member", "casdoor", subject_key("stable"), "member@example.test", "member", tenant)

    groups = {}
    member = {"owner": organization, "name": "member", "id": "stable", "groups": ["elsewhere/keep"]}
    writes = []

    def upstream(request):
        operation = request.url.path.rsplit("/", 1)[-1]
        data = None
        if operation == "get-groups":
            assert request.url.params["owner"] == organization
            data = list(groups.values())
        elif operation == "get-users":
            assert request.url.params["owner"] == organization
            data = [member]
        elif operation == "get-user":
            assert request.url.params["id"] == "directory/member"
            data = member
        else:
            payload = json.loads(request.content)
            writes.append(operation)
            if operation == "add-group":
                groups[payload["name"]] = payload
            elif operation == "update-group":
                assert request.url.params["id"] == f"directory/{payload['name']}"
                groups[payload["name"]] = payload
            else:
                assert operation == "update-user"
                assert request.url.params["columns"] == "groups"
                assert "elsewhere/keep" in payload["groups"]
                member["groups"] = payload["groups"]
        return httpx.Response(200, json={"status": "ok", "data": data})

    http_client = httpx.Client
    monkeypatch.setattr(casdoor_groups.httpx, "Client",
                        lambda **kwargs: http_client(transport=httpx.MockTransport(upstream), **kwargs))
    admin = {"Authorization": f"Bearer {auth.generate_session_jwt('admin')}"}
    foreign = {"Authorization": f"Bearer {auth.generate_session_jwt('foreign')}"}

    def create(name, parent=None):
        response = client.post("/api/groups", headers=admin, json={
            "tenant_id": tenant, "group_name": name, "parent_group_id": parent,
        })
        assert response.status_code == 201, response.text
        return response.json()["data"]["group_id"]

    parent_id = create("Research")
    child_id = create("Analysis", parent_id)
    parent, child = groups.values()
    assert child["parentId"] == parent["name"]
    assert client.put(f"/api/groups/{child_id}", headers=admin, json={
        "group_name": "Analytics", "group_description": "Shared description",
    }).status_code == 200
    assert groups[child["name"]]["displayName"] == "Analytics"
    assert groups[child["name"]]["properties"]["nexentDescription"] == "Shared description"
    response = client.post(f"/api/groups/{child_id}/members", headers=admin, json={"user_id": "member"})
    assert response.status_code == 200, response.text
    assert f"directory/{child['name']}" in member["groups"]
    response = client.put(f"/api/groups/{child_id}/members", headers=admin, json={"user_ids": []})
    assert response.status_code == 200, response.text
    assert member["groups"] == ["elsewhere/keep"]
    response = client.post("/api/groups/members/batch", headers=admin, json={
        "user_id": "member", "group_ids": [child_id],
    })
    assert response.status_code == 200, response.text
    assert f"directory/{child['name']}" in member["groups"]

    groups["casdoor-group"] = {
        "owner": organization, "name": "casdoor-group", "displayName": "Provider child",
        "createdTime": "2026-11-11T00:00:00Z", "parentId": child["name"], "isEnabled": True,
    }
    groups[child["name"]]["displayName"] = "Edited in Casdoor"
    member["groups"] = ["elsewhere/keep", "directory/casdoor-group"]
    casdoor_groups.reconcile_group_directory(tenant)
    response = client.post("/api/groups/list", headers=admin, json={"tenant_id": tenant})
    assert response.status_code == 200
    by_name = {group["group_name"]: group for group in response.json()["data"]}
    assert by_name["Edited in Casdoor"]["group_id"] == child_id
    assert by_name["Edited in Casdoor"]["parent_group_id"] == parent_id
    imported = by_name["Provider child"]
    assert imported["parent_group_id"] == child_id
    assert client.get(f"/api/groups/{child_id}/members", headers=admin).json()["data"] == []
    imported_members = client.get(f"/api/groups/{imported['group_id']}/members", headers=admin).json()["data"]
    assert [user["id"] for user in imported_members] == ["member"]

    before = list(writes)
    assert client.put(f"/api/groups/{parent_id}", headers=admin,
                      json={"parent_group_id": child_id}).status_code == 400
    assert client.put(f"/api/groups/{child_id}", headers=foreign,
                      json={"group_name": "Forbidden"}).status_code == 401
    assert client.post(f"/api/groups/{child_id}/members", headers=admin,
                       json={"user_id": "local"}).status_code == 400
    assert client.get(f"/api/groups/{imported['group_id']}/members", headers=foreign).status_code == 403
    assert client.get(f"/api/groups/{imported['group_id']}/members").status_code == 401
    assert writes == before
