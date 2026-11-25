# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute repository predicates against an isolated relational database."""

from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import Column, JSON, Table, create_engine, event
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import registry, sessionmaker

from management.db.agent import version
from management.db.identity import group, invitation
from infrastructure.rdb import model_records as model
from management.db.tool import repository as tool
from management.services.agent import read


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite://")
    mappings = registry()
    classes = {}
    modules = [group, invitation, model, tool, version]
    for module in modules:
        for name in ["TenantGroupInfo", "TenantGroupUser", "TenantInvitationCode", "TenantInvitationRecord",
                     "ModelRecord", "AgentVersion", "AgentInfo", "ToolInstance", "ToolInfo", "AgentRelation"]:
            original = getattr(module, name, None)
            if original is None:
                continue
            if name not in classes:
                columns = [Column(c.name, JSON() if isinstance(c.type, (ARRAY, JSONB)) else c.type.copy(),
                                  primary_key=c.primary_key, nullable=True) for c in original.__table__.columns]
                table = Table(original.__tablename__, mappings.metadata, *columns)
                classes[name] = type(name, (), {})
                mappings.map_imperatively(classes[name], table)
            monkeypatch.setattr(module, name, classes[name])
    mappings.metadata.create_all(engine)
    factory = sessionmaker(engine)

    @contextmanager
    def get_session(*args, **kwargs):
        with factory() as session:
            yield session

    for module in modules:
        monkeypatch.setattr(module, "get_db_session", get_session)
    statements = []
    event.listen(engine, "before_cursor_execute", lambda conn, cursor, sql, params, context, many: (
        statements.append(sql) if sql.lstrip().upper().startswith("SELECT") else None
    ))

    def insert(table_name, **values):
        values.setdefault("delete_flag", "N")
        with factory.begin() as session:
            session.add(classes[table_name](**values))

    yield insert, statements
    mappings.dispose()
    engine.dispose()


def test_group_batch_counts_preserve_membership_rows_and_soft_delete(database):
    insert, statements = database
    for row_id, group_id, deleted in [(1, 1, "N"), (2, 1, "N"), (3, 1, "Y"), (4, 2, "N")]:
        insert("TenantGroupUser", group_user_id=row_id, group_id=group_id, user_id=str(row_id), delete_flag=deleted)
    expected = {gid: group.count_group_users(gid) for gid in [1, 2, 3]}
    statements.clear()
    result = group.count_users_by_group_ids([1, 2, 3])
    assert {gid: result.get(gid, 0) for gid in expected} == expected == {1: 2, 2: 1, 3: 0}
    assert len(statements) == 1
    statements.clear()
    assert group.count_users_by_group_ids([]) == {}
    assert statements == []


@pytest.mark.parametrize("tenant", [None, "a", "b", "missing"])
@pytest.mark.parametrize("page", [1, 2, 20])
@pytest.mark.parametrize("sort_order", ["asc", "desc"])
def test_invitation_page_totals_and_counts(database, tenant, page, sort_order):
    insert, statements = database
    for number in range(1, 7):
        insert("TenantInvitationCode", invitation_id=number, tenant_id="a" if number < 5 else "b",
               create_time=datetime(2026, 1, 1) + timedelta(days=number), delete_flag="Y" if number == 4 else "N")
    for row_id, invite_id, deleted in [(1, 1, "N"), (2, 1, "N"), (3, 1, "Y"), (4, 5, "N")]:
        insert("TenantInvitationRecord", invitation_record_id=row_id, invitation_id=invite_id, delete_flag=deleted)
    ids = [i for i in range(1, 7) if i != 4 and (tenant is None or ("a" if i < 5 else "b") == tenant)]
    ids.sort(reverse=sort_order == "desc")
    expected_page = ids[(page - 1) * 2:page * 2]
    statements.clear()
    result = invitation.query_invitations_with_pagination(tenant, page, 2, "create_time", sort_order)
    assert result["total"] == len(ids)
    assert result["total_pages"] == (len(ids) + 1) // 2
    assert [item["invitation_id"] for item in result["items"]] == expected_page
    assert [item["used_times"] for item in result["items"]] == [{1: 2, 5: 1}.get(i, 0) for i in expected_page]
    assert len(statements) == (3 if expected_page else 2)
    assert "JOIN" not in statements[0].upper()


