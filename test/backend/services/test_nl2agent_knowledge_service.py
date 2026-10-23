# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit proof for authorized knowledge recommendation and draft enrichment."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from management.services.knowledge_base.recommendation import (
    load_visible_knowledge,
    merge_selection,
    rank_knowledge,
    selection_values,
)


def kb(value, name="Expense policy", **extra):
    return {
        "id": value,
        "binding_value": value,
        "name": name,
        "embedding_model_id": 1,
        **extra,
    }


@pytest.mark.parametrize(
    "value,expected",
    [
        ('["001", "002"]', ["001", "002"]),
        ("001,002", ["001", "002"]),
        ([], []),
        ("[]", []),
        ("[broken", []),
        (None, []),
        (["001", "001", "", None, True], ["001"]),
    ],
)
def test_selection_values_preserve_identity(value, expected):
    assert selection_values(value) == expected


def test_rank_subtracts_bound_and_uses_metadata_without_mutation():
    catalog = [
        kb("bound"),
        kb("suggested", summary="Expense policy and invoices"),
        kb("unrelated", "Weather data"),
    ]
    result = rank_knowledge(
        catalog, ["Expense policy"], ["bound"], tool_name="knowledge_base_search"
    )
    assert [item["binding_value"] for item in result] == ["suggested"]
    assert result[0]["name"] == "Expense policy"
    assert "score" not in catalog[1]
    assert (
        rank_knowledge(
            catalog, ["marine biology"], [], tool_name="knowledge_base_search"
        )
        == []
    )
    assert (
        rank_knowledge(
            catalog, ["knowledge", "知识库"], [], tool_name="knowledge_base_search"
        )
        == []
    )
    assert (
        rank_knowledge(
            [kb("capital", "Capital plans")],
            ["API"],
            [],
            tool_name="knowledge_base_search",
        )
        == []
    )
    assert (
        rank_knowledge(
            [kb("api", "API reference")], ["API"], [], tool_name="knowledge_base_search"
        )[0]["id"]
        == "api"
    )


def test_rank_uses_summary_and_keeps_embedding_group_and_aidp_cap():
    catalog = [
        kb("bound", embedding_model_id=2),
        kb("wrong", embedding_model_id=1),
        kb("same", "Company records", summary="Expense policy", embedding_model_id=2),
    ]
    assert [
        r["id"]
        for r in rank_knowledge(
            catalog, ["Expense policy"], ["bound"], tool_name="knowledge_base_search"
        )
    ] == ["same"]
    assert (
        rank_knowledge(
            [kb("image", is_multimodal=True)],
            ["Expense policy"],
            [],
            tool_name="knowledge_base_search",
            multimodal=False,
        )
        == []
    )
    catalog = [kb(f"00{i}") for i in range(15)]
    results = rank_knowledge(
        catalog,
        ["Expense policy"],
        [f"00{i}" for i in range(8)],
        tool_name="aidp_search",
    )
    assert len(results) == 2
    assert all(item["id"].startswith("00") for item in results)
    assert (
        len(rank_knowledge(catalog, ["Expense policy"], [], tool_name="aidp_search"))
        == 5
    )


def test_merge_selection_keeps_settings_and_serializes_aidp_strings():
    config = [{"name": "top_k", "type": "number", "required": False, "value": 7}]
    result = merge_selection(config, "aidp_search", ["001"])
    assert result[0] == config[0]
    assert json.loads(result[-1]["value"]) == ["001"]
    assert len(config) == 1


