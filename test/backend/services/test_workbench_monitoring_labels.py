# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Localize the built-in runtime identity without rewriting published snapshots."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from consts.model import WorkbenchSessionConfig
from services import workbench_service


@pytest.mark.parametrize("display_name", [None, "", "Nexent Workbench", "智能工作台"])
def test_workbench_runtime_has_chinese_label_and_preserves_published_snapshot(mocker, display_name):
    snapshot = {"agent_id": 99, "name": "workbench_main", "display_name": display_name}
    before = deepcopy(snapshot)
    mocker.patch.object(
        workbench_service.system_agent_provider, "get_workbench_main_ref",
        return_value=SimpleNamespace(agent_id=99, version_no=4),
    )
    mocker.patch.object(workbench_service, "search_agent_info_by_agent_id", return_value=snapshot)
    mocker.patch.object(workbench_service.skill_db, "search_skills_for_agent", return_value=[])
    config = WorkbenchSessionConfig.model_validate({"mode": "generic_chat"})

    _, plan = workbench_service.resolve_workbench_config(config, tenant_id="tenant")

    assert plan.root.identity.display_name == "智能工作台"
    assert plan.root.identity.invocation_name == "workbench_main"
    assert plan.root.identity.agent_id == 99
    assert plan.root.identity.version_no == 4
    assert plan.root.published_snapshot["display_name"] == before["display_name"]
    assert snapshot["display_name"] == before["display_name"]
