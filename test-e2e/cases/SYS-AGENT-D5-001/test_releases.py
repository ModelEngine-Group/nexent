# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real PostgreSQL release serialization and atomic failure recovery."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, insert, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from shared.postgres import apply_product_postgres_env, postgres_url

apply_product_postgres_env()

# Object storage and optional archive installation are outside this proof boundary.
with (
    patch(
        "nexent.storage.storage_client_factory.create_storage_client_from_config",
        return_value=MagicMock(),
    ),
    patch("nexent.storage.minio_config.MinIOStorageConfig.validate", lambda self: None),
):
    from contracts.constants.constants import ASSET_OWNER_TENANT_ID
    from contracts.errors.exceptions import WorkbenchAgentError
    from management.db.agent.models import AgentInfo, AgentVersion, AgentRelation
    from management.db.agent import repository
    from management.db.conversation import repository as history_db
    from management.db.conversation.models import (
        ConversationRecord, ConversationMessage, ConversationMessageUnit,
        ConversationSourceSearch, ConversationSourceImage,
    )
    from management.db.tool.models import ToolInstance, ToolInfo
    from management.db.skill.models import SkillInstance, SkillInfo, SkillToolRelation
    from management.services.agent import system as provider_module
    from management.services.agent import system_release as release_module
    from management.services.agent import system_initialize as initialize_module
    from management.db.skill import repository as skill_db
    from management.db.tool import repository as tool_db

pytestmark = [pytest.mark.case_id("SYS-AGENT-D5-001"), pytest.mark.stage("D5")]
HISTORY_MODELS = (ConversationRecord, ConversationMessage, ConversationMessageUnit, ConversationSourceSearch, ConversationSourceImage)


@pytest.fixture
def release_database(monkeypatch):
    schema = "test_system_release_" + uuid4().hex
    engine = create_engine(postgres_url(), pool_size=20).execution_options(
        schema_translate_map={"nexent": schema}
    )

    @contextmanager
    def transaction():
        with Session(engine) as session, session.begin():
            session.execute(text("SET LOCAL lock_timeout = '10s'"))
            session.execute(text("SET LOCAL statement_timeout = '20s'"))
            yield session

    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
        AgentInfo.__table__.create(connection)
        AgentVersion.__table__.create(connection)
        for model in (*HISTORY_MODELS, ToolInfo, ToolInstance, SkillInfo, SkillInstance, SkillToolRelation, AgentRelation):
            model.__table__.create(connection)
    with engine.begin() as connection:
        connection.execute(text(f"CREATE TABLE {schema}.schema_migrations (migration_id text PRIMARY KEY, checksum text NOT NULL, status text DEFAULT 'applied', source_file text)"))
    monkeypatch.setattr(release_module, "get_db_session", transaction)
    monkeypatch.setattr(initialize_module, "get_db_session", transaction)
    monkeypatch.setattr(tool_db, "get_db_session", transaction)
    monkeypatch.setattr(skill_db, "get_db_session", transaction)
    monkeypatch.setattr(repository, "get_db_session", transaction)
    monkeypatch.setattr(history_db, "get_db_session", transaction)
    with engine.begin() as connection:
        connection.execute(insert(ToolInfo).values(tool_id=1, name="knowledge_base_search", class_name="KnowledgeBaseSearchTool", author=ASSET_OWNER_TENANT_ID, source="local", params=[], is_available=True))
        connection.execute(insert(SkillInfo).values(skill_id=1, skill_name="pdf", tenant_id=ASSET_OWNER_TENANT_ID, source="official"))
    monkeypatch.setattr(initialize_module, "prepare_shared_resources", lambda provider: (
        [{"tool_id": 1, "params": [{"name": "top_k", "default": 5}]}], [{"skill_id": 1}],
    ))
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def records(engine, model):
    with engine.connect() as connection:
        return sorted((dict(row) for row in connection.execute(select(model.__table__)).mappings()), key=lambda row: repr(sorted(row.items())))


def database_state(engine):
    return {model.__tablename__: records(engine, model) for model in (
        AgentInfo, AgentVersion, AgentRelation, ToolInfo, SkillInfo, SkillToolRelation, ToolInstance, SkillInstance, *HISTORY_MODELS,
    )}


def assert_creator_identity(engine, agent_id):
    identities = [row for row in records(engine, AgentInfo) if row["agent_id"] == agent_id]
    assert len(identities) == 1
    assert identities[0]["version_no"] == 0
    assert all(identities[0][key] is None for key in ("prompt", "current_version_no", "system_revision"))
    assert identities[0]["tenant_id"] == ASSET_OWNER_TENANT_ID
    for model in (AgentVersion, ToolInstance, SkillInstance):
        assert not [row for row in records(engine, model) if row["agent_id"] == agent_id]


