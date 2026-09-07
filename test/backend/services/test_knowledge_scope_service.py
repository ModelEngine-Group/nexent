from unittest.mock import patch
from types import SimpleNamespace

import pytest

from backend.consts.model import ConversationKnowledgeScopeRequest, ToolParamsRequest
from consts.exceptions import ValidationError
from backend.services.knowledge_scope_service import (
    ResolvedKnowledgeScope,
    STATIC_SCOPE_PATTERN,
    _merge_tool_params,
    _parse_list,
    _resolve_aidp_override,
    _resolve_local_override,
    _tool_default,
    _walk_agent_tree,
    build_runtime_knowledge_policy,
    build_runtime_knowledge_resources,
    get_agent_knowledge_capabilities,
    resolve_root_version,
    resolve_knowledge_scope,
)


def _agent_tree():
    return [{
        "agent_id": 7,
        "version_no": 3,
        "agent_name": "root-agent",
        "tools": [
            {
                "class_name": "KnowledgeBaseSearchTool",
                "name": "knowledge_base_search",
                "params": [{"name": "index_names", "default": ["default-index"]}],
            },
            {
                "class_name": "AidpSearchTool",
                "name": "aidp_search",
                "params": [{"name": "kds_list", "default": ["default-kds"]}],
            },
        ],
    }]


@patch("backend.services.knowledge_scope_service._walk_agent_tree", return_value=_agent_tree())
@patch("backend.services.knowledge_scope_service._resolve_local_override")
def test_override_projects_only_selected_local_indices(mock_local_override, _mock_tree):
    mock_local_override.return_value = ([{
        "knowledge_id": 12,
        "index_name": "selected-index",
        "knowledge_name": "Selected KB",
        "embedding_model_id": 9,
    }], [])
    scope = ConversationKnowledgeScopeRequest.model_validate({
        "local": {"mode": "override", "knowledge_ids": ["12"]},
        "aidp": {"mode": "disabled", "kds_ids": []},
    })

    resolved = resolve_knowledge_scope(
        scope=scope,
        agent_id=7,
        tenant_id="tenant",
        user_id="user",
        version_no=3,
        is_debug=False,
    )

    tools = resolved.tool_params.agents["root-agent"].tools
    assert tools["knowledge_base_search"]["index_names"] == ["selected-index"]
    assert tools["aidp_search"]["kds_list"] == []
    assert resolved.local_knowledge_ids == ["12"]
    assert resolved.local_index_names == ["selected-index"]
    assert resolved.aidp_disabled is True


@patch("backend.services.knowledge_scope_service._walk_agent_tree", return_value=_agent_tree())
@patch(
    "backend.services.knowledge_scope_service._resolve_aidp_access_snapshot",
    return_value=SimpleNamespace(
        accessible_id_set={"default-kds", "user-selected-kds"},
        name_to_id={
            "Default AIDP": "default-kds",
            "User selected": "user-selected-kds",
        },
    ),
)
def test_aidp_override_can_select_accessible_kds_outside_agent_default(
    _mock_snapshot, _mock_tree
):
    scope = ConversationKnowledgeScopeRequest.model_validate({
        "local": {"mode": "disabled", "knowledge_ids": []},
        "aidp": {"mode": "override", "kds_ids": ["user-selected-kds"]},
    })

    resolved = resolve_knowledge_scope(
        scope=scope,
        agent_id=7,
        tenant_id="tenant",
        user_id="user",
        version_no=3,
        is_debug=False,
    )

    tools = resolved.tool_params.agents["root-agent"].tools
    assert tools["aidp_search"]["kds_list"] == ["user-selected-kds"]
    assert resolved.aidp_kds_ids == ["user-selected-kds"]
    assert resolved.aidp_display_names == ["User selected"]


@patch("backend.services.knowledge_scope_service._walk_agent_tree", return_value=_agent_tree())
def test_disabled_projects_deny_all_whitelists(_mock_tree):
    scope = ConversationKnowledgeScopeRequest.model_validate({
        "local": {"mode": "disabled", "knowledge_ids": []},
        "aidp": {"mode": "disabled", "kds_ids": []},
    })

    resolved = resolve_knowledge_scope(
        scope=scope,
        agent_id=7,
        tenant_id="tenant",
        user_id="user",
        version_no=3,
        is_debug=False,
    )

    tools = resolved.tool_params.agents["root-agent"].tools
    assert tools["knowledge_base_search"]["index_names"] == []
    assert tools["aidp_search"]["kds_list"] == []
    assert resolved.local_disabled is True
    assert resolved.aidp_disabled is True