@pytest.mark.parametrize("page", [1, 2, 8])
def test_model_sql_page_matches_full_list_defaults_and_total(database, page):
    insert, statements = database
    for i in range(1, 7):
        insert("ModelRecord", model_id=i, tenant_id="a" if i < 5 else "b", model_type="embedding",
               create_time=datetime(2026, 1, i), delete_flag="Y" if i == 3 else "N")
    expected = model.get_model_records({"model_type": "embedding"}, "a")
    statements.clear()
    rows, total = model.get_model_records_page({"model_type": "embedding"}, "a", page, 2)
    assert rows == expected[(page - 1) * 2:page * 2]
    assert total == 3
    assert len(statements) == 2
    assert "LIMIT" in statements[-1].upper()
    assert all(row["expected_chunk_size"] is not None for row in rows)


def test_version_and_snapshot_batches_match_individual_queries(database):
    insert, statements = database
    for agent_id in [1, 2]:
        for no in [1, 2, 3]:
            insert("AgentVersion", id=agent_id * 10 + no, agent_id=agent_id, tenant_id="a",
                   version_no=no, version_name=f"release {no}", delete_flag="Y" if no == 2 else "N")
            insert("AgentInfo", agent_id=agent_id, version_no=no, tenant_id="a", name=f"a{agent_id}")
            insert("ToolInstance", tool_instance_id=agent_id * 10 + no, agent_id=agent_id,
                   tenant_id="a", version_no=no, tool_id=10)
            insert("AgentRelation", relation_id=agent_id * 10 + no, parent_agent_id=agent_id,
                   selected_agent_id=9, tenant_id="a", version_no=no)
    expected_versions = {aid: version.query_version_list(aid, "a") for aid in [1, 2]}
    expected_snapshots = {aid: version.query_agent_snapshot(aid, "a", no) for aid, no in {1: 3, 2: 1}.items()}
    statements.clear()
    assert version.query_version_lists([1, 2], "a") == expected_versions
    assert len(statements) == 1
    statements.clear()
    assert version.query_agent_snapshots({1: 3, 2: 1}, "a") == expected_snapshots
    assert len(statements) == 3
    assert version.query_version_labels({1: 3, 2: 2}, "a") == {1: "release 3"}
    assert version.query_version_lists([1], "b") == {}
    assert version.query_agent_snapshots({}, "a") == {}


def test_tool_and_model_batches_preserve_scope_draft_and_parameter_rules(database):
    insert, statements = database
    insert("ModelRecord", model_id=1, tenant_id="a", model_type="llm", display_name="LLM", api_key="private")
    insert("ModelRecord", model_id=2, tenant_id="a", model_type="llm", delete_flag="Y")
    insert("ModelRecord", model_id=3, tenant_id="b", model_type="llm")
    insert("ToolInfo", tool_id=10, source="mcp", params=[{"name": "selected_model_id", "default": 1}],
           is_available=True)
    rows = [
        (1, "a", 0, True, "N", 2),
        (2, tool.ASSET_OWNER_TENANT_ID, 0, True, "N", None),
        (3, "b", 0, True, "N", 1),
        (4, "a", 1, True, "N", 1),
        (5, "a", 0, False, "N", 1),
        (6, "a", 0, True, "Y", 1),
    ]
    for row_id, tenant_id, no, enabled, deleted, selected in rows:
        insert("ToolInstance", tool_instance_id=row_id, agent_id=8, tenant_id=tenant_id, version_no=no,
               enabled=enabled, delete_flag=deleted, tool_id=10, params={"selected_model_id": selected})
    agent_info = {"agent_id": 8, "model_ids": [1, 2, 3, 999]}
    legacy_tools = tool.search_tools_for_sub_agent(8, "a")
    legacy_projection = read.project_agent_models(agent_info, "a", {})
    legacy_availability = read.check_agent_availability(8, "a", agent_info, {})
    statements.clear()
    context = read.load_agent_list_context([agent_info], "a")
    assert len(statements) == 3
    assert context.tools[8] == [{"tool_id": row["tool_id"], "params": row["params"]} for row in legacy_tools]
    assert len(context.tools[8]) == 2
    statements.clear()
    assert read.project_agent_models(agent_info, "a", context.model_cache(), read_context=context) == legacy_projection
    assert read.check_agent_availability(8, "a", agent_info, context.model_cache(), read_context=context) == legacy_availability
    assert statements == []
    assert all("api_key" not in row for row in context.models.values())