def run_migration_sql(engine, filename):
    migration = Path(__file__).resolve().parents[3] / "deploy/sql/migrations" / filename
    schema = engine.get_execution_options()["schema_translate_map"]["nexent"]
    sql = migration.read_text(encoding="utf-8").replace("nexent.", schema + ".").replace("'nexent'", "'" + schema + "'")
    with engine.begin() as connection:
        with connection.connection.driver_connection.cursor() as cursor:
            cursor.execute(sql)


def run_legacy_sql(engine):
    run_migration_sql(engine, "v2.8.1_001_shared_system_agents.sql")


def run_creator_sql(engine):
    run_migration_sql(engine, "v2.8.1_002_shared_creator_identities.sql")


def run_history_sql(engine):
    run_migration_sql(engine, "v2.8.1_003_creator_conversation_targets.sql")


def initialize_installation(engine):
    """Compose independent deployment steps; production Python returns only Workbench."""
    run_creator_sql(engine)
    run_history_sql(engine)
    workbench = initialize_module.initialize_system_agents()
    creators = {row["system_key"]: row["agent_id"] for row in records(engine, AgentInfo)
                if row["agent_origin"] == "SYSTEM" and row["system_key"] in ("nl2agent_main", "nl2skill_main") and row["version_no"] == 0}
    return {**workbench, **creators}


def migration_marker(engine):
    schema = engine.get_execution_options()["schema_translate_map"]["nexent"]
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT migration_id FROM {schema}.schema_migrations")).scalars().all()


def test_fresh_install_initialization_and_publication_are_separate(release_database):
    engine = release_database
    run_legacy_sql(engine)
    assert not records(engine, AgentInfo)
    run_creator_sql(engine)
    run_history_sql(engine)
    assert {row["system_key"] for row in records(engine, AgentInfo)} == {"nl2agent_main", "nl2skill_main"}
    creators = records(engine, AgentInfo)
    with pytest.raises(WorkbenchAgentError, match="system_agent_not_ready"):
        release_module.release_system_agents(app_version="2.8.0")
    first = initialize_module.initialize_system_agents()
    assert set(first) == {"workbench_main"}
    before = database_state(engine)
    assert len(before[AgentInfo.__tablename__]) == 3
    assert all(row["version_no"] == 0 for row in records(engine, AgentInfo))
    assert not records(engine, AgentVersion)
    assert initialize_module.initialize_system_agents() == first
    assert database_state(engine) == before
    release_module.release_system_agents(app_version="2.8.0")
    assert [row for row in records(engine, AgentInfo) if row["system_key"] in ("nl2agent_main", "nl2skill_main")] == creators
    published = database_state(engine)
    for run in (run_legacy_sql, run_creator_sql, run_history_sql):
        run(engine)
    assert database_state(engine) == published
    assert set(migration_marker(engine)) == {"__once_shared_system_agents_v1", "__once_shared_creator_identities_v1", "__once_creator_conversation_targets_v1"}


def test_shared_tool_scan_has_no_tenant_tag_library_dependency(release_database):
    engine = release_database
    # This fresh-scan variant does not use the fixture's explicitly numbered tool.
    with engine.begin() as connection:
        connection.execute(delete(ToolInfo))
    # No tag tables/libraries exist in this disposable shared-catalog schema.
    tool = SimpleNamespace(name="deepseek_search", source="local", params=[])
    tool_db.update_tool_table_from_scan_tool_list(ASSET_OWNER_TENANT_ID, "system", [tool])
    registered = [row for row in records(engine, ToolInfo) if row["name"] == "deepseek_search"]
    assert len(registered) == 1
    assert registered[0]["author"] == ASSET_OWNER_TENANT_ID
    assert registered[0]["is_available"] is True
    tool_id = registered[0]["tool_id"]
    tool_db.update_tool_table_from_scan_tool_list(ASSET_OWNER_TENANT_ID, "system", [tool])
    repeated = [row for row in records(engine, ToolInfo) if row["name"] == "deepseek_search"]
    assert len(repeated) == 1
    assert repeated[0]["tool_id"] == tool_id


def test_concurrent_explicit_releases(release_database):
    engine = release_database

    def concurrent(revision):
        gate = Barrier(16)
        def initialize(index):
            gate.wait(timeout=10)
            return release_module.release_system_agents(app_version=revision)
        with ThreadPoolExecutor(max_workers=16) as executor:
            return list(executor.map(initialize, range(16)))

    identities = initialize_installation(engine)
    first = concurrent("2.8.0")
    assert all(item == first[0] for item in first)
    before = database_state(engine)
    second = concurrent("2.8.1")
    assert all(item == second[0] for item in second)
    assert first[0]["workbench_main"] == second[0]["workbench_main"]
    assert "nl2agent_main" not in second[0]
    assert second[0]["workbench_version"] == 2
    assert len(records(engine, AgentInfo)) == 5
    assert len(records(engine, AgentVersion)) == 2
    for model in (ToolInstance, SkillInstance):
        assert sorted(row["version_no"] for row in records(engine, model)) == [0, 1, 2]
        prior = [row for row in before[model.__tablename__] if row["version_no"] == 1]
        assert prior == [row for row in records(engine, model) if row["version_no"] == 1]
    assert_creator_identity(engine, identities["nl2agent_main"])
    assert_creator_identity(engine, identities["nl2skill_main"])


