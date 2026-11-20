# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from contracts.errors.exceptions import ValidationError
from infrastructure.rdb import workbench_skill_records


@pytest.fixture
def catalog(monkeypatch):
    row = {"tool_id": 8, "name": "shared", "source": "local",
           "params": [{"name": "enabled", "default": False}, {"name": "limit", "default": 10}]}
    session = Mock()
    session.execute.return_value.mappings.return_value.all.return_value = [row]
    monkeypatch.setattr(workbench_skill_records, "get_db_session", lambda: nullcontext(session))
    return session


def test_mounted_tool_overlays_only_declared_parameters(catalog):
    skills = [
        {"skill_id": 5, "name": "first", "tool_ids": [8], "config": {"enabled": True, "unrelated": "a"}},
        {"skill_id": 3, "name": "second", "tool_ids": [8], "config": {"enabled": True, "unrelated": "b"}},
    ]
    row, = workbench_skill_records.read_workbench_derived_tools(7, 3, "tenant-a", skills)
    assert row["params"] == [{"name": "enabled", "default": True}, {"name": "limit", "default": 10}]
    assert row["workbench_skill_ids"] == [3, 5]
    assert row["instance_params"] == {}
    catalog.execute.assert_called_once()


def test_conflicting_mounted_tool_overlays_fail_closed(catalog):
    skills = [
        {"skill_id": 5, "name": "first", "tool_ids": [8], "config": {"enabled": True}},
        {"skill_id": 3, "name": "second", "tool_ids": [8], "config": {"enabled": False}},
    ]
    with pytest.raises(ValidationError, match="enabled"):
        workbench_skill_records.read_workbench_derived_tools(7, 3, "tenant-a", skills)


def test_mount_without_tool_dependencies_skips_catalog_read(catalog):
    assert not workbench_skill_records.read_workbench_derived_tools(7, 3, "tenant-a", [])
    catalog.execute.assert_not_called()
