# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute user search predicates against isolated relational records."""

from contextlib import contextmanager

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session, registry

from management.db.identity import user_tenant as user_db


@pytest.fixture
def search_db(monkeypatch):
    metadata = MetaData()
    tables = {
        "UserTenant": Table("users", metadata,
            Column("user_id", String, primary_key=True), Column("tenant_id", String),
            Column("user_email", String), Column("user_role", String),
            Column("create_time", Integer), Column("delete_flag", String)),
        "UserOAuthAccount": Table("bindings", metadata,
            Column("oauth_account_id", Integer, primary_key=True), Column("user_id", String),
            Column("provider", String), Column("provider_username", String), Column("delete_flag", String)),
        "TenantGroupInfo": Table("groups", metadata,
            Column("group_id", Integer, primary_key=True), Column("tenant_id", String), Column("delete_flag", String)),
        "TenantGroupUser": Table("members", metadata,
            Column("id", Integer, primary_key=True), Column("user_id", String),
            Column("group_id", Integer), Column("delete_flag", String)),
    }
    mapper = registry()
    for name, table in tables.items():
        model = type(name, (), {})
        mapper.map_imperatively(model, table)
        monkeypatch.setattr(user_db, name, model, raising=False)
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    user_rows = [
        ("a", "alpha@test", "ADMIN"), ("b", "beta@test", "ADMIN"),
        ("mail", "bob@test", "USER"), ("foreign", "foreign@test", "ADMIN"),
        ("deleted", "deleted@test", "ADMIN"), ("removed", "removed@test", "USER"),
        ("github", "github@test", "USER"), ("blank", "fallback@test", "USER"),
        ("missing", "missing@test", "USER"),
    ]
    with engine.begin() as connection:
        connection.execute(tables["UserTenant"].insert(), [
            {"user_id": key, "user_email": email, "user_role": role,
             "tenant_id": "other" if key == "foreign" else "tenant", "create_time": i,
             "delete_flag": "Y" if key == "deleted" else "N"}
            for i, (key, email, role) in enumerate(user_rows)
        ])
        connection.execute(tables["UserOAuthAccount"].insert(), [
            {"oauth_account_id": i, "user_id": key, "provider_username": name,
             "provider": "github" if key == "github" else "cas",
             "delete_flag": "Y" if key == "removed" else "N"}
            for i, (key, name) in enumerate([
                ("a", "  Bob  "), ("a", "Bob"), ("b", "Bob"), ("foreign", "Bob"),
                ("deleted", "Bob"), ("removed", "Bob"), ("github", "Bob"),
                ("blank", " \t"), ("missing", None),
            ], 1)
        ])
        connection.execute(tables["TenantGroupInfo"].insert(), [
            {"group_id": 7, "tenant_id": "tenant", "delete_flag": "N"},
            {"group_id": 8, "tenant_id": "other", "delete_flag": "N"},
        ])
        connection.execute(tables["TenantGroupUser"].insert(), [
            {"id": 1, "user_id": "a", "group_id": 7, "delete_flag": "N"},
            {"id": 2, "user_id": "b", "group_id": 7, "delete_flag": "Y"},
            {"id": 3, "user_id": "mail", "group_id": 8, "delete_flag": "N"},
        ])
    with Session(engine) as session:
        @contextmanager
        def db_session():
            yield session
        monkeypatch.setattr(user_db, "get_db_session", db_session)
        monkeypatch.setattr(user_db, "as_dict", lambda row: {
            column.name: getattr(row, column.name) for column in tables["UserTenant"].columns
        })
        yield session
        assert not session.new and not session.dirty and not session.deleted
    engine.dispose()


@pytest.mark.parametrize("search,cas,expected", [
    (" BoB ", True, ["a", "b", "mail"]),
    ("BO", True, ["a", "b", "mail"]),
    ("bob", False, ["mail"]),
    ("alpha@", True, ["a"]),
    ("alpha@", False, ["a"]),
    ("fallback@", True, ["blank"]),
    ("missing@", True, ["missing"]),
    ("no-such-name", True, []),
    ("   ", True, ["a", "b", "mail", "removed", "github", "blank", "missing"]),
])
def test_name_email_matching_and_active_tenant_boundaries(search_db, search, cas, expected):
    result = user_db.get_users_by_tenant_id(
        "tenant", page=None, page_size=None, sort_order="asc", search=search,
        search_cas_username=cas,
    )
    assert [row["user_id"] for row in result["users"]] == expected
    assert result["total"] == len(expected)
    assert all(row["tenant_id"] == "tenant" and row["delete_flag"] == "N" for row in result["users"])


def test_duplicate_names_and_bindings_do_not_change_totals_or_pages(search_db):
    pages = [user_db.get_users_by_tenant_id(
        "tenant", page=page, page_size=1, sort_order="asc", search="bob", search_cas_username=True,
    ) for page in range(1, 5)]
    assert [page["total"] for page in pages] == [3, 3, 3, 3]
    assert [[row["user_id"] for row in page["users"]] for page in pages] == [["a"], ["b"], ["mail"], []]
    assert pages[0]["users"][0]["user_email"] == "alpha@test"
    descending = user_db.get_users_by_tenant_id("tenant", search="bob", search_cas_username=True)
    assert [row["user_id"] for row in descending["users"]] == ["mail", "b", "a"]


def test_roles_and_active_tenant_group_membership_remain_required(search_db):
    result = user_db.get_users_by_tenant_id(
        "tenant", search="bob", roles=["ADMIN"], group_ids=[7], search_cas_username=True,
    )
    assert result["total"] == 1
    assert [row["user_id"] for row in result["users"]] == ["a"]
    assert user_db.get_users_by_tenant_id(
        "tenant", search="bob", group_ids=[8], search_cas_username=True,
    )["total"] == 0


def test_default_search_and_database_failure_keep_existing_contract(search_db, monkeypatch):
    assert user_db.get_users_by_tenant_id("tenant", search="bob")["total"] == 1
    def fail(*args):
        raise RuntimeError("controlled database outage")
    monkeypatch.setattr(search_db, "query", fail)
    with pytest.raises(RuntimeError, match="controlled database outage"):
        user_db.get_users_by_tenant_id("tenant", search="bob", search_cas_username=True)