@patch("backend.services.knowledge_scope_service._walk_agent_tree", return_value=_agent_tree())
@patch("backend.services.knowledge_scope_service.resolve_root_version", return_value=3)
@patch(
    "backend.services.knowledge_scope_service.get_knowledge_info_by_tenant_id",
    return_value=[{
        "knowledge_id": 12,
        "index_name": "default-index",
    }],
)
@patch(
    "backend.services.knowledge_scope_service.ElasticSearchService.filter_accessible_indices",
    return_value=["default-index"],
)
@patch(
    "backend.services.knowledge_scope_service._filter_accessible_aidp_ids",
    return_value=["default-kds"],
)
def test_capabilities_include_stable_revision(
    _mock_aidp, _mock_accessible, _mock_records, _mock_version, _mock_tree
):
    first = get_agent_knowledge_capabilities(7, "tenant", None, user_id="user")
    second = get_agent_knowledge_capabilities(7, "tenant", None, user_id="user")

    assert first["sources"]["local"]["max_select"] == 50
    assert first["sources"]["aidp"]["max_select"] == 10
    assert first["sources"]["local"]["default_knowledge_ids"] == ["12"]
    assert first["sources"]["local"]["default_range_values"] == ["default-index"]
    assert first["capability_revision"] == second["capability_revision"]
    assert len(first["capability_revision"]) == 16
    assert first["legacy_prompt_warning"]["detected"] is False


@patch(
    "backend.services.knowledge_scope_service._walk_agent_tree",
    return_value=[{
        **_agent_tree()[0],
        "has_static_scope_reference": True,
    }],
)
@patch("backend.services.knowledge_scope_service.resolve_root_version", return_value=3)
def test_capabilities_report_legacy_static_scope(_mock_version, _mock_tree):
    result = get_agent_knowledge_capabilities(7, "tenant", None)

    assert result["legacy_prompt_warning"] == {
        "detected": True,
        "affected_agent_ids": [7],
        "reason_code": "STATIC_KNOWLEDGE_SCOPE_REFERENCE",
    }


def test_static_scope_scanner_uses_high_confidence_assignment_pattern():
    assert STATIC_SCOPE_PATTERN.search('index_names=["fixed-index"]')
    assert STATIC_SCOPE_PATTERN.search('kds_list: ["fixed-kds"]')
    assert not STATIC_SCOPE_PATTERN.search("Do not use fixed index_names values")


def test_runtime_resource_names_are_sanitized_and_bounded():
    resolved = ResolvedKnowledgeScope(
        desired_scope={},
        tool_params=ToolParamsRequest(agents={}),
        local_display_names=["first\nname\x00", "\u200bsecond"],
        aidp_display_names=[f"aidp-{index}" for index in range(20)],
    )

    content = build_runtime_knowledge_resources(resolved, "en")

    assert "first name" in content
    assert "\x00" not in content
    assert "\u200b" not in content
    assert "10. aidp-9" in content
    assert "11. aidp-10" not in content


@patch("backend.services.knowledge_scope_service.query_current_version_no", return_value=8)
def test_root_version_resolution(mock_current_version):
    assert resolve_root_version(1, "tenant", 4, False) == 4
    assert resolve_root_version(1, "tenant", None, True) == 0
    assert resolve_root_version(1, "tenant", None, False) == 8
    mock_current_version.assert_called_once_with(agent_id=1, tenant_id="tenant")


def test_list_and_tool_default_parsing_is_defensive():
    assert _parse_list(None) == []
    assert _parse_list('["a", 2, ""]') == ["a", "2"]
    assert _parse_list("not-json") == []
    assert _parse_list({"not": "a-list"}) == []
    assert _tool_default(
        {"params": [{"name": "index_names", "default": '["index-a"]'}]},
        "index_names",
    ) == ["index-a"]
    assert _tool_default({"params": []}, "index_names") == []