@pytest.mark.parametrize("upgrade", [False, True])
def test_publication_failure_rolls_back(release_database, upgrade):
    engine = release_database
    identities = initialize_installation(engine)
    if upgrade:
        release_module.release_system_agents(app_version="2.8.0")
    before = database_state(engine)

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("INSERT INTO") and "ag_tenant_agent_version_t" in statement:
            raise RuntimeError("publication failure")
    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="publication failure"):
            release_module.release_system_agents(app_version="2.8.1")
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert database_state(engine) == before
    result = release_module.release_system_agents(app_version="2.8.1")
    assert result["workbench_version"] == (2 if upgrade else 1)
    assert_creator_identity(engine, identities["nl2agent_main"])
    assert_creator_identity(engine, identities["nl2skill_main"])


def test_workbench_rollback_uses_saved_bindings(release_database, monkeypatch):
    engine = release_database
    initialize_installation(engine)
    first = release_module.release_system_agents(app_version="2.8.0")
    original = database_state(engine)
    with engine.begin() as connection:
        for model in (ToolInstance, SkillInstance):
            connection.execute(delete(model).where(model.version_no == 0))
    release_module.release_system_agents(app_version="2.8.1")
    before = database_state(engine)
    with pytest.raises(WorkbenchAgentError, match="system_agent_revision_ahead"):
        release_module.release_system_agents(app_version="2.7.0")
    assert database_state(engine) == before
    release_module.select_workbench_version(1)
    ref = provider_module.SystemAgentProvider(app_version="2.8.1").get_workbench_main_ref("tenant-b")
    assert ref.agent_id == first["workbench_main"] and ref.version_no == 1
    assert [row for row in records(engine, ToolInstance) if row["version_no"] == ref.version_no] == [row for row in original[ToolInstance.__tablename__] if row["version_no"] == 1]
    assert [row for row in records(engine, SkillInstance) if row["version_no"] == ref.version_no] == [row for row in original[SkillInstance.__tablename__] if row["version_no"] == 1]
    assert tool_db.search_tools_for_sub_agent(ref.agent_id, "tenant-b", ref.version_no)[0]["tool_id"] == 1
    assert skill_db.search_skills_for_agent(ref.agent_id, "tenant-b", ref.version_no)[0]["skill_id"] == 1
    assert not tool_db.search_tools_for_sub_agent(ref.agent_id, "tenant-b", 2)
    snapshot = repository.search_agent_info_by_agent_id(ref.agent_id, "tenant-b", ref.version_no)
    old_snapshot = next(row for row in original[AgentInfo.__tablename__] if row["version_no"] == 1)
    assert snapshot["prompt"] == old_snapshot["prompt"]
    # Repeating the current product release preserves an explicitly selected pointer.
    assert release_module.release_system_agents(app_version="2.8.1")["workbench_version"] == 1


