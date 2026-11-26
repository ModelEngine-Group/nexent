# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from contracts.errors.exceptions import ResourceBindingError
from contracts.resource_denylist import GlobalDenylistUpdate, TenantDenylistUpdate
from management.services.configuration import resource_denylist as denylist


def test_policy_matches_global_name_or_tenant_resource(mocker):
    session = object()
    mocker.patch.object(denylist.client, "get_db_session", return_value=nullcontext(session))
    policy_values = mocker.patch.object(
        denylist.repository, "policy_values",
        side_effect=lambda _, tenant: (
            {"tool_names": ["search"]}, '{"resource_refs":["tool:98"]}' if tenant == "tenant-a" else None,
        ),
    )

    policy = denylist.load_tool_denylist("tenant-a")
    assert policy.blocks("search", 172)
    assert policy.blocks("lookup", 98)
    assert not policy.blocks("search_news", 99)
    assert not policy.blocks("Search", 99)
    assert not denylist.load_tool_denylist("tenant-b").blocks("lookup", 98)
    policy_values.assert_called_with(session, "tenant-b")
    with pytest.raises(ResourceBindingError, match="resource_blocked"):
        denylist.require_tool_allowed("tenant-a", "search", 114)


def test_policy_treats_missing_settings_as_empty_and_propagates_read_failure(mocker):
    session = object()
    mocker.patch.object(denylist.client, "get_db_session", return_value=nullcontext(session))
    read = mocker.patch.object(denylist.repository, "policy_values", return_value=(None, None))
    assert not denylist.load_tool_denylist("tenant-a").blocks("search", 98)
    read.side_effect = RuntimeError("configuration unavailable")
    with pytest.raises(RuntimeError, match="configuration unavailable"):
        denylist.load_tool_denylist("tenant-a")


@pytest.fixture
def editor(mocker):
    session = mocker.Mock()
    mocker.patch.object(denylist, "_editor_session", return_value=nullcontext(session))
    write = mocker.patch.object(denylist.repository, "save_config")
    lock = mocker.patch.object(denylist.repository, "lock_config")
    mocker.patch.object(denylist.repository, "global_config", return_value=SimpleNamespace(
        configuration_value={"tool_names": ["search"]}, update_time=None,
    ))
    mocker.patch.object(denylist.repository, "tenant_config", return_value=SimpleNamespace(
        config_value='{"resource_refs":["tool:98","tool:101"]}', update_time=None,
    ))
    mocker.patch.object(denylist.repository, "tool_catalog", side_effect=lambda _, tenant: [
        {"tool_id": 98, "name": "search", "source": "mcp", "usage": "Enterprise"},
        {"tool_id": 114, "name": "lookup", "source": "local", "usage": None},
    ] if tenant else [{"name": "search"}, {"name": "lookup"}])
    mocker.patch.object(denylist.repository, "resource_catalog", return_value=[])
    return session, write, lock


def test_tenant_editor_preserves_locked_choice_and_updates_existing_record(editor):
    session, write, lock = editor
    snapshot = denylist.read_denylist("tenant-a")
    assert snapshot["items"][0]["global_blocked"]
    assert snapshot["items"][-1]["missing"]
    value = TenantDenylistUpdate(revision=snapshot["revision"], resource_refs=["tool:98", "tool:114", "tool:114"])
    denylist.update_denylist(value, "admin", "tenant-a")

    assert [call.args for call in lock.call_args_list] == [(session, None), (session, "tenant-a")]
    assert write.call_args.args[1] == "tenant-a"
    assert write.call_args.args[2].config_value == '{"resource_refs":["tool:98","tool:101"]}'
    assert write.call_args.args[3:] == ('{"resource_refs":["tool:114","tool:98"]}', "admin")
    session.flush.assert_called_once()


@pytest.mark.parametrize("selection,revision,error", [
    (["tool:98", "tool:172"], None, ValueError),
    (["tool:114"], None, ValueError),
    (["tool:98"], "old-revision", denylist.DenylistConflict),
])
def test_tenant_editor_rejects_bad_updates(editor, selection, revision, error):
    _, write, _ = editor
    revision = revision or denylist.read_denylist("tenant-a")["revision"]
    with pytest.raises(error):
        denylist.update_denylist(TenantDenylistUpdate(revision=revision, resource_refs=selection), "admin", "tenant-a")
    write.assert_not_called()


def test_global_editor_stores_tool_names_as_json_object(editor):
    _, write, _ = editor
    snapshot = denylist.read_denylist()
    payload = GlobalDenylistUpdate(revision=snapshot["revision"], tool_names=["lookup"])
    denylist.update_denylist(payload, "super-admin")
    assert write.call_args.args[1] is None
    assert write.call_args.args[3:] == ({"tool_names": ["lookup"], "resource_refs": []}, "super-admin")


@pytest.mark.parametrize("tenant,hidden", [(None, "download_from_s3"), ("tenant-a", "tool:101")])
def test_editor_preserves_previously_blocked_hidden_tool_and_allows_removal(editor, mocker, tenant, hidden):
    _, write, _ = editor
    if tenant is None:
        mocker.patch.object(denylist.repository, "global_config", return_value=SimpleNamespace(
            configuration_value={"tool_names": [hidden]}, update_time=None,
        ))
    snapshot = denylist.read_denylist(tenant)
    assert next(item for item in snapshot["items"] if item["key"] == hidden)["missing"]
    assert hidden in snapshot["selected"]
    selection = [key for key in snapshot["selected"] if key != hidden]
    payload = (GlobalDenylistUpdate(revision=snapshot["revision"], tool_names=selection) if tenant is None
               else TenantDenylistUpdate(revision=snapshot["revision"], resource_refs=selection))
    denylist.update_denylist(payload, "admin", tenant)
    write.assert_called_once()


