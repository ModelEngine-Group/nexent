# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read-only shared identity and Workbench version selection."""

from unittest.mock import MagicMock

import pytest

from contracts.agent import SystemAgentRef
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.exceptions import WorkbenchAgentError
from management.services.agent import system as module


def test_workbench_uses_current_pointer_even_from_an_older_release(monkeypatch):
    lookup = MagicMock(side_effect=[
        {"agent_id": 17, "current_version_no": 2, "system_revision": "2.8.0", "enabled": True},
        {"agent_id": 17, "version_no": 2, "system_revision": "2.7.0", "enabled": True},
    ])
    monkeypatch.setattr(module, "search_system_agent", lookup)
    result = module.SystemAgentProvider(app_version="2.8.0").get_workbench_main_ref("tenant-a")
    assert result == SystemAgentRef(ASSET_OWNER_TENANT_ID, "workbench_main", 17, 2)
    assert lookup.call_args_list[1].kwargs == {"version_no": 2}
    assert all(call.args[0] == ASSET_OWNER_TENANT_ID for call in lookup.call_args_list)


@pytest.mark.parametrize("draft,snapshot", [
    (None, None),
    ({"agent_id": 17, "enabled": False}, None),
    ({"agent_id": 17, "current_version_no": None}, None),
    ({"agent_id": 17, "current_version_no": 1}, None),
    ({"agent_id": 17, "current_version_no": 1}, {"agent_id": 18}),
    ({"agent_id": 17, "current_version_no": 1}, {"agent_id": 17, "enabled": False}),
])
def test_missing_or_disabled_publication_never_initializes(monkeypatch, draft, snapshot):
    monkeypatch.setattr(module, "search_system_agent", MagicMock(side_effect=[draft, snapshot]))
    with pytest.raises(WorkbenchAgentError, match="system_agent_not_ready"):
        module.SystemAgentProvider().get_workbench_main_ref("tenant-a")


@pytest.mark.parametrize("key", ["nl2agent_main", "nl2skill_main"])
def test_creator_reads_identity_without_prompt_or_published_version(monkeypatch, key):
    lookup = MagicMock(return_value={"agent_id": 23, "enabled": True, "prompt": None, "current_version_no": None})
    monkeypatch.setattr(module, "search_system_agent", lookup)
    provider = module.SystemAgentProvider()
    assert provider.get_creator_ref("tenant-a", key) == provider.get_creator_ref("tenant-b", key)
    assert provider.get_creator_ref("tenant-a", key).version_no == 0
    assert all(call.args == (ASSET_OWNER_TENANT_ID, key) for call in lookup.call_args_list)


@pytest.mark.parametrize("identity", [None, {"agent_id": 23, "enabled": False}])
def test_creator_missing_identity_errors_without_creation(monkeypatch, identity):
    monkeypatch.setattr(module, "search_system_agent", MagicMock(return_value=identity))
    with pytest.raises(WorkbenchAgentError, match="system_agent_not_ready"):
        module.SystemAgentProvider().get_nl2agent_main_ref("tenant-a")


@pytest.mark.parametrize("tenant", ["", " ", None])
def test_empty_tenant_rejected_before_lookup(monkeypatch, tenant):
    lookup = MagicMock()
    monkeypatch.setattr(module, "search_system_agent", lookup)
    with pytest.raises(ValueError):
        module.SystemAgentProvider().get_nl2agent_main_ref(tenant)
    lookup.assert_not_called()


@pytest.mark.parametrize("origin,prompt,expected", [
    ("SYSTEM", '{"zh":"中文","en":"English"}', "English"),
    ("SYSTEM", "legacy text", "legacy text"),
    ("USER", '{"zh":"中文","en":"English"}', '{"zh":"中文","en":"English"}'),
])
def test_localized_frozen_workbench_prompt(origin, prompt, expected):
    assert module.localized_system_prompt({"agent_origin": origin, "prompt": prompt}, "en") == expected
