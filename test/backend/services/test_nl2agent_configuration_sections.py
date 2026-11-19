# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Configuration visibility, allowlists, tag changes and optimistic persistence."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from contracts.nl2agent_configuration import PATCH_MODELS
from contracts.tag import AuthenticatedCaller
from services import nl2agent_configuration as service


@pytest.fixture
def caller():
    return AuthenticatedCaller("user", "tenant")


@pytest.fixture
def blocking(mocker):
    async def run(_task, function, *args, **kwargs):
        return function(*args)

    mocker.patch.object(service, "run_blocking", new=run)


@pytest.mark.parametrize("system,owner,admin,groups,allowed,code", [
    (True, "user", True, [], [7], "system_agent_read_only"),
    (False, "user", False, [], [7], None),
    (False, "other", True, [], [7], None),
    (False, "other", False, [7], [7], None),
    (False, "other", False, [8], [7], "agent_read_only"),
])
def test_draft_rechecks_system_and_group_edit_rights(mocker, system, owner, admin, groups, allowed, code):
    caller = AuthenticatedCaller("user", "tenant", can_edit_all=admin)
    draft = {"created_by": owner, "group_ids": service.convert_list_to_string(allowed)}
    authorize = mocker.patch.object(service, "require_agent_draft_edit", return_value=draft)
    mocker.patch.object(service, "is_system_agent", return_value=system)
    query = mocker.patch.object(service, "query_group_ids_by_user_in_tenant", return_value=groups)
    if code:
        with pytest.raises(service.ConfigurationError, match=code):
            service._draft(caller, 42)
    else:
        assert service._draft(caller, 42) is draft
    authorize.assert_called_once_with(agent_id=42, tenant_id="tenant", user_id="user")
    if not system and not admin and owner != "user":
        query.assert_called_once_with("user", "tenant")
    else:
        query.assert_not_called()


def test_model_options_include_only_available_llms_and_safe_names(mocker):
    query = mocker.patch.object(service, "get_model_records", return_value=[
        {"model_id": 1, "display_name": "Public", "model_name": "raw", "connect_status": "AVAILABLE"},
        {"model_id": 2, "display_name": "", "model_name": "Fallback", "connect_status": "available"},
        {"model_id": 3, "connect_status": "unavailable"}, {"model_id": 4},
    ])
    assert service._available_models("tenant") == [{"model_id": 1, "name": "Public"},
                                                  {"model_id": 2, "name": "Fallback"}]
    query.assert_called_once_with({"model_type": "llm"}, "tenant")


@pytest.mark.parametrize("admin,expected", [(False, [2, 3]), (True, [2, 3, 4, 5])])
def test_collaborator_options_filter_self_system_and_inaccessible_agents(mocker, admin, expected):
    mocker.patch.object(service, "query_group_ids_by_user_in_tenant", return_value=[7])
    rows = [
        {"agent_id": 1}, {"agent_id": 6, "agent_origin": "SYSTEM"},
        {"agent_id": 2, "created_by": "user"},
        {"agent_id": 3, "created_by": "other", "ingroup_permission": "READ_ONLY", "group_ids": "7"},
        {"agent_id": 4, "created_by": "other", "ingroup_permission": "PRIVATE", "group_ids": "7"},
        {"agent_id": 5, "created_by": "other", "ingroup_permission": "EDIT", "group_ids": "8"},
    ]
    rows = [{"name": str(row["agent_id"]), **row} for row in rows]
    rows[2]["display_name"] = "Owned"
    query = mocker.patch.object(service, "query_all_agent_info_by_tenant_id", return_value=rows)
    result = service._visible_collaborators(AuthenticatedCaller("user", "tenant", can_edit_all=admin), 1)
    assert [row["agent_id"] for row in result] == expected
    assert result[0]["name"] == "Owned" and result[1]["name"] == "3"
    query.assert_called_once_with("tenant")