@pytest.mark.parametrize("tenant,hidden", [(None, "download_from_s3"), ("tenant-a", "tool:172")])
def test_editor_rejects_new_hidden_tool_selection(editor, tenant, hidden):
    _, write, _ = editor
    snapshot = denylist.read_denylist(tenant)
    selection = [*snapshot["selected"], hidden]
    payload = (GlobalDenylistUpdate(revision=snapshot["revision"], tool_names=selection) if tenant is None
               else TenantDenylistUpdate(revision=snapshot["revision"], resource_refs=selection))
    with pytest.raises(ValueError, match="unavailable"):
        denylist.update_denylist(payload, "admin", tenant)
    write.assert_not_called()


@pytest.mark.parametrize("tenant", [None, "tenant-a"])
def test_editor_exposes_tool_source_and_never_groups_local_usage_as_mcp(editor, mocker, tenant):
    mocker.patch.object(denylist.repository, "tool_catalog", return_value=[
        {"tool_id": 1, "name": "local_lookup", "source": "local", "usage": "Enterprise"},
        {"tool_id": 2, "name": "mcp_lookup", "source": "mcp", "usage": "Enterprise"},
    ])
    parent = "mcp:Enterprise" if tenant is None else "mcp:12"
    mocker.patch.object(denylist.repository, "resource_catalog", return_value=[
        {"key": parent, "name": "Enterprise", "resource_type": "mcp"},
    ])
    state = denylist.read_denylist(tenant)
    local, remote = [next(item for item in state["items"] if item["name"] == name)
                     for name in ("local_lookup", "mcp_lookup")]
    assert local["source"] == "local" and local["service"] is None and local["parent_key"] is None
    assert remote["source"] == "mcp" and remote["service"] == "Enterprise" and remote["parent_key"] == parent


def test_mcp_and_skill_rules_keep_scope_and_type_distinct(mocker):
    session = object()
    mocker.patch.object(denylist.client, "get_db_session", return_value=nullcontext(session))
    mocker.patch.object(denylist.repository, "policy_values", return_value=(
        {"tool_names": [], "resource_refs": ["mcp:search-service", "skill:research"]},
        '{"resource_refs":["mcp:12","skill:34"]}',
    ))
    resolve = mocker.patch.object(denylist.repository, "blocked_mcp_tool_ids", return_value={98, 114})
    policy = denylist.load_tool_denylist("tenant-a")
    assert policy.blocks("lookup", 98)
    assert policy.blocks("lookup", 114)
    assert not policy.blocks("lookup", 172)
    assert policy.blocks_skill("research", 99)
    assert policy.blocks_skill("other", 34)
    assert not policy.blocks_skill("Research", 98)
    resolve.assert_called_once_with(session, "tenant-a", {"search-service"}, {12})
    with pytest.raises(ResourceBindingError, match="resource_blocked"):
        denylist.require_skill_allowed("tenant-a", "research", 99)


def test_resource_editor_locks_platform_mcp_and_preserves_legacy_tools(editor, mocker):
    _, write, _ = editor
    mocker.patch.object(denylist.repository, "global_config", return_value=SimpleNamespace(
        configuration_value={"tool_names": ["search"], "resource_refs": ["mcp:enterprise"]}, update_time=None,
    ))
    mocker.patch.object(denylist.repository, "resource_catalog", return_value=[
        {"key": "mcp:12", "name": "enterprise", "resource_type": "mcp", "description": "Search"},
        {"key": "skill:34", "name": "research", "resource_type": "skill", "description": "Research"},
    ])
    state = denylist.read_denylist("tenant-a")
    assert next(item for item in state["items"] if item["key"] == "mcp:12")["global_blocked"]
    payload = TenantDenylistUpdate(revision=state["revision"], resource_refs=["tool:98", "skill:34"])
    denylist.update_denylist(payload, "admin", "tenant-a")
    assert write.call_args.args[3] == '{"resource_refs":["skill:34","tool:98"]}'
    with pytest.raises(ValueError):
        denylist.update_denylist(TenantDenylistUpdate(
            revision=state["revision"], resource_refs=["tool:98", "mcp:12"],
        ), "admin", "tenant-a")


@pytest.mark.asyncio
async def test_global_skill_exclusion_also_filters_uninstalled_recommendations(mocker):
    from unittest.mock import AsyncMock
    from management.services.agent import nl2agent

    mocker.patch("management.services.skill.transfer.get_official_skills_with_status", return_value=[
        {"name": "research", "status": "installable"}, {"name": "Research", "status": "installable"},
    ])
    mocker.patch.object(nl2agent, "run_blocking", new=AsyncMock(return_value={
        "items": [], "pagination": {"total_pages": 1},
    }))
    mocker.patch("management.services.repository.mcp.service.list_community_mcp_services",
                 new=AsyncMock(return_value={"items": [], "nextCursor": None}))
    mocker.patch.object(denylist, "load_tool_denylist", return_value=denylist.ToolDenylist(
        frozenset(), frozenset(), frozenset({"skill:research"}),
    ))
    catalog = await nl2agent._load_internal_uninstalled_resource_catalog(tenant_id="tenant-a", user_id="admin")
    assert [item["name"] for item in catalog] == ["Research"]
