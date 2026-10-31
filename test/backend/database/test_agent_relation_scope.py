# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Keep persisted child relations tenant-scoped while protecting shared identities."""

from types import SimpleNamespace

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session, registry

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from management.db.agent import repository


@pytest.fixture
def relation_store(monkeypatch):
    metadata = MetaData()
    relations = Table(
        "agent_relations", metadata,
        Column("id", Integer, primary_key=True),
        Column("parent_agent_id", Integer),
        Column("selected_agent_id", Integer),
        Column("selected_agent_version_no", Integer),
        Column("tenant_id", String),
        Column("version_no", Integer),
        Column("delete_flag", String),
    )
    agents = Table(
        "agents", metadata,
        Column("agent_id", Integer, primary_key=True),
        Column("tenant_id", String),
        Column("agent_origin", String),
        Column("delete_flag", String),
    )
    mapper = registry()

    class Relation:
        pass

    mapper.map_imperatively(Relation, relations)
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    owners = ("tenant-a", "tenant-b", ASSET_OWNER_TENANT_ID)
    with engine.begin() as connection:
        connection.execute(relations.insert(), [
            {
                "parent_agent_id": parent, "selected_agent_id": child,
                "selected_agent_version_no": 7, "tenant_id": owner,
                "version_no": version, "delete_flag": deleted,
            }
            for owner in owners
            for parent, child, version, deleted in (
                (10, 20, 2, "N"), (10, 21, 1, "N"),
                (10, 22, 2, "Y"), (11, 23, 2, "N"),
            )
        ])
        connection.execute(agents.insert(), [
            {"agent_id": 100, "tenant_id": ASSET_OWNER_TENANT_ID,
             "agent_origin": "SYSTEM", "delete_flag": "N"},
            {"agent_id": 101, "tenant_id": "tenant-a",
             "agent_origin": "USER", "delete_flag": "N"},
        ])
    monkeypatch.setattr(repository, "AgentRelation", Relation)
    monkeypatch.setattr(repository, "AgentInfo", SimpleNamespace(**dict(agents.c.items())))
    monkeypatch.setattr(repository, "get_db_session", lambda: Session(engine))
    monkeypatch.setattr(repository, "as_dict", lambda row: {
        column.name: getattr(row, column.name) for column in relations.c
    })
    try:
        yield
    finally:
        mapper.dispose()
        engine.dispose()


@pytest.mark.parametrize("owner", ["tenant-a", ASSET_OWNER_TENANT_ID])
@pytest.mark.parametrize("query", ["ids", "relations"])
def test_child_relations_use_only_the_explicit_owner(relation_store, owner, query):
    if query == "ids":
        assert repository.query_sub_agents_id_list(10, owner, version_no=2) == [20]
    else:
        result = repository.query_sub_agent_relations(10, owner, version_no=2)
        assert [(row["selected_agent_id"], row["tenant_id"],
                 row["selected_agent_version_no"]) for row in result] == [(20, owner, 7)]


@pytest.mark.parametrize("query", [
    repository.query_sub_agents_id_list, repository.query_sub_agent_relations,
])
def test_missing_owner_has_no_shared_relation_fallback(relation_store, query):
    assert query(10, "missing-tenant", version_no=2) == []


def test_shared_system_identity_remains_protected_from_business_tenant(relation_store):
    assert repository.is_system_agent(100, "tenant-a") is True
    assert repository.is_system_agent(101, "tenant-a") is False
    with pytest.raises(ValueError, match="managed by the platform"):
        repository.insert_related_agent(100, 20, "tenant-a", "user-a")