def test_local_catalog_reads_only_authorized_indices_and_stored_summary(mocker):
    core = mocker.patch(
        "management.services.knowledge_base.common.get_vector_db_core",
        return_value=object(),
    ).return_value
    query = mocker.patch(
        "management.services.knowledge_base.service.ElasticSearchService.list_indices",
        return_value={"indices": ["allowed"]},
    )
    metadata = mocker.patch(
        "database.knowledge_db.get_knowledge_metadata_by_index_names",
        return_value=[
            {
                "knowledge_id": 1,
                "index_name": "allowed",
                "knowledge_name": "Company records",
                "knowledge_describe": "Expense policy",
                "embedding_model_id": 9,
            },
            {"knowledge_id": 2, "index_name": "forbidden", "knowledge_name": "Private"},
        ],
    )
    result = load_visible_knowledge("knowledge_base_search", user_id="u", tenant_id="t")
    query.assert_any_call(
        user_id="u", target_tenant_id="t", include_stats=False, vdb_core=core
    )
    assert all(call.kwargs["user_id"] == "u" for call in query.call_args_list)
    metadata.assert_called_once_with(["allowed"])
    assert [item["binding_value"] for item in result] == ["allowed"]
    assert (
        rank_knowledge(
            result, ["Expense policy"], [], tool_name="knowledge_base_search"
        )[0]["id"]
        == "1"
    )


def test_aidp_catalog_preserves_authorized_string_ids_and_filters_inactive(mocker):
    mocker.patch(
        "management.services.knowledge_base.scope._resolve_aidp_access_snapshot",
        return_value=SimpleNamespace(
            accessible_rows=[
                {
                    "kb_id": "0001",
                    "kds_name": "Expense policy",
                    "description": "Invoices",
                },
                {
                    "kb_id": "0002",
                    "kds_name": "Deleted policy",
                    "resource_status": "DELETED",
                },
            ]
        ),
    )
    result = load_visible_knowledge("aidp_search", user_id="u", tenant_id="t")
    assert len(result) == 1
    assert result[0]["binding_value"] == "0001"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["knowledge_base_search", "aidp_search"])
async def test_recommendation_enriches_real_card_and_preserves_current_binding(
    mocker, tool_name
):
    from services import nl2agent_service as service
    from tool_collection.mcp.nl2agent_mcp_tools import ResourceCandidate

    field = "kds_list" if tool_name == "aidp_search" else "index_names"
    actual = {
        "candidate_ref": "tool:7",
        "resource_type": "tool",
        "source": "LOCAL_TOOL",
        "name": tool_name,
        "names": [tool_name],
        "description": "Search knowledge",
        "inputs": {},
        "config": [{"name": "top_k", "type": "number", "value": 3}],
    }
    mocker.patch.object(
        service, "_load_installed_resource_catalog", AsyncMock(return_value=[actual])
    )
    query = mocker.patch.object(
        service,
        "query_all_enabled_tool_instances",
        return_value=[
            {
                "tool_id": 7,
                "params": {
                    field: json.dumps(["bound"])
                    if tool_name == "aidp_search"
                    else ["bound"],
                    "top_k": 8,
                },
            }
        ],
    )
    loader = mocker.patch.object(
        service, "run_blocking", AsyncMock(return_value=[kb("bound"), kb("001")])
    )
    supplied = ResourceCandidate(
        candidate_ref="tool:7",
        resource_type="tool",
        source="LOCAL_TOOL",
        name="tampered",
        requirement_ids=["expense"],
        score=0.9,
        knowledge_queries=["Expense policy"],
    )
    result = await service.recommend_installed_resources_impl(
        agent_id=42,
        candidates=[supplied],
        recommended_refs=["tool:7"],
        tenant_id="t",
        user_id="u",
    )
    serialized = result.model_dump(mode="json")["resources"][0]
    assert serialized["candidate"]["source"] == "LOCAL_TOOL"
    assert "source" not in serialized["knowledge_recommendations"][0]
    assert serialized["knowledge_recommendations"][0]["binding_value"] == "001"
    resource = result.resources[0]
    assert resource.candidate.name == tool_name
    assert resource.is_bound is False
    assert resource.knowledge_recommendations[0].binding_value == "001"
    values = {param["name"]: param.get("value") for param in resource.config}
    assert selection_values(values[field]) == ["bound", "001"]
    assert values["top_k"] == 8
    assert loader.await_count == 1
    query.assert_called_once_with(agent_id=42, tenant_id="t", version_no=0)