@patch(
    "backend.services.knowledge_scope_service._resolve_runtime_tool_records",
    side_effect=[[{"class_name": "root-tool"}], [{"class_name": "child-tool"}]],
)
@patch(
    "backend.services.knowledge_scope_service.resolve_sub_agent_version_no",
    return_value=2,
)
@patch(
    "backend.services.knowledge_scope_service.query_sub_agent_relations",
    side_effect=[[{"selected_agent_id": 9}], []],
)
@patch(
    "backend.services.knowledge_scope_service.search_agent_info_by_agent_id",
    side_effect=[
        {"name": "root", "constraint_prompt": 'index_names: ["fixed"]'},
        {"name": "child"},
    ],
)
def test_walk_agent_tree_resolves_children_and_static_prompt(
    _mock_agent_info,
    _mock_relations,
    _mock_child_version,
    _mock_tools,
):
    nodes = _walk_agent_tree(7, "tenant", 1)

    assert [node["agent_id"] for node in nodes] == [7, 9]
    assert nodes[0]["has_static_scope_reference"] is True
    assert nodes[1]["version_no"] == 2
    assert _walk_agent_tree(7, "tenant", 1, {(7, 1)}) == []


@patch(
    "backend.services.knowledge_scope_service.ElasticSearchService.filter_accessible_indices",
    return_value=["index-a"],
)
@patch(
    "backend.services.knowledge_scope_service.get_knowledge_info_by_ids_and_tenant",
    return_value=[
        {"knowledge_id": 1, "index_name": "index-a", "embedding_model_id": 3},
        {"knowledge_id": 2, "index_name": "index-b", "embedding_model_id": 3},
    ],
)
def test_local_override_filters_inaccessible_and_invalid_ids(_mock_records, _mock_filter):
    records, warnings = _resolve_local_override(
        ["1", "2", "invalid"], "user", "tenant"
    )

    assert [record["knowledge_id"] for record in records] == [1]
    assert warnings[0]["count"] == 2


@patch(
    "backend.services.knowledge_scope_service.ElasticSearchService.filter_accessible_indices",
    return_value=["index-a", "index-b"],
)
@patch(
    "backend.services.knowledge_scope_service.get_knowledge_info_by_ids_and_tenant",
    return_value=[
        {"knowledge_id": 1, "index_name": "index-a", "embedding_model_id": 3},
        {"knowledge_id": 2, "index_name": "index-b", "embedding_model_name": "other"},
    ],
)
def test_local_override_rejects_mixed_embedding_models(_mock_records, _mock_filter):
    with pytest.raises(ValidationError, match="same embedding model"):
        _resolve_local_override(["1", "2"], "user", "tenant")


def test_aidp_override_filters_names_and_reports_removed():
    ids, names, warnings = _resolve_aidp_override(
        ["kds-a", "kds-b"],
        {"kds-a"},
        {"Allowed": "kds-a", "Hidden": "kds-b"},
    )

    assert ids == ["kds-a"]
    assert names == {"Allowed": "kds-a"}
    assert warnings[0]["count"] == 1


def test_merge_tool_params_preserves_non_scope_parameters():
    original = ToolParamsRequest.model_validate({
        "agents": {
            "root-agent": {
                "tools": {"knowledge_base_search": {"top_k": 7}}
            }
        }
    })

    merged = _merge_tool_params(
        original,
        {"root-agent": {"knowledge_base_search": {"index_names": ["a"]}}},
    )

    params = merged.agents["root-agent"].tools["knowledge_base_search"]
    assert params == {"top_k": 7, "index_names": ["a"]}


