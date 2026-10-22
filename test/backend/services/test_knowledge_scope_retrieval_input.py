# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Northbound overrides use Agent defaults without retired conversation policies."""
import pytest

from consts.exceptions import ValidationError
from consts.model import ToolParamsRequest
from management.services.knowledge_base import scope as service


def request_with(params, agent="root", tool="aidp_search"):
    return ToolParamsRequest(agents={agent: {"tools": {tool: params}}})


def inherited_tree():
    return [{"agent_name": "root", "tools": [{
        "name": "aidp_search", "class_name": "AidpSearchTool",
        "params": [{"name": "top_k", "default": 10}, {"name": "hybrid_top_k", "default": 6}],
    }]}]


@pytest.mark.parametrize("tool", ["aidp_search", "AidpSearchTool"])
@pytest.mark.parametrize("params", [
    {"top_k": True}, {"top_k": 0}, {"vector_candidates": 5},
    {"vector_candidates": 10.0}, {"search_method": []}, {"reranking_mode": []},
    {"reranking_enable": False, "graph_reranking_enable": True},
])
def test_raw_northbound_override_is_rejected_before_runtime(mocker, tool, params):
    mocker.patch.object(service, "snapshot_runtime_knowledge_tree", return_value=inherited_tree())
    with pytest.raises(ValidationError):
        service.prepare_tool_retrieval_overrides(
            "tenant", tool_params=request_with(params, tool=tool), agent_id=7, version_no=3,
        )


def test_override_is_prepared_against_instance_values_without_mutating_them(mocker):
    tree = inherited_tree()
    mocker.patch.object(service, "snapshot_runtime_knowledge_tree", return_value=tree)
    params = request_with({"vector_candidates": 10, "search_method": "hybrid_search"})
    service.prepare_tool_retrieval_overrides("tenant", tool_params=params, agent_id=7, version_no=3)
    assert params.agents["root"].tools["aidp_search"] == {
        "vector_candidates": 10, "search_method": "vector_search|full_text_search|graph_search",
    }
    assert tree == inherited_tree()


@pytest.mark.parametrize("params", [None, {}, {"kds_list": ["kb"]}])
def test_no_retrieval_override_does_not_read_or_validate_saved_configuration(mocker, params):
    read = mocker.patch.object(service, "snapshot_runtime_knowledge_tree")
    request = None if params is None else request_with(params)
    service.prepare_tool_retrieval_overrides("tenant", tool_params=request, agent_id=7, version_no=3)
    read.assert_not_called()


def test_debug_override_uses_draft_instead_of_published_configuration(mocker):
    mocker.patch.object(service, "query_current_version_no", return_value=3)

    def snapshot(agent_id, tenant_id, version):
        return [{"agent_name": "root", "tools": [{"name": "aidp_search", "class_name": "AidpSearchTool", "params": [
            {"name": "top_k", "default": 30 if version == 0 else 10},
        ]}]}]

    read = mocker.patch.object(service, "snapshot_runtime_knowledge_tree", side_effect=snapshot)
    raw = {"hybrid_top_k": 12, "vector_candidates": 30, "full_text_candidates": 30}
    params = request_with(dict(raw))
    service.prepare_tool_retrieval_overrides("tenant", tool_params=params, agent_id=7, is_debug=True)
    read.assert_called_once_with(7, "tenant", 0)
    assert params.agents["root"].tools["aidp_search"] == raw
    with pytest.raises(ValidationError, match="hybrid_top_k"):
        service.prepare_tool_retrieval_overrides("tenant", tool_params=request_with(raw), agent_id=7)


@pytest.mark.parametrize("tool", ["other_search", "ind_aidp_search"])
def test_other_and_independent_tool_overrides_do_not_trigger_managed_preparation(mocker, tool):
    read = mocker.patch.object(service, "snapshot_runtime_knowledge_tree")
    params = request_with({"top_k": 0}, tool=tool)
    service.prepare_tool_retrieval_overrides("tenant", agent_id=7, tool_params=params)
    read.assert_not_called()
    assert params.agents["root"].tools[tool] == {"top_k": 0}


@pytest.mark.parametrize("tool", ["aidp_search", "AidpSearchTool"])
def test_child_override_uses_its_own_instance_defaults(mocker, tool):
    tree = inherited_tree()
    tree[0]["tools"][0]["params"][0]["default"] = 30
    tree.append({"agent_name": "child", "tools": [{
        "name": "aidp_search", "class_name": "AidpSearchTool",
        "params": [{"name": "top_k", "default": 10}],
    }]})
    mocker.patch.object(service, "snapshot_runtime_knowledge_tree", return_value=tree)
    params = request_with({"hybrid_top_k": 12, "vector_candidates": 30, "full_text_candidates": 30}, agent="child", tool=tool)
    with pytest.raises(ValidationError, match="hybrid_top_k"):
        service.prepare_tool_retrieval_overrides("tenant", agent_id=7, version_no=3, tool_params=params)