@pytest.mark.asyncio
async def test_no_match_keeps_generic_and_provider_error_is_retryable(mocker):
    from services import nl2agent_service as service
    from tool_collection.mcp.nl2agent_mcp_tools import ResourceCandidate

    actual = {
        "candidate_ref": "tool:7",
        "resource_type": "tool",
        "source": "LOCAL_TOOL",
        "name": "knowledge_base_search",
        "names": ["knowledge_base_search"],
        "description": "Search knowledge",
        "inputs": {},
        "config": [],
    }
    mocker.patch.object(
        service, "_load_installed_resource_catalog", AsyncMock(return_value=[actual])
    )
    mocker.patch.object(service, "query_all_enabled_tool_instances", return_value=[])
    loader = mocker.patch.object(
        service, "run_blocking", AsyncMock(return_value=[kb("weather", "Weather data")])
    )
    supplied = ResourceCandidate(
        candidate_ref="tool:7",
        resource_type="tool",
        source="LOCAL_TOOL",
        name="knowledge_base_search",
        requirement_ids=["expense"],
        score=0.9,
        knowledge_queries=["Expense policy"],
    )
    kwargs = {
        "agent_id": 42,
        "candidates": [supplied],
        "recommended_refs": ["tool:7"],
        "tenant_id": "t",
        "user_id": "u",
    }
    resource = (await service.recommend_installed_resources_impl(**kwargs)).resources[0]
    assert resource.knowledge_recommendations == []
    assert resource.candidate.name == "knowledge_base_search"
    assert selection_values(resource.config[-1]["value"]) == []
    loader.side_effect = RuntimeError("provider failed")
    with pytest.raises(service.Nl2AgentResourceError) as error:
        await service.recommend_installed_resources_impl(**kwargs)
    assert error.value.retryable is True
    assert error.value.code == "knowledge_search_failed"


def test_metadata_bulk_read_skips_empty_and_returns_active_query(mocker):
    from database.knowledge_db import get_knowledge_metadata_by_index_names

    sessions = mocker.patch("database.knowledge_db.get_db_session")
    assert get_knowledge_metadata_by_index_names([]) == []
    sessions.assert_not_called()
    query = sessions.return_value.__enter__.return_value.query.return_value.filter.return_value
    record = object()
    query.all.return_value = [record]
    mocker.patch(
        "database.knowledge_db.as_dict", return_value={"index_name": "allowed"}
    )
    assert get_knowledge_metadata_by_index_names(["allowed"]) == [
        {"index_name": "allowed"}
    ]
    sessions.return_value.__enter__.return_value.query.return_value.filter.assert_called_once()


@pytest.mark.asyncio
async def test_installed_search_carries_matched_intent_to_concrete_recommendation(
    mocker,
):
    from services import nl2agent_service as service
    from tool_collection.mcp.nl2agent_mcp_tools import ResourceRequirement

    actual = {
        "candidate_ref": "tool:7",
        "resource_type": "tool",
        "source": "LOCAL_TOOL",
        "name": "knowledge_base_search",
        "names": ["knowledge_base_search"],
        "description": "Search Expense policy knowledge",
        "descriptions": ["Search Expense policy knowledge"],
        "labels": [],
        "interfaces": [],
        "inputs": {},
        "config": [],
        "installed": True,
    }
    mocker.patch.object(
        service, "_load_installed_resource_catalog", AsyncMock(return_value=[actual])
    )
    mocker.patch.object(service, "query_all_enabled_tool_instances", return_value=[])
    mocker.patch.object(service, "run_blocking", AsyncMock(return_value=[kb("001")]))
    fallback = mocker.patch.object(
        service,
        "require_agent_draft_edit",
        side_effect=AssertionError("Search intent must be preserved"),
    )
    found = await service.search_installed_resources_impl(
        requirements=[
            ResourceRequirement(
                requirement_id="expense",
                query="Expense policy",
                search_terms=["expense"],
            )
        ],
        tenant_id="t",
        user_id="u",
    )
    assert found.candidates[0].knowledge_queries == ["Expense policy", "expense"]
    result = await service.recommend_installed_resources_impl(
        agent_id=42,
        candidates=found.candidates,
        recommended_refs=["tool:7"],
        tenant_id="t",
        user_id="u",
    )
    assert result.resources[0].knowledge_recommendations[0].name == "Expense policy"
    fallback.assert_not_called()
