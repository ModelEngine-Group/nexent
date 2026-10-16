# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Execute the Agent binding filter SQL against isolated in-memory tables."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, event
from sqlalchemy.orm import Session

import database.agent_db as agent_db
from consts.const import ASSET_OWNER_TENANT_ID


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite://")
    schema = agent_db.AgentInfo.__table__.schema
    metadata = MetaData(schema=schema)
    agents = Table(agent_db.AgentInfo.__tablename__, metadata,
                   Column("agent_id", Integer, primary_key=True), Column("version_no", Integer, primary_key=True),
                   Column("tenant_id", String), Column("delete_flag", String), Column("display_name", String),
                   Column("name", String), Column("duty_prompt", String))
    versions = Table(agent_db.AgentVersion.__tablename__, metadata,
                     Column("id", Integer, primary_key=True), Column("agent_id", Integer),
                     Column("version_no", Integer), Column("delete_flag", String))
    statements = []

    def record_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_sql)
    with engine.connect() as connection:
        if schema:
            connection.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS \"{schema}\"")
        metadata.create_all(connection)
        monkeypatch.setattr(agent_db, "get_db_session", lambda: Session(bind=connection))
        tools = MagicMock(return_value=[])
        monkeypatch.setattr(agent_db, "query_tool_knowledge_references", tools)

        def add_agent(agent_id=7, version_no=0, tenant_id="t1", delete_flag="N", display_name="Agent", name="Internal"):
            connection.execute(agents.insert().values(
                agent_id=agent_id, version_no=version_no, tenant_id=tenant_id, delete_flag=delete_flag,
                display_name=display_name, name=name, duty_prompt="Not needed by the deletion dialog",
            ))

        def add_version(version_no=1, delete_flag="N"):
            connection.execute(versions.insert().values(agent_id=7, version_no=version_no, delete_flag=delete_flag))

        yield add_agent, add_version, tools, statements
    engine.dispose()


@pytest.mark.parametrize("selected,param", [({"index_names": ["idx-1"]}, "index_names"), ({"kds_ids": ["kds-1"]}, "kds_list")])
def test_names_are_deduplicated_in_one_sql_and_return_only_used_fields(database, selected, param):
    add_agent, _, tools, statements = database
    add_agent()
    tools.return_value = [{"agent_id": 7, "version_no": 0}] * 2
    assert agent_db.query_knowledge_binding_agents(tenant_id="t1", **selected) == [
        {"agent_id": 7, "display_name": "Agent"},
    ]
    assert len(statements) == 1
    assert "duty_prompt" not in statements[0]
    resource_ids = set(next(iter(selected.values())))
    assert tools.call_args.args[1:] == (param, resource_ids)


@pytest.mark.parametrize("snapshot_flag,version_flag,expected", [
    ("N", "N", True), ("Y", "N", False), ("N", "Y", False), ("N", None, False),
])
def test_published_binding_requires_live_snapshot_and_version(database, snapshot_flag, version_flag, expected):
    add_agent, add_version, tools, statements = database
    add_agent(display_name="Current name")
    add_agent(version_no=1, delete_flag=snapshot_flag, display_name="Old name")
    if version_flag:
        add_version(delete_flag=version_flag)
    tools.return_value = [{"agent_id": 7, "version_no": 1}]
    assert agent_db.query_knowledge_binding_agents(tenant_id="t1", index_names=["idx"]) == (
        [{"agent_id": 7, "display_name": "Current name"}] if expected else []
    )
    assert len(statements) == 1


@pytest.mark.parametrize("tenant,delete_flag,expected", [
    ("t1", "N", True), (ASSET_OWNER_TENANT_ID, "N", True), ("other", "N", False), ("t1", "Y", False),
])
def test_tenant_and_deleted_agent_filtering_happens_in_sql(database, tenant, delete_flag, expected):
    add_agent, _, tools, _ = database
    add_agent(tenant_id=tenant, delete_flag=delete_flag)
    tools.return_value = [{"agent_id": 7, "version_no": 0}]
    assert agent_db.query_knowledge_binding_agents(tenant_id="t1", index_names=["idx"]) == (
        [{"agent_id": 7, "display_name": "Agent"}] if expected else []
    )


def test_missing_agent_is_not_listed(database):
    _, _, tools, _ = database
    tools.return_value = [{"agent_id": 999, "version_no": 0}, {"agent_id": None, "version_no": 0}]
    assert agent_db.query_knowledge_binding_agents(tenant_id="t1", kds_ids=["kds"]) == []


def test_empty_bindings_do_not_issue_agent_queries(database):
    _, _, _, statements = database
    assert agent_db.query_knowledge_binding_agents(tenant_id="t1", index_names=["missing"]) == []
    assert statements == []


def test_sql_applies_name_fallbacks_and_stable_order(database):
    add_agent, _, tools, _ = database
    add_agent(agent_id=7, display_name="", name="Internal name")
    add_agent(agent_id=8, display_name=None, name=None)
    tools.return_value = [{"agent_id": 7, "version_no": 0}, {"agent_id": 8, "version_no": 0}]
    assert agent_db.query_knowledge_binding_agents(tenant_id="t1", index_names=["idx"]) == [
        {"agent_id": 8, "display_name": "8"}, {"agent_id": 7, "display_name": "Internal name"},
    ]
