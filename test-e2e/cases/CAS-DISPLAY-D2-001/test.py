# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""CAS-DISPLAY-D2-001: existing HTTP contracts with optional CAS metadata."""

from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from apps import group_app, user_app
from services import group_service, user_identity_service, user_service

pytestmark = [pytest.mark.case_id("CAS-DISPLAY-D2-001"), pytest.mark.stage("D2")]


@pytest.mark.parametrize("lookup_failed", [False, True])
def test_cas_display_d2_001(monkeypatch, lookup_failed):
    app = FastAPI()
    app.include_router(user_app.router)
    app.include_router(group_app.router)
    client = TestClient(app)
    monkeypatch.setattr(user_app, "get_current_user_context", lambda _: ("admin", "tenant", "ADMIN"))
    rows = [{"user_id": "display-user", "user_email": "member@example.test",
             "user_role": "USER", "tenant_id": "tenant"}]
    list_users = Mock(return_value={"users": rows, "total": 11})
    monkeypatch.setattr(user_service, "get_users_by_tenant_id", list_users)
    monkeypatch.setattr(user_service, "query_groups_by_users", Mock(return_value={}))
    monkeypatch.setattr(group_service, "query_groups", Mock(return_value={"group_id": 7}))
    monkeypatch.setattr(group_service, "query_group_users", Mock(return_value=[{"user_id": "display-user"}]))
    monkeypatch.setattr(group_service, "get_user_tenant_by_user_id", Mock(return_value=rows[0]))
    lookup = Mock(return_value={"display-user": {"cas_username": "示例用户", "email": "member@example.test"}})
    if lookup_failed:
        lookup.side_effect = RuntimeError("controlled identity lookup outage")
    monkeypatch.setattr(user_identity_service, "get_cas_identities", lookup)
    write_user = Mock(side_effect=AssertionError("read request must not write accounts"))
    write_members = Mock(side_effect=AssertionError("read request must not change membership"))
    monkeypatch.setattr(user_service, "update_user_tenant_role", write_user)
    monkeypatch.setattr(group_service, "add_user_to_group", write_members)

    response = client.post("/users/list", json={
        "tenant_id": "tenant", "page": 2, "page_size": 5,
        "sort_by": "username", "sort_order": "asc", "search": "member@", "roles": ["USER"], "group_ids": [7],
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 11
    assert payload["pagination"] == {"page": 2, "page_size": 5, "total": 11, "total_pages": 3}
    user = payload["data"][0]
    assert user["id"] == "display-user"
    assert user["username"] == "member@example.test"
    assert user["role"] == "USER"
    assert user["tenant_id"] == "tenant"
    assert user["group_names"] == []
    list_users.assert_called_once_with(tenant_id="tenant", page=2, page_size=5, sort_by="username",
                                       sort_order="asc", search="member@", roles=["USER"], group_ids=[7])
    members = client.get("/groups/7/members")
    assert members.status_code == 200, members.text
    member = members.json()["data"][0]
    assert {key: member[key] for key in ("id", "username", "role")} == {
        "id": "display-user", "username": "member@example.test", "role": "USER",
    }
    if lookup_failed:
        assert "cas_username" not in user
        assert "cas_username" not in member
    else:
        assert user["cas_username"] == member["cas_username"] == "示例用户"
    assert lookup.call_count == 2
    assert all(call.args[0] == {"display-user"} for call in lookup.call_args_list)
    write_user.assert_not_called()
    write_members.assert_not_called()