@patch(
    "backend.services.knowledge_scope_service._resolve_aidp_access_snapshot",
    return_value=SimpleNamespace(
        accessible_id_set={"default-kds"},
        name_to_id={"Default AIDP": "default-kds"},
    ),
)
@patch(
    "backend.services.knowledge_scope_service.get_knowledge_name_map_by_index_names",
    return_value={"default-index": "Default Local"},
)
@patch(
    "backend.services.knowledge_scope_service.ElasticSearchService.filter_accessible_indices",
    return_value=["default-index"],
)
@patch("backend.services.knowledge_scope_service._walk_agent_tree", return_value=_agent_tree())
def test_inherit_resolves_each_tool_default_and_display_name(
    _mock_tree,
    _mock_local_filter,
    _mock_local_names,
    _mock_aidp_snapshot,
):
    scope = ConversationKnowledgeScopeRequest()

    resolved = resolve_knowledge_scope(
        scope=scope,
        agent_id=7,
        tenant_id="tenant",
        user_id="user",
        version_no=3,
        is_debug=False,
    )

    assert resolved.local_display_names == ["Default Local"]
    assert resolved.aidp_display_names == ["Default AIDP"]
    assert resolved.warnings == []


@patch(
    "backend.services.knowledge_scope_service._walk_agent_tree",
    return_value=[
        {"agent_id": 1, "version_no": 1, "agent_name": None, "tools": []},
        {"agent_id": 2, "version_no": 1, "agent_name": "plain", "tools": []},
    ],
)
def test_missing_capabilities_do_not_warn_for_inherited_scope(_mock_tree):
    resolved = resolve_knowledge_scope(
        scope=ConversationKnowledgeScopeRequest(),
        agent_id=1,
        tenant_id="tenant",
        user_id="user",
        version_no=1,
        is_debug=False,
    )

    assert resolved.warnings == []
    assert resolved.local_capable is False
    assert resolved.aidp_capable is False
    assert resolved.local_index_names == []
    assert resolved.aidp_kds_ids == []


@patch(
    "backend.services.knowledge_scope_service._walk_agent_tree",
    return_value=[
        {"agent_id": 1, "version_no": 1, "agent_name": "plain", "tools": []},
    ],
)
@patch(
    "backend.services.knowledge_scope_service._resolve_local_override",
    return_value=([], []),
)
def test_missing_capability_warns_for_explicit_override(_mock_local, _mock_tree):
    scope = ConversationKnowledgeScopeRequest.model_validate({
        "local": {"mode": "override", "knowledge_ids": ["12"]},
        "aidp": {"mode": "inherit", "kds_ids": []},
    })

    resolved = resolve_knowledge_scope(
        scope=scope,
        agent_id=1,
        tenant_id="tenant",
        user_id="user",
        version_no=1,
        is_debug=False,
    )

    assert resolved.warnings == [{
        "code": "KNOWLEDGE_SCOPE_CAPABILITY_UNSUPPORTED",
        "source": "local",
        "count": 1,
    }]


def test_runtime_policy_and_empty_resource_variants():
    assert "当前会话" in build_runtime_knowledge_policy("zh")
    assert "platform-resolved" in build_runtime_knowledge_policy("en")
    resolved = ResolvedKnowledgeScope(
        desired_scope={},
        tool_params=ToolParamsRequest(agents={}),
    )
    zh_content = build_runtime_knowledge_resources(resolved, "zh")
    assert "当前会话没有可用知识库资源" in zh_content
    resolved.local_disabled = True
    resolved.aidp_disabled = True
    en_content = build_runtime_knowledge_resources(resolved, "en")
    assert "Knowledge retrieval is disabled for this conversation" in en_content


def test_runtime_resources_omit_unsupported_sources():
    resolved = ResolvedKnowledgeScope(
        desired_scope={},
        tool_params=ToolParamsRequest(agents={}),
        local_disabled=True,
        local_capable=True,
        aidp_capable=False,
    )

    content = build_runtime_knowledge_resources(resolved, "zh")

    assert "当前会话已禁用知识库检索" in content
    assert "本地知识库：当前会话已禁用" not in content
    assert "AIDP 知识库" not in content


def test_runtime_resources_only_describe_effective_source():
    resolved = ResolvedKnowledgeScope(
        desired_scope={},
        tool_params=ToolParamsRequest(agents={}),
        local_display_names=["本地1"],
        aidp_disabled=True,
        local_capable=True,
        aidp_capable=True,
    )

    content = build_runtime_knowledge_resources(resolved, "zh")

    assert "本地知识库：" in content
    assert "本地1" in content
    assert "AIDP 知识库" not in content
    assert "当前会话已禁用" not in content
