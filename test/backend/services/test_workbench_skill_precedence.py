# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit regression for complete-resource Skill precedence and snapshot safety."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.exceptions import WorkbenchError
from management.services.agent import workbench
from management.services.agent.preparation.inputs import _materialize_runtime_skill_snapshot


DEFAULT_NAMES = ("pdf", "docx", "xlsx", "pptx", "canvas-design", "analyze-image")


@pytest.fixture
def catalog(monkeypatch):
    rows = {
        1: {"skill_id": 1, "name": "analyze-image", "tool_ids": [10],
            "config_schemas": [{"name": "region", "type": "string"}], "config_values": {"region": "default"}},
        2: {"skill_id": 2, "name": "analyze-image", "tool_ids": [20],
            "config_schemas": [{"name": "region", "type": "string"}], "config_values": {"region": "tenant"}},
    }
    capture = Mock(side_effect=lambda name, owner: (("SKILL.md", owner.encode()),))
    definitions = {
        value: {"tool_id": value, "name": "analyze_image", "class_name": "AnalyzeImageTool",
                "author": ASSET_OWNER_TENANT_ID if value == 10 else "tenant", "is_available": True,
                "params": [{"name": "region", "default": "tool-default"}]}
        for value in (10, 20)
    }
    tools = Mock(side_effect=lambda ids: [deepcopy(definitions[i]) for i in ids])
    monkeypatch.setattr(workbench.skill_db, "get_skill_by_id", lambda skill_id, owner: deepcopy(rows.get(skill_id)))
    monkeypatch.setattr(workbench, "_capture_skill_file_snapshot", capture)
    monkeypatch.setattr(workbench, "query_tools_by_ids", tools)
    monkeypatch.setattr(workbench, "_get_user_role", lambda user: "USER")
    monkeypatch.setattr(workbench, "query_group_ids_by_user", lambda user: [])
    monkeypatch.setattr(workbench, "can_view_skill", lambda **kwargs: True)
    return rows, capture, definitions, tools


def resolve(mounts=(), defaults=({"skill_id": 1},)):
    return workbench._resolve_skill_mounts(
        mounts, "tenant", defaults, user_id="viewer", published_tenant_id=ASSET_OWNER_TENANT_ID,
    )


@pytest.mark.parametrize("name", DEFAULT_NAMES)
def test_explicit_skill_replaces_same_name_default_as_one_resource(catalog, name):
    rows, capture, definitions, tools = catalog
    rows[1]["name"] = rows[2]["name"] = name
    rows[1]["config_schemas"].append({"name": "platform_only", "type": "string", "required": True})
    rows[1]["config_values"]["platform_only"] = "must-not-leak"
    definitions[10]["is_available"] = False
    before = deepcopy(rows)

    result = resolve(({"skill_id": 2, "config_values": {"region": "chosen"}},))

    assert [(s.skill_id, s.name, s.tool_ids, s.config_values) for s in result] == [(2, name, (20,), {"region": "chosen"})]
    assert result[0].files == (("SKILL.md", b"tenant"),)
    assert [t["tool_id"] for t in result[0].tool_definitions] == [20]
    capture.assert_called_once_with(name, "tenant")
    tools.assert_called_once_with([20])
    assert rows == before


def test_removing_explicit_mount_restores_published_configuration(catalog):
    result = resolve(defaults=({"skill_id": 1, "config_values": {"region": "published"}},))
    assert [(s.skill_id, s.tool_ids, s.config_values) for s in result] == [(1, (10,), {"region": "published"})]


def test_same_identity_preserves_existing_configuration_precedence(catalog):
    result = resolve(({"skill_id": 1, "config_values": {"region": "runtime"}},),
                     ({"skill_id": 1, "config_values": {"region": "published"}}, {"skill_id": 1}))
    assert len(result) == 1 and result[0].config_values == {"region": "runtime"}


@pytest.mark.parametrize("explicit", [True, False])
def test_same_priority_same_name_is_rejected_before_capture(catalog, explicit):
    _, capture, _, tools = catalog
    with pytest.raises(WorkbenchError, match="RUNTIME_SKILL_NAME_CONFLICT"):
        resolve(({"skill_id": 1}, {"skill_id": 2}) if explicit else (),
                () if explicit else ({"skill_id": 1}, {"skill_id": 2}))
    capture.assert_not_called()
    tools.assert_not_called()


def test_unauthorized_override_cannot_fall_back_to_default(catalog, monkeypatch):
    monkeypatch.setattr(workbench, "can_view_skill", lambda **kwargs: False)
    with pytest.raises(WorkbenchError, match="RUNTIME_SKILL_FORBIDDEN"):
        resolve(({"skill_id": 2},))
    catalog[1].assert_not_called()


def test_unavailable_effective_dependency_is_rejected(catalog):
    catalog[2][20]["is_available"] = False
    with pytest.raises(WorkbenchError, match="RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE"):
        resolve(({"skill_id": 2},))


def test_missing_explicit_resource_cannot_fall_back_to_default(catalog):
    with pytest.raises(WorkbenchError, match="RUNTIME_SKILL_FORBIDDEN"):
        resolve(({"skill_id": 999},))
    catalog[1].assert_not_called()


def test_empty_effective_skill_set_does_not_touch_storage(catalog):
    assert resolve((), ()) == ()
    catalog[1].assert_not_called()
    catalog[3].assert_not_called()


def test_different_skills_cannot_introduce_same_name_tools_with_different_ids(catalog):
    catalog[0][2]["name"] = "other-skill"
    with pytest.raises(WorkbenchError, match="RUNTIME_SKILL_TOOL_CONFLICT"):
        resolve(({"skill_id": 2},))


def test_different_skills_can_share_the_same_tool_identity(catalog):
    catalog[0][2].update(name="other-skill", tool_ids=[10], config_values={"region": "default"})
    result = resolve(({"skill_id": 2},))
    assert [s.skill_id for s in result] == [1, 2]
    catalog[3].assert_called_once_with([10])


def test_snapshot_duplicate_names_fail_before_any_file_write(tmp_path):
    snapshot = [{"name": "same", "files": [("SKILL.md", body)]} for body in (b"default", b"tenant")]
    before = deepcopy(snapshot)
    with pytest.raises(WorkbenchError, match="RUNTIME_SKILL_NAME_CONFLICT"):
        _materialize_runtime_skill_snapshot(snapshot, str(tmp_path), "tenant")
    assert list(tmp_path.iterdir()) == []
    assert snapshot == before