def seed_legacy(engine, revision="2.7.0"):
    with engine.begin() as connection:
        for agent_id, tenant in ((9001, "tenant-a"), (9002, "tenant-b")):
            resource_id = agent_id - 8999
            connection.execute(insert(ToolInfo).values(tool_id=resource_id, name="knowledge_base_search",
                class_name="KnowledgeBaseSearchTool", author=tenant, source="local", params=[]))
            connection.execute(insert(SkillInfo).values(skill_id=resource_id, skill_name="pdf_1",
                tenant_id=tenant, source="official"))
            connection.execute(insert(SkillToolRelation).values(skill_id=resource_id, tool_id=resource_id))
            for version in (0, 1, *([3] if agent_id == 9002 else [])):
                connection.execute(insert(AgentInfo).values(agent_id=agent_id, tenant_id=tenant, version_no=version,
                    name="workbench_main", system_key="workbench_main", agent_origin="SYSTEM", enabled=True,
                    prompt=f"legacy prompt v{version}", current_version_no=1 if version == 0 else None,
                    system_revision=revision, created_by="owner", updated_by="owner"))
                if version:
                    connection.execute(insert(AgentVersion).values(agent_id=agent_id, tenant_id=tenant,
                        version_no=version, version_name=f"legacy-{version}", status="RELEASED"))
                connection.execute(insert(ToolInstance).values(agent_id=agent_id, tenant_id=tenant,
                    version_no=version, tool_id=resource_id, enabled=True, params={"legacy_version": version}))
                connection.execute(insert(SkillInstance).values(agent_id=agent_id, tenant_id=tenant,
                    version_no=version, skill_id=resource_id, enabled=True, config_values={"legacy_version": version}))
            for deleted in (False, True):
                conversation_id = agent_id * 10 + int(deleted)
                connection.execute(insert(ConversationRecord).values(conversation_id=conversation_id, agent_id=agent_id,
                    conversation_title="original title", created_by=tenant, updated_by=tenant,
                    delete_flag="Y" if deleted else "N", workbench_config={"mode": "generic_chat"}, workbench_config_version=7,
                    workbench_pinned_at=datetime(2026, 1, 1), last_activity_time=datetime(2026, 1, 2)))
                connection.execute(insert(ConversationMessage).values(message_id=conversation_id, conversation_id=conversation_id,
                    message_content="unchanged transcript", created_by=tenant, minio_files='["attachment.pdf"]'))
                connection.execute(insert(ConversationMessageUnit).values(unit_id=conversation_id, message_id=conversation_id,
                    conversation_id=conversation_id, unit_content="unchanged tool output", unit_type="other"))
                connection.execute(insert(ConversationSourceSearch).values(search_id=conversation_id, conversation_id=conversation_id,
                    message_id=conversation_id, unit_id=conversation_id, source_content="citation"))
                connection.execute(insert(ConversationSourceImage).values(image_id=conversation_id, conversation_id=conversation_id,
                    message_id=conversation_id, unit_id=conversation_id, image_url="image.png"))
        for model, column in ((ToolInfo, "tool_id"), (SkillInfo, "skill_id")):
            sequence = f"ag_{'tool' if model is ToolInfo else 'skill'}_info_t_{column}_seq"
            schema = engine.get_execution_options()["schema_translate_map"]["nexent"]
            connection.execute(text(f"SELECT setval('{schema}.{sequence}', 3)"))
        connection.execute(insert(AgentInfo).values(agent_id=9003, tenant_id="tenant-a", version_no=0,
            name="workbench_main", agent_origin="USER", prompt="user-owned"))
        connection.execute(insert(ToolInstance).values(agent_id=9003, tenant_id="tenant-a", version_no=0,
            tool_id=2, enabled=True, params={"private": True}))
        connection.execute(insert(SkillInstance).values(agent_id=9003, tenant_id="tenant-a", version_no=0,
            skill_id=2, enabled=True, config_values={"private": True}))

    schema = engine.get_execution_options()["schema_translate_map"]["nexent"]
    with engine.begin() as connection:
        connection.execute(text(f"CREATE FUNCTION {schema}.touch_history() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.update_time := now(); RETURN NEW; END; $$"))
        connection.execute(text(f"CREATE TRIGGER touch_history BEFORE UPDATE ON {schema}.{ConversationRecord.__tablename__} FOR EACH ROW EXECUTE FUNCTION {schema}.touch_history()"))


@pytest.mark.parametrize("legacy_revision", ["2.7.0", "2.8.0"])
@pytest.mark.parametrize("shared_catalog", [True, False])
def test_legacy_merge_preserves_history_and_deletes_duplicates(release_database, legacy_revision, shared_catalog):
    engine = release_database
    seed_legacy(engine, legacy_revision)
    if not shared_catalog:
        with engine.begin() as connection:
            connection.execute(delete(ToolInfo).where(ToolInfo.tool_id == 1))
            connection.execute(delete(SkillInfo).where(SkillInfo.skill_id == 1))
    original = database_state(engine)
    with pytest.raises(ValueError, match="SQL migration"):
        initialize_module.initialize_system_agents()
    assert database_state(engine) == original
    run_legacy_sql(engine)
    identities = initialize_installation(engine)
    result = release_module.release_system_agents(app_version="2.8.0")
    assert result["workbench_main"] == 9001
    assert result["workbench_version"] == 4
    agents = records(engine, AgentInfo)
    assert not any(row["agent_id"] == 9002 for row in agents)
    assert sorted(row["version_no"] for row in agents if row["agent_id"] == 9001) == [0, 1, 3, 4]
    assert all(row["tenant_id"] == ASSET_OWNER_TENANT_ID for row in agents if row["agent_origin"] == "SYSTEM")
    assert [row for row in agents if row["agent_id"] == 9003] == [row for row in original[AgentInfo.__tablename__] if row["agent_id"] == 9003]
    for model in HISTORY_MODELS[1:]:
        assert records(engine, model) == original[model.__tablename__]
    old_headers = original[ConversationRecord.__tablename__]
    for header in records(engine, ConversationRecord):
        prior = next(row for row in old_headers if row["conversation_id"] == header["conversation_id"])
        assert header == {**prior, "agent_id": 9001}
    for model in (ToolInstance, SkillInstance, AgentVersion):
        rows = records(engine, model)
        assert not any(row["agent_id"] == 9002 for row in rows)
        assert sorted(row["version_no"] for row in rows if row["version_no"] > 0) == [1, 3, 4]
    assert next(row for row in records(engine, ToolInstance) if row["version_no"] == 3)["params"] == {"legacy_version": 3}
    shared_tool = next(row["tool_id"] for row in records(engine, ToolInfo) if row["author"] == ASSET_OWNER_TENANT_ID)
    shared_skill = next(row["skill_id"] for row in records(engine, SkillInfo) if row["tenant_id"] == ASSET_OWNER_TENANT_ID)
    assert all(row["tool_id"] == shared_tool for row in records(engine, ToolInstance) if row["agent_id"] == 9001)
    assert all(row["skill_id"] == shared_skill for row in records(engine, SkillInstance) if row["agent_id"] == 9001)
    for model in (ToolInstance, SkillInstance):
        assert [row for row in records(engine, model) if row["agent_id"] == 9003] == [row for row in original[model.__tablename__] if row["agent_id"] == 9003]
    assert any(row["skill_id"] == shared_skill and row["tool_id"] == shared_tool for row in records(engine, SkillToolRelation))
    for model in (ToolInfo, SkillInfo, SkillToolRelation):
        for row in original[model.__tablename__]:
            assert row in records(engine, model)
    assert_creator_identity(engine, identities["nl2agent_main"])
    assert_creator_identity(engine, identities["nl2skill_main"])
    before_repeat = database_state(engine)
    run_legacy_sql(engine)
    assert set(migration_marker(engine)) == {"__once_shared_system_agents_v1", "__once_shared_creator_identities_v1", "__once_creator_conversation_targets_v1"}
    assert release_module.release_system_agents(app_version="2.8.0") == result
    assert database_state(engine) == before_repeat