def test_tag_options_exclude_non_agent_inactive_definitions_and_values(mocker):
    mocker.patch.object(service.TagManagementService, "list_libraries", return_value=[
        {"bucket_id": "skip", "resource_types": ["tool"]},
        {"bucket_id": "use", "resource_types": ["agent"]},
    ])
    definitions = mocker.patch.object(service.TagManagementService, "list_definitions", return_value=[
        {"status": "inactive", "definition_name": "Hidden"},
        {"status": "active", "definition_name": "Empty", "values": None},
        {"status": "active", "definition_name": "Category", "values": [
            {"status": "active", "value_id": 1, "display_value": "Visible"},
            {"status": "inactive", "value_id": 2, "display_value": "Hidden"},
        ]},
    ])
    assert service._tag_options("tenant") == [{"value_id": 1, "name": "Visible", "definition": "Category"}]
    definitions.assert_called_once_with("tenant", "use")


@pytest.mark.asyncio
@pytest.mark.parametrize("section", ["model", "collaborators", "permissions", "tags", "guardrails"])
async def test_read_configuration_returns_section_options(mocker, blocking, caller, section):
    draft = {"model_ids": [2], "group_ids": "7", "ingroup_permission": "EDIT", "is_main_agent": True, "is_a2a": False}
    mocker.patch.object(service, "_draft", return_value=draft)
    mocker.patch.object(service, "get_model_records", return_value=[])
    mocker.patch.object(service, "query_sub_agent_relations", return_value=[
        {"selected_agent_id": 3, "selected_agent_version_no": 2},
    ])
    mocker.patch.object(service, "_visible_collaborators", return_value=[{"agent_id": 3, "name": "Peer"}])
    versions = mocker.patch.object(service, "query_version_list", return_value=[{"version_no": 0}, {"version_no": 2}])
    groups = mocker.patch.object(service, "query_groups_by_tenant", return_value={"groups": [
        {"group_id": 7, "group_name": "Team"},
    ]})
    mocker.patch.object(service, "_tag_options", return_value=[{"value_id": 9}])
    tags = mocker.patch.object(service.TagManagementService, "get_resource_assignments", new=AsyncMock(
        return_value={"assignments": [{"value_id": 9}]},
    ))
    result = await service.read_configuration(caller, 42, section)
    if section == "model":
        assert result == {"model_ids": [2], "options": []}
    elif section == "collaborators":
        assert result == {"related_agents": [{"agent_id": 3, "version_no": 2}],
                          "options": [{"agent_id": 3, "name": "Peer", "versions": [0, 2]}]}
        versions.assert_called_once_with(3, "tenant")
    elif section == "permissions":
        assert result == {"group_ids": [7], "ingroup_permission": "EDIT", "is_main_agent": True, "is_a2a": False,
                          "groups": [{"group_id": 7, "name": "Team"}],
                          "permission_options": ["PRIVATE", "READ_ONLY", "EDIT"]}
        groups.assert_called_once_with("tenant", page=None)
    elif section == "tags":
        assert result == {"options": [{"value_id": 9}], "assignments": [{"value_id": 9}]}
        tags.assert_awaited_once_with(caller, "agent", "42")
    else:
        assert result["enabled"] is False and result["rules"] == []
    if section != "tags":
        tags.assert_not_awaited()


@pytest.mark.parametrize("section,patch,code", [
    ("model", {"model_ids": [1, 1]}, "invalid_model_selection"),
    ("model", {"model_ids": [99]}, "invalid_model_selection"),
    ("permissions", {"group_ids": [7, 7]}, "invalid_permission_groups"),
    ("permissions", {"group_ids": [99]}, "invalid_permission_groups"),
])
def test_invalid_selection_is_rejected_without_write(mocker, caller, section, patch, code):
    mocker.patch.object(service, "_available_models", return_value=[{"model_id": 1}])
    mocker.patch.object(service, "_groups", return_value=[{"group_id": 7}])
    persist = mocker.patch.object(service, "update_agent_draft_fields")
    with pytest.raises(service.ConfigurationError, match=code):
        service._apply(caller, 42, section, patch, {})
    persist.assert_not_called()


