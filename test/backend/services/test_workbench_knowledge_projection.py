"""Canonical knowledge scope compatibility endpoint contract tests."""

from copy import deepcopy

import pytest

from consts.exceptions import WorkbenchConfigVersionConflict
from services import conversation_management_service as service


def test_legacy_scope_endpoint_updates_canonical_config_only(mocker):
    """UT-BE-WB-026: legacy PATCH delegates to versioned canonical replacement."""
    canonical = {
        "schema_version": 3,
        "mode": "single_agent_chat",
        "agent_mounts": [{"agent_id": 7, "version_no": 2}],
        "skill_mounts": [],
    }
    before = deepcopy(canonical)
    scope = {"schema_version": 1, "local": {"mode": "disabled", "knowledge_ids": []},
             "aidp": {"mode": "disabled", "kds_ids": []}}
    mocker.patch.object(service, "get_conversation", return_value={
        "workbench_config": canonical, "workbench_config_version": 4,
        "knowledge_scope": {"stale": True},
    })
    replace = mocker.patch.object(service, "update_conversation_workbench_config_service", return_value={
        "workbench_config_version": 5,
    })
    preview = mocker.patch.object(service, "_resolve_knowledge_scope_for_update")
    result = service.update_conversation_knowledge_scope_service(12, scope, "user", "tenant", 4)
    replace.assert_called_once_with(
        conversation_id=12, config={**canonical, "knowledge_scope": scope}, expected_version=4, user_id="user",
    )
    assert result["desired_scope"] == scope
    assert result["workbench_config_version"] == 5
    assert canonical == before
    preview.assert_not_called()


@pytest.mark.parametrize("version", [None, 3])
def test_legacy_scope_endpoint_rejects_unversioned_or_stale_update(mocker, version):
    """UT-BE-WB-026: stale compatibility clients cannot overwrite v3 scope."""
    mocker.patch.object(service, "get_conversation", return_value={
        "workbench_config": {"schema_version": 3}, "workbench_config_version": 4,
    })
    replace = mocker.patch.object(service, "update_conversation_workbench_config_service")
    with pytest.raises(WorkbenchConfigVersionConflict):
        service.update_conversation_knowledge_scope_service(12, None, "user", "tenant", version)
    replace.assert_not_called()
