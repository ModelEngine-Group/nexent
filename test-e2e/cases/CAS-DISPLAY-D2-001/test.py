# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""CAS-DISPLAY-D2-001: existing HTTP contracts with optional CAS metadata."""

from contextlib import contextmanager
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session, registry
from sqlalchemy.pool import StaticPool

from apps import group_app, user_app
from database import user_tenant_db, user_identity_db
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


@pytest.mark.parametrize("cas_session", [False, True])
def test_cas_username_search(monkeypatch, cas_session):
    """Exercise HTTP, service and SQL matching before count and pagination."""
    metadata = MetaData()
    users = Table("users", metadata,
        Column("user_id", String, primary_key=True), Column("tenant_id", String),
        Column("user_email", String), Column("user_role", String),
        Column("create_time", Integer), Column("delete_flag", String))
    bindings = Table("bindings", metadata,
        Column("oauth_account_id", Integer, primary_key=True), Column("user_id", String),
        Column("provider", String), Column("provider_username", String), Column("delete_flag", String))
    mapper = registry()
    user_model, binding_model = type("User", (), {}), type("Binding", (), {})
    mapper.map_imperatively(user_model, users)
    mapper.map_imperatively(binding_model, bindings)
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(users.insert(), [
            {"user_id": key, "tenant_id": "other" if key == "foreign" else "tenant",
             "user_email": email, "user_role": "USER", "create_time": i,
             "delete_flag": "Y" if key == "deleted" else "N"}
            for i, (key, email) in enumerate([
                ("a", "alpha@test"), ("b", "beta@test"), ("mail", "bob@test"),
                ("foreign", "foreign@test"), ("deleted", "deleted@test"), ("removed", "removed@test"),
            ])
        ])
        connection.execute(bindings.insert(), [
            {"oauth_account_id": i, "user_id": key, "provider": "cas",
             "provider_username": "Bob", "delete_flag": "Y" if key == "removed" else "N"}
            for i, key in enumerate(["a", "a", "b", "foreign", "deleted", "removed"], 1)
        ])
    @contextmanager
    def db_session():
        with Session(engine) as session:
            yield session
            assert not session.new and not session.dirty and not session.deleted
    for module in (user_tenant_db, user_identity_db):
        monkeypatch.setattr(module, "get_db_session", db_session)
        monkeypatch.setattr(module, "UserTenant", user_model)
        monkeypatch.setattr(module, "UserOAuthAccount", binding_model, raising=False)
    monkeypatch.setattr(user_tenant_db, "as_dict", lambda row: {
        column.name: getattr(row, column.name) for column in users.columns
    })
    monkeypatch.setattr(user_service, "query_groups_by_users", lambda _: {})
    monkeypatch.setattr(user_app, "get_current_user_context", lambda _: ("admin", "tenant", "ADMIN"))
    monkeypatch.setattr(user_app, "extract_session_id_from_authorization", lambda _: "cas-session" if cas_session else None)
    app = FastAPI()
    app.include_router(user_app.router)
    with TestClient(app) as client:
        def search(text, page=1):
            response = client.post("/users/list", json={
                "tenant_id": "tenant", "search": text, "page": page, "page_size": 1,
                "sort_by": "created_at", "sort_order": "asc",
            })
            assert response.status_code == 200, response.text
            return response.json()
        first = search(" BoB ")
        assert first["total"] == (3 if cas_session else 1)
        assert first["pagination"]["total_pages"] == first["total"]
        assert first["data"][0]["id"] == ("a" if cas_session else "mail")
        assert first["data"][0]["username"] == ("alpha@test" if cas_session else "bob@test")
        second = search("bob", 2)
        assert [row["id"] for row in second["data"]] == (["b"] if cas_session else [])
        assert second["total"] == first["total"]
        email = search("alpha@")
        assert email["total"] == 1 and email["data"][0]["username"] == "alpha@test"
        assert search("no-such-user")["total"] == 0
        assert search("   ")["total"] == 4
    engine.dispose()
