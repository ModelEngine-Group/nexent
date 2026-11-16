# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Skill visibility and configuration contract regression tests."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from contracts.errors.exceptions import ForbiddenError, SkillException
from management.services.skill import files, local_config, permission
from management.services.skill import service as module
from management.services.skill.yaml_cache import SkillYamlCache


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "CONTAINER_SKILLS_PATH", str(tmp_path))
    monkeypatch.setattr(local_config, "CONTAINER_SKILLS_PATH", str(tmp_path))
    monkeypatch.setattr(module, "skill_yaml_cache", SkillYamlCache())
    value = module.SkillService(skill_manager=Mock(), tenant_id="a")
    monkeypatch.setattr(value, "_resolve_local_skills_dir_for_overlay", lambda: str(tmp_path))
    return value


def skill(number, **overrides):
    row = {"skill_id": number, "name": f"skill-{number}", "source": "custom", "created_by": "other",
           "group_ids": [], "ingroup_permission": "PRIVATE", "content": "full skill content",
           "config_values": {"db": number}, "config_schemas": [{"name": "db"}], "tags": ["tag"]}
    row.update(overrides)
    return row


@pytest.mark.parametrize("role", ["USER", "DEV", "ADMIN", "SUPER_ADMIN", ["USER", "ADMIN"]])
@pytest.mark.parametrize("groups", [[], [10], [20], [10, 20]])
@pytest.mark.parametrize("include_content", [False, True])
def test_visible_result_matches_previous_enrich_then_filter_policy(service, mocker, role, groups, include_content):
    rows = [skill(9, source="official"), skill(8, created_by="user"), skill(7, group_ids=[10]),
            skill(6, group_ids=[10], ingroup_permission="READ_ONLY"),
            skill(5, group_ids="10,20", ingroup_permission="EDIT"),
            skill(4, group_ids=[20], ingroup_permission="EDIT"), skill(3), skill(2, created_by=123)]
    expected = []
    for row in rows:
        # The old implementation enriched every row before using this policy.
        enriched = service._enrich_configs_from_yaml(dict(row, tool_ids=[row["skill_id"], 7, 7]))
        if permission.can_view_skill(skill=enriched, user_id="user", user_role=role, user_group_ids=set(groups)):
            enriched["permission"] = permission.resolve_skill_permission(
                skill=enriched, user_id="user", user_role=role, user_group_ids=set(groups))
            expected.append(enriched)
    records = deepcopy(rows)
    if not include_content:
        for row in records + expected:
            row.pop("content", None)
    metadata = mocker.patch.object(module.skill_db, "list_skills", return_value=records)
    batch = mocker.patch.object(module.skill_db, "get_tool_ids_by_skill_ids",
                              side_effect=lambda ids: {number: [number, 7, 7] for number in ids})
    mocker.patch.object(module, "_get_user_role", return_value=role)
    mocker.patch.object(module, "query_group_ids_by_user", return_value=groups)
    enrich = mocker.patch.object(service, "_enrich_configs_from_yaml", wraps=service._enrich_configs_from_yaml)
    assert service.list_visible_skills(user_id="user", include_content=include_content) == expected
    metadata.assert_called_once_with("a", include_tool_ids=False, include_content=include_content)
    batch.assert_called_once_with([row["skill_id"] for row in expected])
    assert enrich.call_count == len(expected)
    assert rows[0]["config_values"] == {"db": 9}


def test_hidden_skills_never_resolve_paths_or_fetch_relations(service, mocker):
    mocker.patch.object(module.skill_db, "list_skills", return_value=[skill(1, name="../hidden")])
    batch = mocker.patch.object(module.skill_db, "get_tool_ids_by_skill_ids", return_value={})
    paths = mocker.patch.object(service, "_resolve_local_skills_dir_for_overlay", side_effect=AssertionError)
    mocker.patch.object(module, "_get_user_role", return_value="USER")
    mocker.patch.object(module, "query_group_ids_by_user", return_value=[])
    assert service.list_visible_skills(user_id="user", tenant_id="explicit") == []
    module.skill_db.list_skills.assert_called_once_with("explicit", include_tool_ids=False, include_content=True)
    batch.assert_called_once_with([])
    paths.assert_not_called()


@pytest.mark.parametrize("stage", ["metadata", "batch", "overlay"])
def test_list_errors_retain_skill_exception_wrapping(service, mocker, stage):
    mocker.patch.object(module, "_get_user_role", return_value="USER")
    mocker.patch.object(module, "query_group_ids_by_user", return_value=[])
    metadata = mocker.patch.object(module.skill_db, "list_skills", return_value=[skill(1, created_by="user")])
    batch = mocker.patch.object(module.skill_db, "get_tool_ids_by_skill_ids", return_value={1: []})
    overlay = mocker.patch.object(service, "_enrich_configs_from_yaml")
    {"metadata": metadata, "batch": batch, "overlay": overlay}[stage].side_effect = RuntimeError("unavailable")
    with pytest.raises(SkillException, match="Failed to list skills: unavailable"):
        service.list_visible_skills(user_id="user")