@pytest.mark.parametrize("count", [1, 20, 100])
def test_availability_query_count_is_independent_of_agent_count(database, count):
    insert, statements = database
    insert("ModelRecord", model_id=1, tenant_id="a", model_type="llm")
    insert("ToolInfo", tool_id=10, source="mcp", params=[], is_available=True)
    agents = []
    for aid in range(1, count + 1):
        agents.append({"agent_id": aid, "model_ids": [1]})
        insert("ToolInstance", tool_instance_id=aid, agent_id=aid, tenant_id="a", version_no=0,
               enabled=True, tool_id=10, params={})
    statements.clear()
    context = read.load_agent_list_context(agents, "a")
    cache = context.model_cache()
    for entry in agents:
        assert read.check_agent_availability(entry["agent_id"], "a", entry, cache, read_context=context) == (True, [])
    assert len(statements) == 3


def test_capacity_projection_preserves_values_scope_and_order_without_credentials(database):
    insert, statements = database
    for mid, kind, tenant, deleted in [(1, "llm", "a", "N"), (2, "vlm", "a", "N"),
                                       (3, "embedding", "a", "N"), (4, "llm", "b", "N"), (5, "llm", "a", "Y")]:
        insert("ModelRecord", model_id=mid, model_type=kind, tenant_id=tenant, delete_flag=deleted,
               create_time=datetime(2026, 1, mid), api_key="private")
    all_rows = model.get_model_records(None, "a")
    statements.clear()
    rows = model.get_capacity_model_records({"llm", "vlm"}, "a")
    assert [row["model_id"] for row in rows] == [2, 1]
    assert rows == [{key: row[key] for key in rows[0]} for row in all_rows if row["model_type"] in {"llm", "vlm"}]
    assert len(statements) == 1
    assert all("api_key" not in row and "extra_params" not in row for row in rows)


@pytest.mark.parametrize("entry", [{"temperature": 0}, {"parameter_values": {"temperature": 0}}, {}])
def test_model_batch_preserves_saved_profile_for_agent_overrides(database, entry):
    from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
    from nexent.core.model_service.registry import model_service_references
    from test.backend.services.test_model_outlet_migration_service import build, row

    insert, statements = database
    stored = encode_resolved_model_profile(build(row()), registered_references=model_service_references())
    insert("ModelRecord", **stored, api_key="private", http_headers={"Authorization": "private"},
           model_appid="private", access_token="private")
    agent = {"agent_id": 8, "model_ids": [42], "model_params_override": {"42": entry}}
    expected = read.project_agent_models(agent, "tenant")
    statements.clear()
    batch = model.get_model_records_by_ids([42, 999])
    assert set(batch) == {42}
    assert len(statements) == 1
    selected = statements[0].split("FROM")[0]
    for credential in ("api_key", "http_headers", "model_appid", "access_token"):
        assert credential not in batch[42]
        assert credential not in selected
    statements.clear()
    context = read.AgentListReadContext(batch, {}, {}, "tenant")
    actual = read.project_agent_models(agent, "tenant", batch, read_context=context)
    assert actual == expected
    assert actual.fields["model_params_override"]["42"]["parameter_values"] == (
        {"temperature": 0} if entry else {}
    )
    assert statements == []
    assert agent["model_params_override"] == {"42": entry}
    assert model.get_model_records_by_ids([]) == {}
    assert statements == []


def test_model_batch_does_not_hide_invalid_saved_profiles(database):
    from nexent.core.model_service.profiles.outlet_storage import ProfileStorageError

    insert, _ = database
    insert("ModelRecord", model_id=42, tenant_id="tenant", model_type="llm", profile_schema_version=1)
    agent = {"model_ids": [42], "model_params_override": {"42": {}}}
    with pytest.raises(ProfileStorageError, match="^PROFILE_STORAGE_INVALID$"):
        read.project_agent_models(agent, "tenant", model.get_model_records_by_ids([42]))
