# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Knowledge suggestions are card scoped, selectable, private and side-effect free."""

import importlib
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from infrastructure.system_configuration.catalog import DEFAULT_CATALOG
from services.nl2agent_state_service import ResourceScope, ResourceStateError


@pytest.fixture
def context(monkeypatch):
    module = importlib.import_module("services.nl2agent_knowledge_recommendations")
    flow = importlib.import_module("services.nl2agent_resource_flow")
    snapshot = DEFAULT_CATALOG.build_snapshot(DEFAULT_CATALOG.defaults)
    monkeypatch.setattr(flow, "get_config_snapshot", lambda: snapshot)
    state = {"conversation_id": "2", "version": 3, "card": {"id": "card", "subtype": "requirement_resources"},
             "requirements": {"r1": {"query": "员工报销政策", "installed": [{"candidate_ref": "tool:7", "resource_type": "tool",
                 "source": "LOCAL_TOOL", "name": "knowledge_base_search", "description": "Search knowledge", "retrieval_score": .9}],
                 "installable": [], "accepted": ["tool:7"]}}}
    models = {"embedding": {"model_id": 11, "model_name": "current"}, "multi_embedding": {}}
    tools = [{"candidate_ref": "tool:7", "resource_type": "tool", "source": "LOCAL_TOOL", "name": "knowledge_base_search",
              "names": ["knowledge_base_search"], "config": [{"name": "top_k", "type": "number", "value": 5}]}]
    catalog = [{"id": "1", "binding_value": "expense", "name": "员工报销政策", "summary": "差旅费用", "embedding_model_id": 11,
                "document_count": 2, "is_multimodal": False}]
    async def blocking(_task, operation, *args, **kwargs):
        kwargs.pop("lane", None)
        kwargs.pop("owner", None)
        return operation(*args, **kwargs)
    monkeypatch.setattr(module, "run_blocking", blocking)
    monkeypatch.setattr(module, "read_resource_state", AsyncMock(side_effect=lambda scope: deepcopy(state)))
    monkeypatch.setattr(module, "_models", lambda tenant: deepcopy(models))
    monkeypatch.setattr(module, "_tools", AsyncMock(return_value=tools))
    monkeypatch.setattr(module, "_catalog", lambda *args: deepcopy(catalog))
    monkeypatch.setattr(module, "_saved", lambda scope: {})
    monkeypatch.setattr(module.semantic, "resolve_model", AsyncMock(return_value=None))
    request = module.KnowledgeRecommendationsRequest(agent_id=1, conversation_id=2, card_id="card", state_version=3)
    return module, ResourceScope("tenant", "user", 1, "2", ""), request, state, models, catalog


@pytest.mark.asyncio
async def test_text_defaults_are_private_and_do_not_change_state(context):
    module, scope, request, state, _, _ = context
    before = deepcopy(state)
    result = await module.recommend(scope, request)
    item = result["resources"][0]
    assert item["selected_values"] == ["expense"]
    assert item["selection_source"] == "recommended"
    assert item["recommendations"][0]["name"] == "员工报销政策"
    assert state == before


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"embedding_model_id": 99}, {"document_count": 0}, {"is_multimodal": True}, {"embedding_model_id": None}])
async def test_ineligible_knowledge_is_never_embedded_or_recommended(context, change, monkeypatch):
    module, scope, request, _, _, catalog = context
    catalog[0].update(change)
    retrieve = AsyncMock()
    monkeypatch.setattr(module.semantic, "retrieve", retrieve)
    result = await module.recommend(scope, request)
    assert result["resources"][0]["recommendations"] == []
    retrieve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [[], ["expense"]])
async def test_saved_selection_and_retrieval_settings_win_over_defaults(context, monkeypatch, values):
    module, scope, request, _, _, _ = context
    monkeypatch.setattr(module, "_saved", lambda scope: {"tool:7": {"index_names": values, "top_k": 8}})
    item = (await module.recommend(scope, request))["resources"][0]
    assert item["selected_values"] == values
    assert item["selection_source"] == "saved"
    assert item["settings"]["top_k"] == 8


