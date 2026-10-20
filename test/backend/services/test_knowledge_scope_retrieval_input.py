# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Submitted tool overrides are checked once before entering runtime resolution."""
from types import SimpleNamespace

import pytest

from backend.consts.model import ToolParamsRequest
from management.services.knowledge_base import scope as service
from consts.exceptions import ValidationError


def request_with(params, *, plan=None):
    return SimpleNamespace(
        tool_params=ToolParamsRequest(agents={"root": {"tools": {"aidp_search": params}}}),
        agent_id=7, version_no=3, is_debug=False, _runtime_mount_plan=plan,
    )


def inherited_tree():
    return [{"agent_name": "root", "tools": [{
        "name": "aidp_search", "class_name": "AidpSearchTool",
        "params": [{"name": "top_k", "default": 10}, {"name": "hybrid_top_k", "default": 6}],
    }]}]


@pytest.mark.parametrize("params", [
    {"top_k": True}, {"top_k": 0}, {"vector_candidates": 5},
    {"vector_candidates": 10.0}, {"search_method": []}, {"reranking_mode": []},
    {"reranking_enable": False, "graph_reranking_enable": True},
])
def test_request_override_is_rejected_before_runtime(mocker, params):
    mocker.patch.object(service, "snapshot_runtime_knowledge_tree", return_value=inherited_tree())
    with pytest.raises(ValidationError):
        service.validate_request_retrieval_overrides(request_with(params), "tenant")


def test_request_override_is_prepared_against_mounted_defaults_without_repository_read(mocker):
    read = mocker.patch.object(service, "snapshot_runtime_knowledge_tree")
    request = request_with(
        {"vector_candidates": 10, "search_method": "hybrid_search"},
        plan=SimpleNamespace(knowledge_tree=inherited_tree()),
    )
    service.validate_request_retrieval_overrides(request, "tenant")
    assert request.tool_params.agents["root"].tools["aidp_search"] == {
        "vector_candidates": None, "search_method": "vector_search|full_text_search|graph_search",
    }
    read.assert_not_called()


@pytest.mark.parametrize("params", [{}, {"kds_list": ["kb"]}])
def test_no_submitted_policy_does_not_read_or_validate_saved_policy(mocker, params):
    read = mocker.patch.object(service, "snapshot_runtime_knowledge_tree")
    service.validate_request_retrieval_overrides(request_with(params), "tenant")
    read.assert_not_called()
