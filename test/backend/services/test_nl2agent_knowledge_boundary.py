# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resource recommendations must not depend on knowledge configuration providers."""

from unittest.mock import AsyncMock, Mock

import pytest

from contracts.nl2agent_resources import VerificationCheck
from services import nl2agent_resource_flow as flow
from services import nl2agent_service as legacy
from services.nl2agent_state_service import ResourceScope


@pytest.mark.asyncio
@pytest.mark.parametrize("aidp", [False, True])
@pytest.mark.parametrize("provider_failure", [False, True])
async def test_recall_verification_and_binding_card_do_not_query_knowledge(monkeypatch, aidp, provider_failure):
    name = "aidp_search" if aidp else "knowledge_base_search"
    scope = ResourceScope("tenant", "user", 1, "2", "run")
    resource = {
        "candidate_ref": "tool:2", "resource_type": "tool", "source": "LOCAL_TOOL", "name": name,
        "names": [name], "description": "知识库检索", "descriptions": ["知识库检索"], "labels": [],
        "interfaces": [], "inputs": {}, "config": [], "form_kind": "TOOL_CONFIG", "installed": True, "quality": 1,
    }
    state = {
        "conversation_id": "2", "run_id": "run", "version": 1, "card": None, "batch": None, "purpose": "bind",
        "requirements": {"r1": {"query": "知识库检索", "search_queries": {"zh": "知识库检索", "en": "search knowledge"}}},
    }

    async def update(_scope, change):
        state.update(change(state))
        return state

    provider = Mock(side_effect=ConnectionError("provider unavailable") if provider_failure else None, return_value=[])
    monkeypatch.setattr(legacy, "ENABLE_AIDP_KNOWLEDGE", aidp)
    monkeypatch.setattr(legacy, "load_visible_knowledge", provider)
    monkeypatch.setattr(legacy, "_load_installed_resource_catalog", AsyncMock(return_value=[resource]))
    monkeypatch.setattr(legacy, "_load_internal_uninstalled_resource_catalog", AsyncMock(return_value=[]))
    monkeypatch.setattr(legacy, "query_all_enabled_tool_instances", lambda **kwargs: [])
    monkeypatch.setattr(legacy, "query_enabled_skill_instances", lambda **kwargs: [])
    monkeypatch.setattr(flow, "read_resource_state", AsyncMock(side_effect=lambda _: state))
    monkeypatch.setattr(flow, "update_resource_state", update)
    monkeypatch.setattr(flow, "_progress", AsyncMock())
    monkeypatch.setattr(flow.semantic, "resolve_model", AsyncMock(return_value=None))
    result = await flow.discover(scope, None, "bind")
    assert [item["candidate_ref"] for item in result["requirements"][0]["installed_candidates"]] == ["tool:2"]
    await flow.verify(scope, result["verification_batch_id"], [VerificationCheck(
        requirement_id="r1", accepted=["tool:2"], assessments=[
            {"candidate_ref": "tool:2", "satisfies": True, "reason": "Declares knowledge retrieval"},
        ],
    )])
    card = await flow.show_card(scope)
    assert card["subtype"] == "installed_resource_binding"
    assert card["requirements"][0]["coverage_status"] == "covered"
    assert card["resources"][0]["candidate"]["candidate_ref"] == "tool:2"
    assert not card["resources"][0]["is_bound"]
    assert card["resources"][0]["knowledge_recommendations"] == []
    assert "knowledge_status" not in card["requirements"][0]
    provider.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("name,field", [("knowledge_base_search", "index_names"), ("aidp_search", "kds_list")])
@pytest.mark.parametrize("configured,selected,ready", [(True, True, True), (False, True, False), (True, False, False)])
async def test_binding_summary_uses_saved_configuration_without_provider(monkeypatch, name, field, configured, selected, ready):
    from tool_collection.mcp.nl2agent_mcp_tools import ResourceCandidate

    resource = {
        "candidate_ref": "tool:2", "resource_type": "tool", "source": "LOCAL_TOOL", "name": name,
        "names": [name], "description": "Search knowledge", "inputs": {},
        "config": [{"name": "endpoint", "type": "string", "required": True}],
    }
    params = {**({"endpoint": "configured"} if configured else {}), **({field: ["saved"]} if selected else {})}
    monkeypatch.setattr(legacy, "_load_installed_resource_catalog", AsyncMock(return_value=[resource]))
    monkeypatch.setattr(legacy, "query_all_enabled_tool_instances", lambda **kwargs: [{"tool_id": 2, "params": params}])
    provider = Mock(side_effect=ConnectionError("must not be called during resource recommendation"))
    monkeypatch.setattr(legacy, "load_visible_knowledge", provider)
    result = await legacy.recommend_installed_resources_impl(
        agent_id=1, candidates=[ResourceCandidate(candidate_ref="tool:2", resource_type="tool", source="LOCAL_TOOL",
                                                name=name, score=.9, requirement_ids=["r1"])],
        recommended_refs=["tool:2"], tenant_id="tenant", user_id="user", include_knowledge_recommendations=False,
    )
    assert result.resources[0].is_bound is ready
    assert result.resources[0].knowledge_recommendations == []
    monkeypatch.setattr(legacy, "require_agent_draft_edit", lambda **kwargs: {"prompt": "Saved prompt"})
    monkeypatch.setattr(legacy, "query_enabled_skill_instances", lambda **kwargs: [])
    _, facts = await legacy._load_verified_nl2agent_state(agent_id=1, tenant_id="tenant", user_id="user")
    assert bool(facts) is ready
    provider.assert_not_called()