def test_legacy_merge_failure_rolls_back(release_database):
    engine = release_database
    seed_legacy(engine)
    with engine.begin() as connection:
        connection.execute(delete(ToolInfo).where(ToolInfo.tool_id == 1))
        connection.execute(delete(SkillInfo).where(SkillInfo.skill_id == 1))
    before = database_state(engine)
    schema = engine.get_execution_options()["schema_translate_map"]["nexent"]
    with engine.begin() as connection:
        connection.execute(text(f"CREATE FUNCTION {schema}.fail_delete() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'deletion failure'; END; $$"))
        connection.execute(text(f"CREATE TRIGGER reject_delete BEFORE DELETE ON {schema}.ag_tenant_agent_t FOR EACH ROW EXECUTE FUNCTION {schema}.fail_delete()"))
    with pytest.raises(Exception, match="deletion failure"):
        run_legacy_sql(engine)
    assert database_state(engine) == before
    assert not migration_marker(engine)
    with engine.begin() as connection:
        connection.execute(text(f"DROP TRIGGER reject_delete ON {schema}.ag_tenant_agent_t"))
    run_legacy_sql(engine)
    assert migration_marker(engine) == ["__once_shared_system_agents_v1"]
    initialize_installation(engine)
    assert release_module.release_system_agents(app_version="2.8.0")["workbench_version"] == 4


def test_sql_completion_marker_prevents_forced_replay(release_database):
    engine = release_database
    seed_legacy(engine)
    run_legacy_sql(engine)
    before = database_state(engine)
    schema = engine.get_execution_options()["schema_translate_map"]["nexent"]
    with engine.begin() as connection:
        connection.execute(text(f"CREATE FUNCTION {schema}.reject_replay() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'migration body executed twice'; END; $$"))
        connection.execute(text(f"CREATE TRIGGER reject_replay BEFORE DELETE ON {schema}.ag_tenant_agent_t FOR EACH ROW EXECUTE FUNCTION {schema}.reject_replay()"))
    run_legacy_sql(engine)
    assert database_state(engine) == before
    assert migration_marker(engine) == ["__once_shared_system_agents_v1"]


@pytest.mark.parametrize("private_resource", ["mcp_tool", "custom_skill"])
def test_private_resources_abort_sql_migration_atomically(release_database, private_resource):
    engine = release_database
    seed_legacy(engine)
    with engine.begin() as connection:
        if private_resource == "mcp_tool":
            connection.execute(update(ToolInfo).where(ToolInfo.tool_id == 2).values(source="mcp"))
        else:
            connection.execute(update(SkillInfo).where(SkillInfo.skill_id == 2).values(source="custom"))
    before = database_state(engine)
    with pytest.raises(Exception, match="Cannot share"):
        run_legacy_sql(engine)
    assert database_state(engine) == before
    assert not migration_marker(engine)


