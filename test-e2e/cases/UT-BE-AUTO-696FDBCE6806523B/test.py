from __future__ import annotations

import asyncio
import sys
import types

import pytest

from services import nl2agent_service

CASE_ID = "UT-BE-AUTO-696FDBCE6806523B"
_NORMAL_TOOL = "some_normal_tool"


def _make_tool(tool_id: int, name: str, source: str) -> dict:
    return {
        "tool_id": tool_id,
        "name": name,
        "origin_name": name,
        "source": source,
        "is_available": True,
        "description": "",
        "description_zh": "",
        "usage": None,
        "params": [],
        "inputs": "{}",
        "labels": [],
    }


class _FakeSkillService:
    def __init__(self, tenant_id: str | None = None) -> None:
        self.tenant_id = tenant_id

    def list_visible_skills(self, *, tenant_id=None, user_id=None) -> list:
        return []


def _install_catalog_dependencies(monkeypatch, tools: list) -> None:
    tcs_name = "services.tool_configuration_service"
    existing_tcs = sys.modules.get(tcs_name)

    async def _fake_list_all_tools(tenant_id=None, labels=None):
        return tools

    if existing_tcs is None:
        fake_tcs = types.ModuleType(tcs_name)
        fake_tcs.list_all_tools = _fake_list_all_tools
        monkeypatch.setitem(sys.modules, tcs_name, fake_tcs)
    else:
        monkeypatch.setattr(existing_tcs, "list_all_tools", _fake_list_all_tools)

    for package in ("management", "management.services", "management.services.skill"):
        monkeypatch.setitem(sys.modules, package, types.ModuleType(package))
    service_name = "management.services.skill.service"
    fake_service = types.ModuleType(service_name)
    fake_service.SkillService = _FakeSkillService
    monkeypatch.setitem(sys.modules, service_name, fake_service)


@pytest.mark.case_id("UT-BE-AUTO-696FDBCE6806523B")
@pytest.mark.stage("D1")
def _check_knowledge_tool_constants_are_defined() -> None:
    assert nl2agent_service._LOCAL_KNOWLEDGE_TOOL_NAMES == frozenset({
        "knowledge_base_search",
    })
    assert nl2agent_service._AIDP_KNOWLEDGE_TOOL_NAME == "aidp_search"


@pytest.mark.stage("D1")
def _check_aidp_deployment_filters_local_knowledge_tools(monkeypatch) -> None:
    monkeypatch.setattr(nl2agent_service, "ENABLE_AIDP_KNOWLEDGE", True)

    assert nl2agent_service._is_nl2agent_recommendable_tool("knowledge_base_search") is False
    assert nl2agent_service._is_nl2agent_recommendable_tool("ind_aidp_search") is True
    assert nl2agent_service._is_nl2agent_recommendable_tool("aidp_search") is True
    assert nl2agent_service._is_nl2agent_recommendable_tool(_NORMAL_TOOL) is True


@pytest.mark.stage("D1")
def _check_local_deployment_filters_aidp_search(monkeypatch) -> None:
    monkeypatch.setattr(nl2agent_service, "ENABLE_AIDP_KNOWLEDGE", False)

    assert nl2agent_service._is_nl2agent_recommendable_tool("aidp_search") is False
    assert nl2agent_service._is_nl2agent_recommendable_tool("knowledge_base_search") is True
    assert nl2agent_service._is_nl2agent_recommendable_tool("ind_aidp_search") is True
    assert nl2agent_service._is_nl2agent_recommendable_tool(_NORMAL_TOOL) is True


@pytest.mark.stage("D1")
def _check_empty_string_input_returns_boolean_without_exception(monkeypatch) -> None:
    monkeypatch.setattr(nl2agent_service, "ENABLE_AIDP_KNOWLEDGE", True)
    assert nl2agent_service._is_nl2agent_recommendable_tool("") is True

    monkeypatch.setattr(nl2agent_service, "ENABLE_AIDP_KNOWLEDGE", False)
    assert nl2agent_service._is_nl2agent_recommendable_tool("") is True


@pytest.mark.stage("D1")
def _check_catalog_excludes_conflicting_knowledge_tools(monkeypatch) -> None:
    tools = [
        _make_tool(1, "knowledge_base_search", "local"),
        _make_tool(2, "ind_aidp_search", "local"),
        _make_tool(3, "aidp_search", "mcp"),
        _make_tool(4, _NORMAL_TOOL, "local"),
    ]
    _install_catalog_dependencies(monkeypatch, tools)

    monkeypatch.setattr(nl2agent_service, "ENABLE_AIDP_KNOWLEDGE", True)
    aidp_catalog = asyncio.run(
        nl2agent_service._load_installed_resource_catalog(tenant_id="t", user_id="u")
    )
    aidp_names = {item["name"] for item in aidp_catalog}
    assert aidp_names == {"aidp_search", "ind_aidp_search", _NORMAL_TOOL}

    monkeypatch.setattr(nl2agent_service, "ENABLE_AIDP_KNOWLEDGE", False)
    local_catalog = asyncio.run(
        nl2agent_service._load_installed_resource_catalog(tenant_id="t", user_id="u")
    )
    local_names = {item["name"] for item in local_catalog}
    assert local_names == {"knowledge_base_search", "ind_aidp_search", _NORMAL_TOOL}


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D1")
def test_nl2agent_recommendable_tool_contract(monkeypatch) -> None:
    _check_knowledge_tool_constants_are_defined()
    _check_aidp_deployment_filters_local_knowledge_tools(monkeypatch)
    _check_local_deployment_filters_aidp_search(monkeypatch)
    _check_empty_string_input_returns_boolean_without_exception(monkeypatch)
    _check_catalog_excludes_conflicting_knowledge_tools(monkeypatch)
