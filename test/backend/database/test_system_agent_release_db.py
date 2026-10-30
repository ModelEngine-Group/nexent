# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""System release SQL preserves shared ownership, snapshots and publication gates."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert, Update

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from management.db.agent import system as db


def compiled(statement):
    return statement.compile(dialect=postgresql.dialect())


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_release_lock_is_transaction_scoped_and_keyed_by_identity():
    session = MagicMock()
    db.lock_system_agent_release(session, "workbench_main")
    statement, parameters = session.execute.call_args.args
    assert str(statement) == "SELECT pg_advisory_xact_lock(hashtext(:lock_key))"
    assert parameters == {"lock_key": "system-agent-release:workbench_main"}


@pytest.mark.parametrize("row", [None, {"agent_id": 77, "version_no": 3}])
def test_load_only_reads_active_shared_system_identity_at_requested_version(row):
    session = MagicMock()
    session.execute.return_value.mappings.return_value.one_or_none.return_value = row
    result = db.load_system_agent(session, "workbench_main", 3)
    assert result == row
    if row is not None:
        assert result is not row
    query = sql(session.execute.call_args.args[0])
    for predicate in (
        f"tenant_id = '{ASSET_OWNER_TENANT_ID}'", "agent_origin = 'SYSTEM'",
        "system_key = 'workbench_main'", "version_no = 3", "delete_flag = 'N'",
    ):
        assert predicate in query


def test_release_writes_draft_snapshot_metadata_and_copies_each_active_binding():
    session = MagicMock()
    bindings = {
        db.ToolInstance.__table__: {"agent_id": 77, "tool_id": 9, "params": {"limit": 4}},
        db.SkillInstance.__table__: {"agent_id": 77, "skill_id": 8, "config_values": {"mode": "safe"}},
        db.AgentRelation.__table__: {"parent_agent_id": 77, "selected_agent_id": 12},
    }

    def execute(statement):
        result = MagicMock()
        if not isinstance(statement, (Insert, Update)):
            row = bindings[statement.get_final_froms()[0]]
            result.mappings.return_value.all.return_value = [
                {**row, "tenant_id": ASSET_OWNER_TENANT_ID, "version_no": 0, "delete_flag": "N"},
            ]
        return result

    session.execute.side_effect = execute
    result = db.write_system_agent_release(
        session, existing={"agent_id": "77"}, system_key="workbench_main",
        revision="2.8.2", fields={"name": "Workbench", "enabled": True, "model_ids": [999]}, version_no=3,
    )
    statements = [call.args[0] for call in session.execute.call_args_list]
    draft, snapshot, metadata = statements[:3]
    assert isinstance(draft, Update) and isinstance(snapshot, Insert)
    assert compiled(draft).params["current_version_no"] == 3
    assert "version_no = 0" in sql(draft.whereclause)
    assert f"tenant_id = '{ASSET_OWNER_TENANT_ID}'" in sql(draft.whereclause)
    for statement in (draft, snapshot):
        values = compiled(statement).params
        assert values["tenant_id"] == ASSET_OWNER_TENANT_ID
        assert values["model_ids"] == []
        assert values["agent_origin"] == "SYSTEM"
        assert values["system_revision"] == "2.8.2"
        assert values["ingroup_permission"] == "PRIVATE"
    assert compiled(snapshot).params["agent_id"] == 77
    assert compiled(snapshot).params["version_no"] == 3
    assert compiled(metadata).params["status"] == "RELEASED"
    assert compiled(metadata).params["version_name"] == "2.8.2"
    assert len(statements) == 9
    for query, insert in zip(statements[3::2], statements[4::2]):
        assert "version_no = 0" in sql(query)
        assert "delete_flag = 'N'" in sql(query)
        assert f"tenant_id = '{ASSET_OWNER_TENANT_ID}'" in sql(query)
        assert compiled(insert).params["version_no"] == 3
        expected = bindings[query.get_final_froms()[0]]
        for key, value in expected.items():
            assert compiled(insert).params[key] == value
    assert result["agent_id"] == 77 and result["version_no"] == 3
    session.commit.assert_not_called()