def test_creator_history_migration_preserves_targets(release_database):
    engine = release_database
    schema = engine.get_execution_options()["schema_translate_map"]["nexent"]
    migration = Path(__file__).resolve().parents[3] / "deploy/sql/migrations/v2.8.1_003_creator_conversation_targets.sql"
    sql = migration.read_text(encoding="utf-8").replace("nexent.", schema + ".")
    with engine.begin() as connection:
        connection.execute(insert(AgentInfo).values(agent_id=201, version_no=0, tenant_id="tenant-a", name="draft", agent_origin="USER"))
        for conversation_id, mode, deleted in ((1, "agent_create", "N"), (2, "skill_create", "N"), (3, "agent_create", "Y"), (4, "generic_chat", "N")):
            connection.execute(insert(ConversationRecord).values(conversation_id=conversation_id, agent_id=201,
                created_by="user-a", delete_flag=deleted, workbench_config={"mode": mode},
                create_time=datetime(2026, 1, 1), update_time=datetime(2026, 1, 2)))
            connection.execute(insert(ConversationMessage).values(message_id=conversation_id, conversation_id=conversation_id,
                message_content="original history", minio_files='["attachment.pdf"]'))
        connection.execute(text(f"CREATE FUNCTION {schema}.touch_creator_history() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.update_time = now(); RETURN NEW; END $$"))
        connection.execute(text(f"CREATE TRIGGER touch_creator_history BEFORE UPDATE ON {schema}.conversation_record_t FOR EACH ROW EXECUTE FUNCTION {schema}.touch_creator_history()"))
    run_creator_sql(engine)
    before = database_state(engine)
    def migrate():
        with engine.begin() as connection:
            with connection.connection.driver_connection.cursor() as cursor:
                cursor.execute(sql)
    with pytest.raises(RuntimeError, match="rollback probe"):
        with engine.begin() as connection:
            with connection.connection.driver_connection.cursor() as cursor:
                cursor.execute(sql)
            raise RuntimeError("rollback probe")
    assert database_state(engine) == before
    assert "__once_creator_conversation_targets_v1" not in migration_marker(engine)
    migrate()
    after = database_state(engine)
    actors = {row["system_key"]: row["agent_id"] for row in records(engine, AgentInfo) if row["agent_origin"] == "SYSTEM"}
    assert set(actors) == {"nl2agent_main", "nl2skill_main"}
    migrated = {row["conversation_id"]: row for row in after[ConversationRecord.__tablename__]}
    for original in before[ConversationRecord.__tablename__]:
        row = migrated[original["conversation_id"]]
        expected = dict(original)
        mode = original["workbench_config"]["mode"]
        if mode in ("agent_create", "skill_create"):
            expected["agent_id"] = actors["nl2agent_main" if mode == "agent_create" else "nl2skill_main"]
            expected["target"] = {"type": "agent", "id": 201} if mode == "agent_create" else None
        assert row == expected
    assert before[ConversationMessage.__tablename__] == after[ConversationMessage.__tablename__]
    assert after[AgentInfo.__tablename__] == before[AgentInfo.__tablename__]
    for actor in actors.values():
        assert_creator_identity(engine, actor)
    migrate()
    assert database_state(engine) == after
    restored = history_db.get_conversation_history(1, "user-a")
    assert restored["agent_id"] == actors["nl2agent_main"]
    assert restored["target"] == {"type": "agent", "id": 201}
    assert history_db.get_conversation_history(1, "user-b") is None
    target = {"type": "skill", "id": 202}
    assert not history_db.bind_creation_conversation_target(2, actors["nl2skill_main"], None, target, "user-b")
    assert history_db.bind_creation_conversation_target(2, actors["nl2skill_main"], None, target, "user-a")
    assert not history_db.bind_creation_conversation_target(2, actors["nl2skill_main"], None, target, "user-a")
    assert history_db.get_conversation_history(2, "user-a")["target"] == target
    with engine.connect() as connection:
        assert connection.execute(text(f"SELECT tgenabled FROM pg_trigger WHERE tgrelid = '{schema}.conversation_record_t'::regclass AND tgname = 'touch_creator_history'")).scalar_one() == "O"



