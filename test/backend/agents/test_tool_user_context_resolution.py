"""Tests for authenticated user-context resolution at the backend boundary."""

import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.agents import tool_user_context


def _agent_config(*, tool_sources=(), has_external_a2a=False, managed_agents=()):
    return SimpleNamespace(
        tools=[SimpleNamespace(source=source) for source in tool_sources],
        external_a2a_agents=[object()] if has_external_a2a else [],
        managed_agents=list(managed_agents),
    )


def _install_database_stubs(monkeypatch, *, tenant_record=None, user_record=None, groups=None):
    tenant_config_db = types.ModuleType("database.tenant_config_db")
    tenant_config_db.get_single_config_info = Mock(return_value=tenant_record)
    user_tenant_db = types.ModuleType("database.user_tenant_db")
    user_tenant_db.get_user_tenant_in_tenant = Mock(return_value=user_record)
    group_db = types.ModuleType("database.group_db")
    group_db.query_groups_by_user = Mock(return_value=groups)
    monkeypatch.setitem(sys.modules, "database.tenant_config_db", tenant_config_db)
    monkeypatch.setitem(sys.modules, "database.user_tenant_db", user_tenant_db)
    monkeypatch.setitem(sys.modules, "database.group_db", group_db)
    return tenant_config_db, user_tenant_db, group_db


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (_agent_config(tool_sources=("local",)), False),
        (_agent_config(tool_sources=("mcp",)), True),
        (_agent_config(has_external_a2a=True), True),
        (
            _agent_config(
                managed_agents=[_agent_config(tool_sources=("mcp",))],
            ),
            True,
        ),
    ],
)
def test_agent_tree_needs_user_context(config, expected):
    assert tool_user_context.agent_tree_needs_user_context(config) is expected


def test_build_tool_user_context_is_tenant_scoped(monkeypatch):
    tenant_module, user_module, _ = _install_database_stubs(
        monkeypatch,
        tenant_record={"config_value": "tenant-one"},
        user_record={"user_email": "user@example.com"},
        groups=[
            {"tenant_id": "tenant-1", "group_name": "Readers"},
            {"tenant_id": "tenant-2", "group_name": "Other tenant"},
        ],
    )

    result = tool_user_context.build_tool_user_context("user-1", "tenant-1")

    assert result == {
        "tenant_id": "tenant-1",
        "tenant_name": "tenant-one",
        "user_id": "user-1",
        "user_name": "user@example.com",
        "user_account": "user@example.com",
        "user_groups": ["Readers"],
    }
    tenant_module.get_single_config_info.assert_called_once_with(
        "tenant-1",
        tool_user_context.TENANT_NAME,
    )
    user_module.get_user_tenant_in_tenant.assert_called_once_with("user-1", "tenant-1")


def test_build_tool_user_context_degrades_per_lookup(monkeypatch):
    tenant_module, user_module, group_module = _install_database_stubs(monkeypatch)
    tenant_module.get_single_config_info.side_effect = RuntimeError("tenant lookup failed")
    user_module.get_user_tenant_in_tenant.side_effect = RuntimeError("user lookup failed")
    group_module.query_groups_by_user.side_effect = RuntimeError("group lookup failed")

    assert tool_user_context.build_tool_user_context("user-1", "tenant-1") == {
        "tenant_id": "tenant-1",
        "tenant_name": "",
        "user_id": "user-1",
        "user_name": "",
        "user_account": "",
        "user_groups": [],
    }


def test_resolve_tool_user_context_skips_local_only_tree(mocker):
    builder = mocker.patch.object(tool_user_context, "build_tool_user_context")

    result = tool_user_context.resolve_tool_user_context(
        _agent_config(tool_sources=("local",)),
        "user-1",
        "tenant-1",
    )

    assert result is None
    builder.assert_not_called()


def test_resolve_tool_user_context_builds_for_external_path(mocker):
    expected = {"user_id": "user-1"}
    builder = mocker.patch.object(
        tool_user_context,
        "build_tool_user_context",
        return_value=expected,
    )

    result = tool_user_context.resolve_tool_user_context(
        _agent_config(tool_sources=("mcp",)),
        "user-1",
        "tenant-1",
    )

    assert result == expected
    builder.assert_called_once_with("user-1", "tenant-1")
