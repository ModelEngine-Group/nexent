# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace

import pytest

from management.services.knowledge_base import scope


@pytest.mark.parametrize(
    ("root_tools", "child_tools", "expected"),
    [
        ([], [], {"local": False, "aidp": False}),
        ([{"class_name": "KnowledgeBaseSearchTool"}], [], {"local": True, "aidp": False}),
        ([], [{"class_name": "AidpSearchTool"}], {"local": False, "aidp": True}),
        ([{"class_name": "KnowledgeBaseSearchTool"}], [{"class_name": "AidpSearchTool"}],
         {"local": True, "aidp": True}),
        ([{"class_name": "OtherTool", "name": "knowledge_base_search"}], [],
         {"local": False, "aidp": False}),
    ],
)
def test_configuration_sources_use_effective_versioned_tree_without_catalogs(
    mocker, root_tools, child_tools, expected,
):
    mocker.patch.object(scope, "search_agent_info_by_agent_id", return_value={"name": "agent"})
    relations = mocker.patch.object(
        scope, "query_sub_agent_relations",
        side_effect=lambda agent_id, *_: [{"selected_agent_id": 9, "selected_agent_version_no": 2}]
        if agent_id == 7 else [],
    )
    mocker.patch.object(scope, "resolve_sub_agent_version_no", return_value=2)
    tools = mocker.patch.object(
        scope, "_resolve_runtime_tool_records", side_effect=lambda agent_id, *_: root_tools if agent_id == 7 else child_tools,
    )
    catalog = mocker.patch.object(scope, "get_knowledge_info_by_tenant_id", side_effect=AssertionError("catalog read"))
    local_access = mocker.patch.object(scope.ElasticSearchService, "filter_accessible_indices",
                                     side_effect=AssertionError("local catalog access"))
    aidp_access = mocker.patch.object(scope, "_resolve_aidp_access_snapshot", side_effect=AssertionError("AIDP catalog read"))

    assert scope.get_agent_knowledge_sources(7, "tenant", 3) == expected
    tools.assert_has_calls([mocker.call(7, "tenant", 3), mocker.call(9, "tenant", 2)])
    relations.assert_called()
    catalog.assert_not_called()
    local_access.assert_not_called()
    aidp_access.assert_not_called()


def test_configuration_sources_propagate_resolution_failure(mocker):
    mocker.patch.object(scope, "_walk_agent_tree", side_effect=ValueError("invalid version"))
    with pytest.raises(ValueError, match="invalid version"):
        scope.get_agent_knowledge_sources(7, "tenant", 3)


def test_published_list_projects_sources_and_keeps_agents_with_invalid_dependencies(mocker):
    from management.services.agent import versions

    draft = {"agent_id": 7, "enabled": True, "current_version_no": 99, "name": "agent"}
    snapshot = {"agent_id": 7, "name": "agent", "model_ids": [], "version_no": 3}
    invalid_draft = {**draft, "agent_id": 8, "name": "unavailable_mcp_agent"}
    invalid_snapshot = {**snapshot, "agent_id": 8, "name": "unavailable_mcp_agent", "version_no": 4}
    mocker.patch.object(versions, "get_user_tenant_by_user_id", return_value={})
    mocker.patch.object(versions, "has_any_role", return_value=True)
    mocker.patch.object(versions, "query_all_agent_info_by_tenant_id", return_value=[invalid_draft, draft])
    mocker.patch.object(
        versions, "query_version_lists", return_value={7: [{"version_no": 3}], 8: [{"version_no": 4}]},
    )
    mocker.patch.object(
        versions, "query_agent_snapshots", return_value={7: (snapshot, [], []), 8: (invalid_snapshot, [], [])},
    )
    mocker.patch.object(versions, "load_agent_list_context", return_value=SimpleNamespace(
        model_cache=lambda: {}, valid_model_ids=lambda _: [],
    ))
    mocker.patch.object(versions, "check_agent_availability", return_value=(True, []))
    mocker.patch.object(versions, "apply_duplicate_name_availability_rules")
    mocker.patch.object(versions, "enrich_cas_usernames")
    mocker.patch.object(versions, "resolve_agent_list_permission", return_value="READ_ONLY")
    mocker.patch.object(versions, "project_authorized_resource_tags", side_effect=lambda agents, **_: agents)
    def resolve_sources(agent_id, *_):
        if agent_id == 8:
            raise versions.ValidationError("Enabled skills require unavailable tool 'removed_mcp'.")
        return {"local": True, "aidp": False}

    sources = mocker.patch.object(scope, "get_agent_knowledge_sources", side_effect=resolve_sources)

    result = versions._list_published_agents_sync("tenant", "user")

    agents = {agent["agent_id"]: agent for agent in result}
    assert set(agents) == {7, 8}
    assert agents[7]["knowledge_sources"] == {"local": True, "aidp": False}
    assert agents[7]["current_version_no"] == 3
    assert agents[8]["knowledge_sources"] == {"local": False, "aidp": False}
    sources.assert_has_calls([mocker.call(8, "tenant", 4), mocker.call(7, "tenant", 3)], any_order=True)
    assert sources.call_count == 2