def test_standalone_creator_history_does_not_persist_workbench_config(release_database, monkeypatch):
    from management.services.conversation import creation_history
    from management.db.conversation import pins
    from management.db.identity import conversation_agent_history_db as groups

    engine = release_database
    monkeypatch.setattr(history_db, "_enforce_user_conversation_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(history_db, "_enforce_conversation_turn_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(pins, "get_db_session", history_db.get_db_session)
    monkeypatch.setattr(groups, "get_db_session", history_db.get_db_session)
    identities = initialize_installation(engine)
    created = []
    for kind in ("agent", "skill"):
        actor = identities[f"nl2{kind}_main"]
        target = {"type": kind, "id": 201}
        for configured in (False, True):
            config = {"schema_version": 3, "mode": f"{kind}_create", "agent_mounts": [], "skill_mounts": []} if configured else None
            conversation_id, index = creation_history.prepare_creation_history(
                conversation_id=None, mode=f"{kind}_create", query="create", minio_files=None,
                workbench_config=config, agent_id=actor, target=target, user_id="user-a", tenant_id="tenant-a",
            )
            assert index == 1
            before = next(row for row in records(engine, ConversationRecord) if row["conversation_id"] == conversation_id)
            if not configured:
                assert before["workbench_config"] is None and before["workbench_config_version"] == 0
            else:
                assert before["workbench_config"]["mode"] == f"{kind}_create"
            history = history_db.get_conversation_history(conversation_id, "user-a")
            assert history["agent_system_key"] == f"nl2{kind}_main"
            assert history["target"] == target and history["agent_id"] == actor
            assert history_db.get_conversation_history(conversation_id, "user-b") is None
            assert creation_history.prepare_creation_history(
                conversation_id=conversation_id, mode=f"{kind}_create", query="continue", minio_files=None,
                workbench_config=None, agent_id=actor, target=target, user_id="user-a", tenant_id="tenant-a",
            ) == (conversation_id, 2)
            after = next(row for row in records(engine, ConversationRecord) if row["conversation_id"] == conversation_id)
            assert after["workbench_config"] == before["workbench_config"]
            assert after["workbench_config_version"] == before["workbench_config_version"]
            messages = [row for row in records(engine, ConversationMessage) if row["conversation_id"] == conversation_id]
            assert len(messages) == 2
            created.append(conversation_id)
    page = history_db.get_conversation_list_page("user-a", 0, 0, conversation_type="workbench")
    assert {row["conversation_id"] for row in page["items"]} == set(created)
    assert not history_db.get_conversation_list_page("user-b", 0, 0, conversation_type="workbench")["items"]
    assert not history_db.get_conversation_list_page("user-a", 0, 0, conversation_type="agent_chat")["items"]
    assert not groups.get_agent_conversation_group_page("user-a", "tenant-a")["items"]
    # A user-owned lookalike key and a NULL executor remain ordinary Agent-chat history.
    with engine.begin() as connection:
        connection.execute(insert(AgentInfo).values(agent_id=999, version_no=0, tenant_id="tenant-a", name="lookalike", agent_origin="USER", system_key="nl2skill_main"))
        for agent_id in (999, None):
            connection.execute(insert(ConversationRecord).values(agent_id=agent_id, created_by="user-a", conversation_title="ordinary"))
    ordinary = history_db.get_conversation_list_page("user-a", 0, 0, conversation_type="agent_chat")["items"]
    assert {row["agent_id"] for row in ordinary} == {999, None}
    for row in ordinary:
        assert history_db.get_conversation_history(row["conversation_id"], "user-a")["agent_system_key"] is None
    assert {row["agent_id"] for row in groups.get_agent_conversation_group_page("user-a", "tenant-a")["items"]} == {999, None}
    pins_after = pins.set_workbench_pin(created[0], True, "user-a", "tenant-a")
    assert pins_after[0]["conversation_type"] == "workbench"
    assert not pins.list_workbench_pins("user-b", "tenant-b")



@pytest.mark.parametrize("existing_key", ["nl2agent_main", "nl2skill_main"])
def test_creator_sql_reuses_existing_public_ids(release_database, existing_key):
    from sqlalchemy.exc import IntegrityError

    engine = release_database
    with engine.begin() as connection:
        connection.execute(insert(AgentInfo).values(agent_id=900, tenant_id=ASSET_OWNER_TENANT_ID,
            version_no=0, agent_origin="SYSTEM", system_key=existing_key, name=existing_key, enabled=True))
        connection.execute(insert(AgentInfo).values(agent_id=901, tenant_id="tenant-a", version_no=0,
            agent_origin="USER", system_key=existing_key, name=existing_key, prompt="user-owned"))
    before = records(engine, AgentInfo)
    run_creator_sql(engine)
    rows = records(engine, AgentInfo)
    for row in before:
        assert row in rows
    creators = [row for row in rows if row["agent_origin"] == "SYSTEM"]
    assert len(creators) == 2
    assert next(row["agent_id"] for row in creators if row["system_key"] == existing_key) == 900
    for row in creators:
        assert_creator_identity(engine, row["agent_id"])
    run_creator_sql(engine)
    assert records(engine, AgentInfo) == rows
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(insert(AgentInfo).values(agent_id=902, tenant_id=ASSET_OWNER_TENANT_ID,
                version_no=0, agent_origin="SYSTEM", system_key=existing_key, name=existing_key))
    assert records(engine, AgentInfo) == rows


def test_creator_sql_concurrent_replay_and_rollback(release_database):
    engine = release_database
    schema = engine.get_execution_options()["schema_translate_map"]["nexent"]
    with engine.begin() as connection:
        connection.execute(text(f"CREATE FUNCTION {schema}.reject_creator_seed() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.system_key = 'nl2skill_main' THEN RAISE EXCEPTION 'creator seed failure'; END IF; RETURN NEW; END $$"))
        connection.execute(text(f"CREATE TRIGGER reject_creator_seed BEFORE INSERT ON {schema}.ag_tenant_agent_t FOR EACH ROW EXECUTE FUNCTION {schema}.reject_creator_seed()"))
    before = database_state(engine)
    with pytest.raises(Exception, match="creator seed failure"):
        run_creator_sql(engine)
    assert database_state(engine) == before
    assert not migration_marker(engine)
    with engine.begin() as connection:
        connection.execute(text(f"DROP TRIGGER reject_creator_seed ON {schema}.ag_tenant_agent_t"))
    gate = Barrier(16)
    def provision(_):
        gate.wait(timeout=10)
        run_creator_sql(engine)
    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(provision, range(16)))
    rows = records(engine, AgentInfo)
    assert len(rows) == 2
    assert {row["system_key"] for row in rows} == {"nl2agent_main", "nl2skill_main"}
    assert migration_marker(engine) == ["__once_shared_creator_identities_v1"]
    for row in rows:
        assert_creator_identity(engine, row["agent_id"])
    run_creator_sql(engine)
    assert records(engine, AgentInfo) == rows


