# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Portable Agent configuration keeps context policy without a per-Agent Core."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from contracts.agent import ExportAndImportAgentInfo
from management.services.agent import transfer


def snapshot(core="jiuwen", cm=False):
    return {
        "agent_core": core, "enable_context_manager": cm, "agent_id": 7,
        "tenant_id": "tenant", "name": "portable", "display_name": "Portable",
        "description": "Test", "max_steps": 8, "provide_run_summary": False,
        "enabled": True, "prompt": "Keep my instructions", "model_ids": [],
        "tools": [], "managed_agents": [],
        "context_policy": None,
    }


@pytest.fixture
def boundary(monkeypatch):
    monkeypatch.setattr(transfer, "query_sub_agents_id_list", lambda **_: [])
    monkeypatch.setattr(transfer, "create_tool_config_list", AsyncMock(return_value=[]))
    monkeypatch.setattr(transfer.skill_db, "query_skill_instances_by_agent_id", lambda **_: [])
    monkeypatch.setattr(transfer, "_get_user_group_ids", lambda *_: "")
    monkeypatch.setattr(transfer, "query_all_agent_info_by_tenant_id", lambda *_: [])
    monkeypatch.setattr(transfer, "_resolve_model_ids_with_fallback", lambda **_: [])
    monkeypatch.setattr(transfer, "query_all_tools", lambda **_: [])
    monkeypatch.setattr(transfer, "publish_version_impl", lambda **_: None)
    create = MagicMock(return_value={"agent_id": 42})
    monkeypatch.setattr(transfer, "create_agent", create)
    return create


@pytest.mark.asyncio
@pytest.mark.parametrize("core", ["smolagents", "jiuwen"])
@pytest.mark.parametrize("cm", [True, False])
async def test_export_omits_legacy_core_and_preserves_cm(boundary, monkeypatch, core, cm):
    source = snapshot(core, cm)
    monkeypatch.setattr(transfer, "search_agent_info_by_agent_id", lambda **_: source)
    result = await transfer.export_agent_by_agent_id(7, "tenant", "user")
    assert "agent_core" not in result.model_dump()
    assert result.enable_context_manager is cm
    assert result.prompt == source["prompt"]
    assert source == snapshot(core, cm)


@pytest.mark.asyncio
@pytest.mark.parametrize("core", ["smolagents", "jiuwen"])
@pytest.mark.parametrize("cm", [True, False])
async def test_import_ignores_legacy_core_and_preserves_cm(boundary, core, cm):
    portable = ExportAndImportAgentInfo(**snapshot(core, cm))
    result = await transfer.import_agent_by_agent_id(portable, "tenant", "user")
    assert result == 42
    saved = boundary.call_args.kwargs["agent_info"]
    assert "agent_core" not in saved
    assert saved["enable_context_manager"] is cm
    assert saved["prompt"] == portable.prompt


def test_legacy_portable_defaults():
    fields = snapshot()
    del fields["agent_core"]
    del fields["enable_context_manager"]
    portable = ExportAndImportAgentInfo(**fields)
    assert "agent_core" not in portable.model_dump()
    assert portable.enable_context_manager is True


@pytest.mark.parametrize("core", ["unknown", ""])
def test_obsolete_core_is_ignored(core):
    portable = ExportAndImportAgentInfo(**snapshot(core))
    assert "agent_core" not in portable.model_dump()
    assert "agent_core" not in ExportAndImportAgentInfo.model_fields


@pytest.mark.asyncio
async def test_import_failure_propagates(boundary):
    boundary.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        await transfer.import_agent_by_agent_id(ExportAndImportAgentInfo(**snapshot()), "tenant", "user")
