# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep root, mounted Agent and request-scoped retrieval policies distinct."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test.backend.agents import test_create_agent_info as legacy

service = legacy.create_agent_info_module


def record(top_k, method, kds):
    return {
        "class_name": "AidpSearchTool", "name": "aidp_search", "source": "langchain",
        "params": [{"name": name, "default": value} for name, value in {
            "top_k": top_k, "search_method": method, "kds_list": kds,
            "vector_candidates": top_k, "full_text_candidates": top_k,
        }.items()],
    }


@pytest.fixture
def runtime_records(mocker):
    records = {
        99: [record(10, "hybrid_search", [])],
        7: [record(20, "full_text_search", ["product"])],
        4: [record(15, "hybrid_search", ["product"])],
        3: [record(5, "vector_search", ["faq"])],
    }
    mocker.patch.object(service, "discover_langchain_tools", new=AsyncMock(return_value=[]))
    mocker.patch.object(service, "_resolve_runtime_tool_records", side_effect=lambda **kw: records[kw["agent_id"]])
    mocker.patch.object(service, "search_agent_info_by_agent_id", side_effect=lambda **kw: {
        "name": {99: "workbench_main", 7: "mounted", 4: "parent", 3: "child"}[kw["agent_id"]],
    })
    mocker.patch.object(service, "ToolConfig", side_effect=lambda **kw: SimpleNamespace(metadata=None, **kw))
    mocker.patch.dict("sys.modules", {
        "ext_components.aidp.services.aidp_access_service": SimpleNamespace(resolve_current_aidp_access=lambda: None),
    })
    mocker.patch.object(service, "run_blocking", new=AsyncMock(return_value=SimpleNamespace(
        accessible_id_set={"product", "faq", "api"}, name_to_id={}, tenant_name_to_id={},
    )))
    return records


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", [False, True])
async def test_workbench_root_scope_does_not_replace_mounted_agent_policy(runtime_records, selected):
    before = deepcopy(runtime_records)
    overrides = None
    if selected:
        overrides = {"agents": {"workbench_main": {"tools": {"aidp_search": {"kds_list": ["api"]}}}}}
    root = await service.create_tool_config_list(
        99, "tenant", "user", version_no=1, tool_params=overrides,
        runtime_knowledge_tools=deepcopy(runtime_records[99]) if selected else None,
    )
    mounted = await service.create_tool_config_list(7, "tenant", "user", version_no=2, tool_params=overrides)
    assert root[0].params["top_k"] == 10
    assert root[0].params["kds_list"] == (["api"] if selected else [])
    assert root[0].metadata["allowed_kds_set"] == (["api"] if selected else [])
    assert mounted[0].params["top_k"] == 20
    assert mounted[0].params["search_method"] == "full_text_search"
    assert mounted[0].params["kds_list"] == ["product"]
    assert mounted[0].metadata["allowed_kds_set"] == ["product"]
    assert runtime_records == before


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_key", ["aidp_search", "AidpSearchTool"])
async def test_parent_child_sparse_caps_stay_distinct_from_total(runtime_records, tool_key):
    before = deepcopy(runtime_records)
    overrides = {"agents": {
        "parent": {"tools": {tool_key: {"hybrid_top_k": 12}}},
        "child": {"tools": {tool_key: {"hybrid_top_k": 4}}},
    }}
    for agent_id, total, cap in [(4, 15, 12), (3, 5, 4)]:
        tools = await service.create_tool_config_list(agent_id, "tenant", "user", version_no=1, tool_params=overrides)
        assert tools[0].params["top_k"] == total
        assert tools[0].params["hybrid_top_k"] == cap
        baseline = await service.create_tool_config_list(agent_id, "tenant", "user", version_no=1)
        assert baseline[0].params["top_k"] == total
        assert baseline[0].params.get("hybrid_top_k", 0) == 0
    assert runtime_records == before