@pytest.mark.parametrize("missing_key", ["nl2agent_main", "nl2skill_main"])
def test_history_sql_requires_seeded_creator_ids(release_database, missing_key):
    engine = release_database
    run_creator_sql(engine)
    with engine.begin() as connection:
        connection.execute(delete(AgentInfo).where(AgentInfo.system_key == missing_key))
        connection.execute(insert(ConversationRecord).values(conversation_id=9, agent_id=201,
            created_by="user-a", workbench_config={"mode": "agent_create"}))
    before = database_state(engine)
    with pytest.raises(Exception, match="apply v2.8.1_002_shared_creator_identities.sql first"):
        run_history_sql(engine)
    assert database_state(engine) == before
    assert migration_marker(engine) == ["__once_shared_creator_identities_v1"]
    schema = engine.get_execution_options()["schema_translate_map"]["nexent"]
    with engine.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM pg_constraint WHERE conrelid = '{schema}.conversation_record_t'::regclass AND conname = 'conversation_target_shape'")).scalar_one() == 0


@pytest.mark.parametrize("kind", ["agent", "skill"])
def test_creator_history_page_filters_executor_target_and_owner(release_database, kind):
    from management.services.conversation.creator_histories import list_creator_histories

    engine = release_database
    identities = initialize_installation(engine)
    executor = identities[f"nl2{kind}_main"]
    other_kind = "skill" if kind == "agent" else "agent"
    with engine.begin() as connection:
        for agent_id, tenant in ((201, "tenant-a"), (202, "tenant-a"), (301, "tenant-b")):
            if kind == "agent":
                connection.execute(insert(AgentInfo).values(agent_id=agent_id, tenant_id=tenant, version_no=0, name="edited", agent_origin="USER"))
            else:
                connection.execute(insert(SkillInfo).values(skill_id=agent_id, tenant_id=tenant, skill_name=f"edited-{agent_id}", source="custom"))
        for cid, owner, actor, target, deleted, workbench in (
            (101, "user-a", executor, {"type": kind, "id": 201}, "N", None),
            (102, "user-a", executor, {"type": kind, "id": 201}, "N", {"mode": f"{kind}_create"}),
            (103, "user-b", executor, {"type": kind, "id": 201}, "N", None),
            (104, "user-a", executor, {"type": kind, "id": 202}, "N", None),
            (105, "user-a", identities[f"nl2{other_kind}_main"], {"type": kind, "id": 201}, "N", None),
            (106, "user-a", 201, {"type": kind, "id": 201}, "N", None),
            (107, "user-a", executor, {"type": kind, "id": 201}, "Y", None),
            (108, "user-a", executor, {"type": other_kind, "id": 201}, "N", None),
        ):
            connection.execute(insert(ConversationRecord).values(conversation_id=cid, agent_id=actor, target=target,
                created_by=owner, delete_flag=deleted, workbench_config=workbench, conversation_title=str(cid), create_time=datetime(2026, 1, 1)))
    before = database_state(engine)
    def page(user="user-a", target=201, offset=0):
        return list_creator_histories(kind=kind, target_id=target, user_id=user, tenant_id="tenant-a", offset=offset, limit=1)
    first, second = page(), page(offset=1)
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["conversation_id"] == 102
    assert second["items"][0]["conversation_id"] == 101
    assert page("user-b")["total"] == 1
    assert page(target=202)["items"][0]["conversation_id"] == 104
    with pytest.raises(PermissionError):
        page(target=301)
    with pytest.raises(PermissionError):
        page(target=999)
    assert database_state(engine) == before
