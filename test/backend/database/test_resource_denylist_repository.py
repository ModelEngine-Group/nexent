# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persistence contracts for resource policy scopes and saved configuration values."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from management.db.configuration import resource_denylist as repository


@pytest.mark.parametrize("tenant", [None, "tenant-a"])
def test_configuration_lookup_only_reads_active_scope(tenant):
    session = MagicMock()
    expected = object()
    session.scalars.return_value.one_or_none.return_value = expected
    result = (repository.global_config(session) if tenant is None
              else repository.tenant_config(session, tenant))
    assert result is expected
    statement = session.scalars.call_args.args[0]
    assert repository.RESOURCE_DENYLIST_KEY in statement.compile().params.values()
    assert "N" in statement.compile().params.values()
    if tenant is not None:
        assert tenant in statement.compile().params.values()
        assert "user_id IS NULL" in str(statement)


def test_policy_reads_global_and_tenant_values_in_one_statement():
    session = MagicMock()
    values = ({"tool_names": ["search"]}, '{"resource_refs":["tool:7"]}')
    session.execute.return_value.one.return_value = values
    assert repository.policy_values(session, "tenant-a") == values
    session.execute.assert_called_once()
    statement = session.execute.call_args.args[0]
    assert "tenant-a" in statement.compile().params.values()
    assert "sys_configuration_t" in str(statement)
    assert "tenant_config_t" in str(statement)


@pytest.mark.parametrize("tenant,scope", [(None, "global"), ("tenant-a", "tenant:tenant-a")])
def test_write_lock_is_scoped_to_policy_owner(tenant, scope):
    session = MagicMock()
    repository.lock_config(session, tenant)
    statement, parameters = session.execute.call_args.args
    assert "pg_advisory_xact_lock" in str(statement)
    assert parameters == {"key": f"{repository.RESOURCE_DENYLIST_KEY}:{scope}"}


@pytest.mark.parametrize("tenant", [None, "tenant-a"])
def test_resource_catalog_separates_types_and_preserves_tenant_identifiers(tenant):
    session = MagicMock()
    session.execute.side_effect = [
        [(1, "service", "First"), (2, "service", "Second"), (3, "", "Hidden")],
        [(4, "service", None), (5, "skill", "Skill")],
    ]
    rows = repository.resource_catalog(session, tenant)
    keys = {row["key"] for row in rows}
    assert keys == ({"mcp:service", "skill:service", "skill:skill"} if tenant is None
                    else {"mcp:1", "mcp:2", "skill:4", "skill:5"})
    assert next(row for row in rows if row["resource_type"] == "skill")["description"] == ""
    for call in session.execute.call_args_list:
        statement = call.args[0]
        assert "N" in statement.compile().params.values()
        if tenant is not None:
            assert tenant in statement.compile().params.values()
    skill_statement = str(session.execute.call_args_list[1].args[0])
    assert ("tenant_id IS NULL" in skill_statement) == (tenant is not None)


@pytest.mark.parametrize("global_names,mcp_ids,expected", [
    (set(), set(), set()), ({"global-service"}, set(), {7, 9}),
    (set(), {12}, {7, 9}), ({"global-service"}, {12}, {7, 9}),
])
def test_service_policy_resolves_only_current_tenant_tools(global_names, mcp_ids, expected):
    session = MagicMock()
    session.scalars.side_effect = [
        SimpleNamespace(all=lambda: ["tenant-service"]),
        SimpleNamespace(all=lambda: [7, 9, 7]),
    ] if mcp_ids else [SimpleNamespace(all=lambda: [7, 9, 7])]
    assert repository.blocked_mcp_tool_ids(session, "tenant-a", global_names, mcp_ids) == expected
    if not global_names and not mcp_ids:
        session.scalars.assert_not_called()
    for call in session.scalars.call_args_list:
        assert "tenant-a" in call.args[0].compile().params.values()
        assert "N" in call.args[0].compile().params.values()


@pytest.mark.parametrize("tenant", [None, "tenant-a"])
@pytest.mark.parametrize("existing", [False, True])
def test_save_creates_or_updates_owned_configuration_without_committing(tenant, existing):
    session = MagicMock()
    row = SimpleNamespace(created_by="creator") if existing else None
    value = {"tool_names": ["search"]} if tenant is None else '{"resource_refs":["tool:7"]}'
    repository.save_config(session, tenant, row, value, "editor")
    if existing:
        session.add.assert_not_called()
        assert row.created_by == "creator"
        assert row.update_time is not None
    else:
        row = session.add.call_args.args[0]
        key = row.configuration_key if tenant is None else row.config_key
        assert key == repository.RESOURCE_DENYLIST_KEY
        assert row.delete_flag == "N" and row.created_by == "editor"
        if tenant is not None:
            assert row.tenant_id == tenant and row.user_id is None
    assert (row.configuration_value if tenant is None else row.config_value) == value
    assert row.updated_by == "editor"
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