@pytest.mark.parametrize("section,patch,expected", [
    ("model", {"model_ids": [1]}, {"model_ids": [1]}),
    ("permissions", {"group_ids": [7], "ingroup_permission": "EDIT"}, {"group_ids": "7", "ingroup_permission": "EDIT"}),
    ("permissions", {"group_ids": [7], "ingroup_permission": "PRIVATE"}, {"group_ids": "", "ingroup_permission": "PRIVATE"}),
])
def test_apply_writes_validated_values_with_expected_snapshot(mocker, caller, section, patch, expected):
    mocker.patch.object(service, "_available_models", return_value=[{"model_id": 1}])
    mocker.patch.object(service, "_groups", return_value=[{"group_id": 7}])
    persist = mocker.patch.object(service, "update_agent_draft_fields", return_value=1)
    draft = {"model_ids": [2], "group_ids": "8", "ingroup_permission": "READ_ONLY"}
    assert set(service._apply(caller, 42, section, patch, draft)) == set(expected)
    persist.assert_called_once_with(42, "tenant", {**expected, "updated_by": "user"}, expected_fields={
        key: draft.get(key) for key in {*expected, "group_ids", "ingroup_permission"}
    })


def test_optimistic_write_conflict_is_reported(mocker, caller):
    mocker.patch.object(service, "update_agent_draft_fields", return_value=0)
    with pytest.raises(service.ConfigurationError, match="configuration_changed"):
        service._apply(caller, 42, "advanced", {"max_steps": 10}, {})


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"add": []}, {"remove": []}, {"add": [1], "remove": [1]}])
async def test_invalid_tag_delta_never_reaches_assignment_service(mocker, blocking, caller, changes):
    mocker.patch.object(service, "_draft", return_value={})
    replace = mocker.patch.object(service.TagManagementService, "replace_resource_assignments", new=AsyncMock())
    with pytest.raises(service.ConfigurationError, match="invalid_tag_changes"):
        await service.save_configuration(caller, 42, "tags", changes)
    replace.assert_not_awaited()


@pytest.mark.asyncio
async def test_tag_save_uses_scoped_delta_api(mocker, blocking, caller):
    mocker.patch.object(service, "_draft", return_value={})
    replace = mocker.patch.object(service.TagManagementService, "replace_resource_assignments", new=AsyncMock())
    persist = mocker.patch.object(service, "update_agent_draft_fields")
    assert await service.save_configuration(caller, 42, "tags", {"add": [1], "remove": [2]}) == ["tags"]
    replace.assert_awaited_once_with(caller, "agent", "42", [1], remove_value_ids=[2])
    persist.assert_not_called()


@pytest.mark.asyncio
async def test_collaborator_save_dispatches_to_relationship_update(mocker, blocking, caller):
    mocker.patch.object(service, "_draft", return_value={})
    update = mocker.patch.object(service, "_update_collaboration")
    assert await service.save_configuration(caller, 42, "collaborators", {"remove": [2]}) == ["related_agents"]
    update.assert_called_once_with(caller, 42, {"remove": [2]})


@pytest.mark.parametrize("patch", [
    {"upsert_rules": [{"name": "same"}, {"name": "same"}]},
    {"upsert_rules": [{"name": "same"}], "remove_rules": ["same"]},
])
def test_conflicting_guardrail_operations_are_rejected(patch):
    with pytest.raises(service.ConfigurationError, match="invalid_guardrails"):
        service._guardrail_changes({}, patch)


def test_guardrail_rule_merge_preserves_other_rules_and_verification_settings():
    draft = {"verification_config": {"enabled": True, "max_final_rounds": 4, "guardrail_config": {
        "enabled": True, "rules": [{"name": name, "pattern": name} for name in ("keep", "replace", "remove")],
    }}}
    before = deepcopy(draft)
    result = service._guardrail_changes(draft, {
        "upsert_rules": [{"name": "replace", "pattern": "new"}], "remove_rules": ["remove"],
    })["verification_config"]
    assert result["enabled"] is True and result["max_final_rounds"] == 4
    assert result["guardrail_config"] == {"enabled": True, "rules": [
        {"name": "keep", "pattern": "keep"}, {"name": "replace", "pattern": "new"},
    ]}
    assert draft == before


@pytest.mark.parametrize("changes", [None, [], {}, {"max_steps": None}])
def test_patch_requires_explicit_non_null_changes(changes):
    with pytest.raises(ValidationError, match="Supply explicit non-null changes"):
        PATCH_MODELS["advanced"].model_validate(changes)


@pytest.mark.parametrize("field", ["name", "pattern"])
def test_guardrail_rule_rejects_whitespace(field):
    with pytest.raises(ValidationError, match="A rule needs a name and pattern"):
        PATCH_MODELS["guardrails"].model_validate({"upsert_rules": [{"name": "rule", "pattern": "secret", field: "  "}]})
