# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise the repository reference count against a real relational query."""

from contextlib import contextmanager

import pytest
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session, registry

@pytest.fixture
def database(monkeypatch):
    from management.db.skill import catalog

    metadata = MetaData()
    skills = Table(
        "skills", metadata, Column("skill_id", Integer, primary_key=True), Column("tenant_id", String),
        Column("source_repository_id", Integer), Column("delete_flag", String, default="N"),
    )
    agents = Table(
        "agents", metadata, Column("agent_id", Integer, primary_key=True), Column("tenant_id", String),
        Column("version_no", Integer, primary_key=True, default=0), Column("current_version_no", Integer),
        Column("delete_flag", String, default="N"),
    )
    bindings = Table(
        "bindings", metadata, Column("id", Integer, primary_key=True),
        Column("agent_id", Integer), Column("tenant_id", String),
        Column("skill_id", Integer), Column("version_no", Integer, default=0),
        Column("enabled", Boolean, default=True), Column("delete_flag", String, default="N"),
    )
    engine = create_engine("sqlite://")
    metadata.create_all(engine)

    @contextmanager
    def session_scope():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(catalog, "get_db_session", session_scope)
    mappings = registry()
    for name, table in (("SkillInfo", skills), ("AgentInfo", agents), ("SkillInstance", bindings)):
        model = type(name, (), {})
        mappings.map_imperatively(model, table)
        monkeypatch.setattr(catalog, name, model)

    def insert(table, **values):
        with engine.begin() as connection:
            connection.execute(table.insert().values(**values))

    yield catalog, insert, skills, agents, bindings
    mappings.dispose()
    engine.dispose()


@pytest.mark.parametrize("source_tenant", ["tenant-a", None, "asset_owner_tenant_id"])
def test_counts_distinct_agents_using_source_or_linked_copy(database, source_tenant):
    catalog, insert, skills, agents, bindings = database
    insert(skills, skill_id=1, tenant_id=source_tenant)
    insert(skills, skill_id=2, tenant_id="tenant-a", source_repository_id=10)
    insert(skills, skill_id=3, tenant_id="tenant-a", source_repository_id=10)
    for agent_id in (100, 101, 102):
        insert(agents, agent_id=agent_id, tenant_id="tenant-a", current_version_no=2)
    insert(bindings, agent_id=100, tenant_id="tenant-a", skill_id=1)
    insert(bindings, agent_id=100, tenant_id="tenant-a", skill_id=2, version_no=2)
    insert(bindings, agent_id=100, tenant_id="tenant-a", skill_id=3)
    insert(bindings, agent_id=101, tenant_id="tenant-a", skill_id=2, version_no=2)
    insert(bindings, agent_id=102, tenant_id="tenant-a", skill_id=3, enabled=False)

    assert catalog.count_skill_repository_agent_references(10, 1, "tenant-a") == 3


def test_excludes_foreign_history_deleted_and_unlinked_rows(database):
    catalog, insert, skills, agents, bindings = database
    insert(skills, skill_id=1, tenant_id="tenant-a")
    insert(skills, skill_id=2, tenant_id="tenant-a", source_repository_id=20)
    insert(skills, skill_id=3, tenant_id="tenant-b", source_repository_id=10)
    insert(skills, skill_id=4, tenant_id="tenant-a", source_repository_id=10, delete_flag="Y")
    insert(skills, skill_id=5, tenant_id="tenant-a")
    for agent_id in range(100, 105):
        insert(agents, agent_id=agent_id, tenant_id="tenant-a", current_version_no=2)
    insert(agents, agent_id=105, tenant_id="tenant-a", delete_flag="Y")
    insert(agents, agent_id=106, tenant_id="tenant-b")
    insert(bindings, agent_id=100, tenant_id="tenant-a", skill_id=1, version_no=1)
    insert(bindings, agent_id=101, tenant_id="tenant-a", skill_id=2)
    insert(bindings, agent_id=102, tenant_id="tenant-a", skill_id=3)
    insert(bindings, agent_id=103, tenant_id="tenant-a", skill_id=4)
    insert(bindings, agent_id=104, tenant_id="tenant-a", skill_id=1, delete_flag="Y")
    insert(bindings, agent_id=104, tenant_id="tenant-a", skill_id=5)
    insert(bindings, agent_id=105, tenant_id="tenant-a", skill_id=1)
    insert(bindings, agent_id=106, tenant_id="tenant-b", skill_id=1)
    insert(bindings, agent_id=106, tenant_id="tenant-a", skill_id=1)

    assert catalog.count_skill_repository_agent_references(10, 1, "tenant-a") == 0