def test_no_tenant_and_default_inventory_service_contract(service, mocker):
    metadata = mocker.patch.object(module.skill_db, "list_skills", return_value=[skill(1, tool_ids=[8])])
    batch = mocker.patch.object(module.skill_db, "get_tool_ids_by_skill_ids")
    assert service.list_skills(tenant_id="explicit")[0]["tool_ids"] == [8]
    metadata.assert_called_once_with("explicit", include_content=True)
    batch.assert_not_called()
    service.tenant_id = None
    with pytest.raises(SkillException, match="tenant_id is required"):
        service.list_skills()


@pytest.mark.parametrize("visible", [False, True])
@pytest.mark.parametrize("include_content", [False, True])
def test_content_selection_keeps_configuration_and_permission_metadata(service, mocker, visible, include_content):
    row = skill(1, created_by="user")
    if not include_content:
        row.pop("content")
    metadata = mocker.patch.object(module.skill_db, "list_skills", return_value=[dict(row)])
    mocker.patch.object(module.skill_db, "get_tool_ids_by_skill_ids", return_value={1: [7]})
    mocker.patch.object(module, "_get_user_role", return_value="USER")
    mocker.patch.object(module, "query_group_ids_by_user", return_value=[])
    mocker.patch.object(service, "_resolve_local_skills_dir_for_overlay", return_value=None)
    if visible:
        result = service.list_visible_skills(user_id="user", include_content=include_content)
        metadata.assert_called_once_with("a", include_tool_ids=False, include_content=include_content)
        assert result == [dict(row, tool_ids=[7], permission="EDIT")]
    else:
        result = service.list_skills(include_content=include_content)
        metadata.assert_called_once_with("a", include_content=include_content)
        assert result == [row]
    assert ("content" in result[0]) is include_content


@pytest.mark.parametrize("field,filename,parser_name,valid,expected", [
    ("config_values", "config.yaml", "_parse_skill_params_from_config_bytes", "key: local\n", {"key": "local"}),
    ("config_schemas", "schema.yaml", "_parse_skill_schema_from_yaml_bytes",
     '{"key":{"type":"string"}}', [{"name": "key", "type": "string", "required": False,
                                      "description_en": "", "description_zh": "", "depends_on": None}]),
])
def test_overlay_freshness_missing_failure_fallback_and_shared_cache(
        service, tmp_path, mocker, field, filename, parser_name, valid, expected):
    path = tmp_path / "skill-1" / "config" / filename
    path.parent.mkdir(parents=True)
    row = skill(1)
    parser = mocker.patch.object(module, parser_name, wraps=getattr(module, parser_name))
    assert field not in service._enrich_configs_from_yaml(row)
    path.write_text(valid)
    result = service._enrich_configs_from_yaml(row)
    assert result[field] == expected
    # The cache is shared by different service instances.
    other = module.SkillService(skill_manager=Mock(), tenant_id="a")
    other._resolve_local_skills_dir_for_overlay = lambda: str(tmp_path)
    assert other._enrich_configs_from_yaml(row)[field] == expected
    assert parser.call_count == 1
    if isinstance(result[field], dict):
        result[field]["mutated"] = True
    else:
        result[field].append({"mutated": True})
    assert other._enrich_configs_from_yaml(row)[field] == expected
    path.write_text("invalid: [unterminated")
    row[field] = {"latest_db": True}
    assert other._enrich_configs_from_yaml(row)[field] == {"latest_db": True}
    row[field] = {"latest_db": False}
    assert other._enrich_configs_from_yaml(row)[field] == {"latest_db": False}
    assert parser.call_count == 3
    path.write_text(valid)
    assert other._enrich_configs_from_yaml(row)[field] == expected
    path.unlink()
    assert field not in other._enrich_configs_from_yaml(row)
    path.mkdir()
    assert field not in other._enrich_configs_from_yaml(row)


def test_cached_yaml_still_runs_path_validation(service, tmp_path, mocker):
    path = tmp_path / "skill-1" / "config" / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("key: local")
    assert service._enrich_configs_from_yaml(skill(1))["config_values"] == {"key": "local"}
    # Even a warm cache must not bypass the real resolver's security boundary.
    mocker.patch.object(module, "_local_skill_config_yaml_path", side_effect=ForbiddenError("unsafe path"))
    with pytest.raises(ForbiddenError, match="unsafe path"):
        service._enrich_configs_from_yaml(skill(1))


@pytest.mark.parametrize("name", ["../escape", "a/b", "a\\b"])
def test_invalid_names_remain_rejected(service, name):
    with pytest.raises(SkillException):
        service._enrich_configs_from_yaml(skill(1, name=name))


def test_missing_local_root_or_name_preserves_database_values(service, mocker):
    row = skill(1)
    mocker.patch.object(service, "_resolve_local_skills_dir_for_overlay", return_value=None)
    assert service._enrich_configs_from_yaml(row) == row
    service._resolve_local_skills_dir_for_overlay.return_value = "unused"
    assert service._enrich_configs_from_yaml(dict(row, name="")) == dict(row, name="")


def test_local_read_failure_preserves_current_database_value(service, tmp_path, mocker):
    path = tmp_path / "skill-1" / "config" / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("key: local")
    mocker.patch("builtins.open", side_effect=PermissionError("denied"))
    assert service._enrich_configs_from_yaml(skill(1))["config_values"] == {"db": 1}