@pytest.mark.asyncio
async def test_semantic_synonyms_and_embedding_failure_fallback(context, monkeypatch):
    module, scope, request, _, _, catalog = context
    monkeypatch.setattr(module.semantic, "resolve_model", AsyncMock(return_value=(object(), "model", 2)))
    catalog[0]["name"] = "差旅财务制度"
    monkeypatch.setattr(module.semantic, "retrieve", AsyncMock(return_value={"r1": {"installed": [(.9, {"candidate_ref": "knowledge:knowledge_base_search:1"})]}}))
    item = (await module.recommend(scope, request))["resources"][0]
    assert item["selected_values"] == ["expense"] and item["mode"] == "hybrid"
    catalog[0]["name"] = "员工报销政策"
    module.semantic.retrieve.side_effect = TimeoutError("embedding unavailable")
    item = (await module.recommend(scope, request))["resources"][0]
    assert item["mode"] == "fallback" and item["selected_values"] == ["expense"]


@pytest.mark.asyncio
async def test_stale_card_and_model_changes_are_rejected(context, monkeypatch):
    module, scope, request, state, models, _ = context
    state["version"] += 1
    with pytest.raises(ResourceStateError, match="resource_card_stale"):
        await module.recommend(scope, request)
    state["version"] -= 1
    original = deepcopy(models)
    calls = iter([original, {**original, "embedding": {"model_id": 99}}])
    monkeypatch.setattr(module, "_models", lambda tenant: next(calls))
    with pytest.raises(ResourceStateError, match="knowledge_model_changed"):
        await module.recommend(scope, request)


@pytest.mark.asyncio
async def test_revoked_or_updated_metadata_is_not_disclosed(context, monkeypatch):
    module, scope, request, _, _, catalog = context
    calls = iter([deepcopy(catalog), []])
    monkeypatch.setattr(module, "_catalog", lambda *args: next(calls))
    assert (await module.recommend(scope, request))["resources"][0]["recommendations"] == []


@pytest.mark.asyncio
async def test_tool_permission_revoked_during_matching_is_rejected(context, monkeypatch):
    module, scope, request, _, _, _ = context
    original = await module._tools(scope)
    monkeypatch.setattr(module, "_tools", AsyncMock(side_effect=[original, []]))
    with pytest.raises(ResourceStateError, match="resource_not_visible"):
        await module.recommend(scope, request)


def test_native_catalog_only_requests_counts_for_authorized_names(monkeypatch):
    module = importlib.import_module("services.nl2agent_knowledge_recommendations")
    scope = ResourceScope("tenant", "user", 1, "2", "")
    from unittest.mock import Mock
    visible = [{"id": "1", "binding_value": "allowed", "name": "Policy"}]
    loader = Mock(return_value=visible)
    counts = Mock(return_value={"allowed": {"base_info": {"doc_count": 2}}, "private": {"base_info": {"doc_count": 9}}})
    monkeypatch.setattr(module, "load_visible_knowledge", loader)
    monkeypatch.setattr("management.services.knowledge_base.common.get_vector_db_core", lambda: type("Core", (), {"get_indices_detail": staticmethod(counts)})())
    result = module._catalog("knowledge_base_search", scope)
    assert result == [{**visible[0], "document_count": 2}]
    counts.assert_called_once_with(["allowed"])
    loader.assert_called_once_with("knowledge_base_search", user_id="user", tenant_id="tenant")


def test_recommendation_request_rejects_client_queries_and_model_overrides():
    from pydantic import ValidationError
    from contracts.nl2agent_resources import KnowledgeRecommendationsRequest
    with pytest.raises(ValidationError):
        KnowledgeRecommendationsRequest(agent_id=1, conversation_id=2, card_id="card", state_version=1,
                                        queries=["untrusted"], embedding_model_id=99)


@pytest.mark.asyncio
async def test_catalog_failure_does_not_become_an_empty_recommendation(context, monkeypatch):
    module, scope, request, _, _, _ = context
    def unavailable(*args):
        raise TimeoutError("catalog unavailable")
    monkeypatch.setattr(module, "_catalog", unavailable)
    with pytest.raises(ResourceStateError, match="knowledge_recommendations_unavailable"):
        await module.recommend(scope, request)


@pytest.mark.asyncio
async def test_knowledge_ranking_receives_content_not_tool_capability(context, monkeypatch):
    module, scope, request, state, _, _ = context
    original = "检索知识库中已有的临床指南和院内资料"
    state["requirements"]["r1"].update(query=original,
        search_queries={"zh": "知识库检索", "en": "knowledge base search"})
    calls = []
    rank = module.rank_knowledge
    def capture(rows, queries, *args, **kwargs):
        calls.append(queries)
        return rank(rows, queries, *args, **kwargs)
    monkeypatch.setattr(module, "rank_knowledge", capture)
    await module.recommend(scope, request)
    assert calls == [[original]]
