# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Submitted tool overrides are checked once before entering runtime resolution."""
from types import SimpleNamespace

import pytest

from backend.consts.model import ToolParamsRequest
from management.services.knowledge_base import scope as service
from consts.exceptions import ValidationError


def request_with(params):
    return SimpleNamespace(
        tool_params=ToolParamsRequest(agents={"root": {"tools": {"aidp_search": params}}}),
        agent_id=7, version_no=3, is_debug=False,
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
        service.prepare_retrieval_request("tenant", tool_params=request_with(params).tool_params, agent_id=7, version_no=3)


def test_request_override_is_prepared_against_actual_tool_defaults(mocker):
    mocker.patch.object(service, "snapshot_runtime_knowledge_tree", return_value=inherited_tree())
    request = request_with({"vector_candidates": 10, "search_method": "hybrid_search"})
    service.prepare_retrieval_request(
        "tenant", tool_params=request.tool_params, agent_id=7, version_no=3,
    )
    assert request.tool_params.agents["root"].tools["aidp_search"] == {
        "vector_candidates": 10, "search_method": "vector_search|full_text_search|graph_search",
    }


@pytest.mark.parametrize("params", [{}, {"kds_list": ["kb"]}])
def test_no_submitted_policy_does_not_read_or_validate_saved_policy(mocker, params):
    read = mocker.patch.object(service, "snapshot_runtime_knowledge_tree")
    service.prepare_retrieval_request("tenant", tool_params=request_with(params).tool_params, agent_id=7, version_no=3)
    read.assert_not_called()


def test_debug_scope_uses_draft_inheritance_when_no_version_is_requested(mocker):
    from consts.model import ConversationKnowledgeScopeRequest
    mocker.patch.object(service, "ENABLE_AIDP_KNOWLEDGE", True)
    mocker.patch.object(service, "query_current_version_no", return_value=3)
    def snapshot(agent_id, tenant_id, version):
        return [{"agent_name": "root", "tools": [{"class_name": "AidpSearchTool", "params": [
            {"name": "top_k", "default": 30 if version == 0 else 10},
        ]}]}]
    read = mocker.patch.object(service, "snapshot_runtime_knowledge_tree", side_effect=snapshot)
    policy = {"hybrid_top_k": 12, "vector_candidates": 30, "full_text_candidates": 30}
    scope = ConversationKnowledgeScopeRequest(retrieval_config=dict(policy))
    service.prepare_retrieval_request("tenant", scope=scope, agent_id=7, is_debug=True)
    read.assert_called_once_with(7, "tenant", 0)
    assert scope.retrieval_config == policy
    with pytest.raises(ValidationError, match="hybrid_top_k"):
        service.prepare_retrieval_request(
            "tenant", scope=ConversationKnowledgeScopeRequest(retrieval_config=dict(policy)), agent_id=7,
        )


def test_tool_override_inherits_prepared_scope_policy(mocker):
    from consts.model import ConversationKnowledgeScopeRequest
    mocker.patch.object(service, "ENABLE_AIDP_KNOWLEDGE", True)
    read = mocker.patch.object(service, "snapshot_runtime_knowledge_tree", return_value=inherited_tree())
    scope = ConversationKnowledgeScopeRequest(retrieval_config={"top_k": 20})
    request = request_with({"hybrid_top_k": 12, "vector_candidates": 30, "full_text_candidates": 30})
    service.prepare_retrieval_request(
        "tenant", scope=scope, tool_params=request.tool_params, agent_id=7, version_no=3,
    )
    read.assert_called_once_with(7, "tenant", 3)
    assert scope.retrieval_config == {"top_k": 20}
    assert request.tool_params.agents["root"].tools["aidp_search"]["hybrid_top_k"] == 12


def test_new_override_uses_stored_workbench_policy_without_revalidating_it(mocker, monkeypatch):
    import nexent.core.ext_components.aidp.retrieval_config as policy
    read = mocker.patch.object(service, "snapshot_runtime_knowledge_tree", return_value=inherited_tree())
    original = policy.validate_config
    calls = []
    def check(config, inherited=None):
        calls.append(dict(config))
        return original(config, inherited)
    monkeypatch.setattr(policy, "validate_config", check)
    raw = {"hybrid_top_k": 12, "vector_candidates": 30, "full_text_candidates": 30}
    request = request_with(raw)
    service.prepare_retrieval_request(
        "tenant", tool_params=request.tool_params, agent_id=7, version_no=3,
        stored_scope={"retrieval_config": {"top_k": 30}},
    )
    read.assert_called_once()
    assert calls == [raw]


def test_empty_scope_policy_does_not_revalidate_saved_values(mocker):
    from consts.model import ConversationKnowledgeScopeRequest
    mocker.patch.object(service, "ENABLE_AIDP_KNOWLEDGE", True)
    read = mocker.patch.object(service, "snapshot_runtime_knowledge_tree")
    scope = ConversationKnowledgeScopeRequest(retrieval_config={})
    service.prepare_retrieval_request("tenant", scope=scope, agent_id=7, version_no=3)
    assert scope.retrieval_config == {}
    read.assert_not_called()


def test_unchanged_scope_is_trusted_but_new_tool_override_is_checked(mocker):
    from consts.model import ConversationKnowledgeScopeRequest

    mocker.patch.object(service, "ENABLE_AIDP_KNOWLEDGE", True)
    mocker.patch.object(service, "snapshot_runtime_knowledge_tree", return_value=inherited_tree())
    prepare = mocker.patch.object(service, "prepare_config", wraps=service.prepare_config)
    scope = ConversationKnowledgeScopeRequest(retrieval_config={"top_k": 30})
    raw = {"hybrid_top_k": 12, "vector_candidates": 30, "full_text_candidates": 30}
    service.prepare_retrieval_request(
        "tenant", agent_id=7, version_no=3, scope=scope,
        stored_scope={"retrieval_config": {"top_k": 30}},
        tool_params=request_with(raw).tool_params,
    )
    assert prepare.call_count == 1
    assert prepare.call_args.args[0] == raw
    assert prepare.call_args.args[1]["top_k"] == 30


def test_unchanged_scope_without_override_does_not_read_saved_tools(mocker):
    from consts.model import ConversationKnowledgeScopeRequest

    mocker.patch.object(service, "ENABLE_AIDP_KNOWLEDGE", True)
    read = mocker.patch.object(service, "snapshot_runtime_knowledge_tree")
    prepare = mocker.patch.object(service, "prepare_config", wraps=service.prepare_config)
    scope = ConversationKnowledgeScopeRequest(retrieval_config={"top_k": 30})
    service.prepare_retrieval_request(
        "tenant", agent_id=7, scope=scope,
        stored_scope={"retrieval_config": {"top_k": 30}},
    )
    read.assert_not_called()
    prepare.assert_not_called()


def test_other_tool_overrides_do_not_trigger_aidp_preparation(mocker):
    read = mocker.patch.object(service, "snapshot_runtime_knowledge_tree")
    tool_params = ToolParamsRequest(agents={"root": {"tools": {"other_search": {"top_k": 0}}}})
    service.prepare_retrieval_request("tenant", agent_id=7, tool_params=tool_params)
    read.assert_not_called()
    assert tool_params.agents["root"].tools["other_search"] == {"top_k": 0}


@pytest.mark.parametrize("tool_name", ["aidp_search", "AidpSearchTool"])
def test_child_tool_override_uses_child_defaults_instead_of_root_policy(mocker, tool_name):
    tree = inherited_tree()
    tree.append({"agent_name": "child", "tools": [{
        "name": "aidp_search", "class_name": "AidpSearchTool",
        "params": [{"name": "top_k", "default": 10}],
    }]})
    mocker.patch.object(service, "snapshot_runtime_knowledge_tree", return_value=tree)
    tool_params = ToolParamsRequest(agents={"child": {"tools": {tool_name: {
        "hybrid_top_k": 12, "vector_candidates": 30, "full_text_candidates": 30,
    }}}})
    with pytest.raises(ValidationError, match="hybrid_top_k"):
        service.prepare_retrieval_request(
            "tenant", agent_id=7, version_no=3, tool_params=tool_params,
            stored_scope={"retrieval_config": {"top_k": 30}},
        )
