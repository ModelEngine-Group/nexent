# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tenant capability resolution stays outside shared publication."""

from unittest.mock import MagicMock

import pytest

from management.services.agent import system as module


def test_only_official_tenant_skills_are_selected(monkeypatch):
    lookup = MagicMock(
        return_value=[
            {"skill_id": 1, "name": "docx", "source": "community"},
            {"skill_id": 2, "name": "pdf_12", "source": "official"},
            {"skill_id": 3, "name": "pdf", "source": "OFFICIAL"},
            {"skill_id": 4, "name": "unrelated", "source": "official"},
            {"skill_id": 5, "name": "docx_7", "source": "official"},
        ]
    )
    monkeypatch.setattr(module.skill_db, "list_skills", lookup)
    skills = module.SystemAgentProvider().get_workbench_default_skills("tenant-a")
    assert {skill["skill_id"] for skill in skills} == {3, 5}
    lookup.assert_called_once_with("tenant-a")


def test_optional_skill_import_failure_keeps_available_official_skills(monkeypatch):
    provider = module.SystemAgentProvider()
    existing = [{"skill_id": 5, "name": "docx_7", "source": "official"}]
    monkeypatch.setattr(
        provider, "get_workbench_default_skills", lambda tenant: existing
    )
    install = MagicMock(side_effect=RuntimeError("archive unavailable"))
    monkeypatch.setattr(module, "install_skills_from_zip_for_tenant", install)
    assert provider._prepare_official_skills("tenant-a", "user-a") == existing
    assert "docx" not in install.call_args.kwargs["skill_names"]
    assert install.call_args.kwargs["tenant_id"] == "tenant-a"


def test_available_defaults_do_not_reinstall(monkeypatch):
    provider = module.SystemAgentProvider()
    existing = [
        {"name": name} for name in provider.release_manifest.official_skill_names
    ]
    monkeypatch.setattr(
        provider, "get_workbench_default_skills", lambda tenant: existing
    )
    install = MagicMock()
    monkeypatch.setattr(module, "install_skills_from_zip_for_tenant", install)
    assert provider._prepare_official_skills("tenant-a", "user-a") == existing
    install.assert_not_called()


@pytest.mark.parametrize(
    "aidp,expected", [(False, "knowledge_base_search"), (True, "aidp_search")]
)
def test_default_tools_use_requesting_tenant_and_deployment_policy(
    monkeypatch, aidp, expected
):
    query = MagicMock(
        return_value=[
            {"tool_id": 1, "name": expected, "is_available": False},
            {"tool_id": 2, "origin_name": expected, "is_available": True},
            {"tool_id": 3, "name": "unrelated"},
        ]
    )
    monkeypatch.setattr(module, "query_all_tools", query)
    result = module.SystemAgentProvider(aidp_enabled=aidp).get_workbench_default_tools(
        "tenant-b"
    )
    assert [tool["tool_id"] for tool in result] == [2]
    assert result[0]["enabled"] is True
    query.assert_called_once_with("tenant-b")


def test_missing_optional_tool_is_empty(monkeypatch):
    monkeypatch.setattr(module, "query_all_tools", lambda tenant: [])
    assert module.SystemAgentProvider().get_workbench_default_tools("tenant-a") == []


def test_default_knowledge_scope_does_not_copy_catalog_indices_or_mutate_definition(
    monkeypatch,
):
    tool = {
        "name": "knowledge_base_search",
        "params": [{"name": "index_names", "default": ["catalog-index"]}],
    }
    monkeypatch.setattr(module, "query_all_tools", lambda tenant: [tool])
    resolved = module.SystemAgentProvider(
        aidp_enabled=False
    ).get_workbench_default_tools("tenant-a")
    assert resolved[0]["params"][0]["default"] == []
    assert tool["params"][0]["default"] == ["catalog-index"]


def test_runtime_provider_exposes_no_creation_or_migration_entrypoints():
    provider = module.SystemAgentProvider()
    assert not hasattr(provider, "ensure_workbench_main")
    assert not hasattr(provider, "ensure_nl2agent_main")
    assert not hasattr(module, "ensure_workbench_main_agent")