@pytest.mark.parametrize("populated", [False, True])
def test_replace_draft_bindings_preserves_snapshots_and_captures_tool_defaults(populated):
    session = MagicMock()
    tools = [{"tool_id": 9, "params": [{"name": "limit", "default": 4}, {"name": "optional"}]},
             {"tool_id": 10, "params": None}] if populated else []
    skills = [{"skill_id": 8}] if populated else []
    db.replace_workbench_draft_bindings(session, 77, tools, skills)
    statements = [call.args[0] for call in session.execute.call_args_list]
    assert len(statements) == (5 if populated else 2)
    for statement in statements[:2]:
        assert "version_no = 0" in sql(statement)
        assert "agent_id = 77" in sql(statement)
    if populated:
        assert compiled(statements[2]).params["params"] == {"limit": 4, "optional": None}
        assert compiled(statements[3]).params["params"] == {}
        assert compiled(statements[4]).params["config_values"] == {}
        for statement in statements[2:]:
            values = compiled(statement).params
            assert values["tenant_id"] == ASSET_OWNER_TENANT_ID
            assert values["agent_id"] == 77 and values["version_no"] == 0
            assert values["enabled"] is True and values["created_by"] == "system"


def test_latest_release_requires_revision_and_orders_retained_versions():
    session = MagicMock()
    row = {"agent_id": 77, "version_no": 4}
    session.execute.return_value.mappings.return_value.one_or_none.return_value = row
    assert db.latest_workbench_release(session, 77, "2.8.2") == row
    query = sql(session.execute.call_args.args[0])
    assert "agent_id = 77" in query and "version_no > 0" in query
    assert "system_revision = '2.8.2'" in query and "delete_flag = 'N'" in query
    assert "ORDER BY" in query and "version_no DESC" in query and "LIMIT 1" in query


def test_create_draft_returns_shared_identity_without_publishing():
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = 77
    assert db.create_workbench_draft(session, {"name": "Workbench", "enabled": True}) == 77
    values = compiled(session.execute.call_args.args[0]).params
    assert values["tenant_id"] == ASSET_OWNER_TENANT_ID
    assert values["agent_origin"] == "SYSTEM" and values["system_key"] == "workbench_main"
    assert values["version_no"] == 0 and values["model_ids"] == []


@pytest.mark.parametrize("maximum,expected", [(None, 1), (0, 1), (4, 5)])
def test_next_version_follows_existing_maximum(maximum, expected):
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = maximum
    assert db.next_workbench_version(session, 77) == expected
    assert "max(" in sql(session.execute.call_args.args[0])
    assert "agent_id = 77" in sql(session.execute.call_args.args[0])


@pytest.mark.parametrize("version,draft,snapshot", [
    (0, {"agent_id": 77}, {"enabled": True}),
    (2, None, {"enabled": True}),
    (2, {"agent_id": 77}, None),
    (2, {"agent_id": 77}, {"enabled": False}),
])
def test_selection_rejects_unavailable_snapshot_before_writes(mocker, version, draft, snapshot):
    session = MagicMock()
    mocker.patch.object(db, "load_system_agent", side_effect=[draft, snapshot])
    with pytest.raises(ValueError, match="unavailable"):
        db.select_workbench_snapshot(session, version)
    session.execute.assert_not_called()


@pytest.mark.parametrize("status", [None, "DRAFT", "RELEASED"])
def test_selection_only_updates_pointer_for_released_snapshot(mocker, status):
    session = MagicMock()
    load = mocker.patch.object(db, "load_system_agent", side_effect=[{"agent_id": 77}, {"enabled": True}])
    session.execute.return_value.scalar_one_or_none.return_value = status
    if status != "RELEASED":
        with pytest.raises(ValueError, match="not released"):
            db.select_workbench_snapshot(session, 2)
        session.execute.assert_called_once()
    else:
        db.select_workbench_snapshot(session, 2)
        statement = session.execute.call_args.args[0]
        assert isinstance(statement, Update)
        assert compiled(statement).params["current_version_no"] == 2
        assert "agent_id = 77" in sql(statement.whereclause)
        assert "version_no = 0" in sql(statement.whereclause)
    assert [call.args[2:] for call in load.call_args_list] == [(), (2,)]
    query = sql(session.execute.call_args_list[0].args[0])
    assert f"tenant_id = '{ASSET_OWNER_TENANT_ID}'" in query
    assert "delete_flag = 'N'" in query and "version_no = 2" in query


@pytest.mark.parametrize("identity,expected", [(None, False), (5, True)])
def test_legacy_detection_excludes_shared_tenant(identity, expected):
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = identity
    assert db.has_legacy_workbench_agents(session) is expected
    query = sql(session.execute.call_args.args[0])
    assert f"tenant_id IS DISTINCT FROM '{ASSET_OWNER_TENANT_ID}'" in query
    assert "system_key = 'workbench_main'" in query and "agent_origin = 'SYSTEM'" in query
