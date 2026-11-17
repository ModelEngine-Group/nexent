# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Knowledge resource recommendations use scores and the authorized resource catalog."""

from unittest.mock import AsyncMock

import pytest

from contracts.nl2agent_resources import VerificationCheck
from services import nl2agent_service as legacy
from services import nl2agent_resource_flow as flow
from services.nl2agent_state_service import ResourceScope, ResourceStateError


def tool(ref, name, description="opaque"):
    return {"candidate_ref": ref, "name": name, "names": [name], "description": description,
            "descriptions": [description], "labels": [], "interfaces": [], "installed": True,
            "resource_type": "tool", "source": "LOCAL_TOOL", "config": [], "quality": 1.0}


@pytest.fixture
def setup_policy(monkeypatch):
    async def blocking(task, fn, *args, **kwargs):
        kwargs.pop("lane", None)
        kwargs.pop("owner", None)
        return fn(*args, **kwargs)
    monkeypatch.setattr(legacy, "run_blocking", blocking)
    monkeypatch.setattr(legacy, "query_all_enabled_tool_instances", lambda **kw: [])
    monkeypatch.setattr(legacy, "query_enabled_skill_instances", lambda **kw: [])
    monkeypatch.setattr(legacy, "load_visible_knowledge", lambda *a, **kw: [
        {"binding_value": "private-index", "name": "private-name"},
    ])
    monkeypatch.setattr(legacy, "ENABLE_AIDP_KNOWLEDGE", False)
    return ResourceScope("tenant", "user", 1, "2", "run")


def test_post_verification_order_keeps_scores_alternatives_and_rejection(setup_policy):
    candidates = [flow._candidate(tool("tool:1", "datamate_search"), .99),
                  flow._candidate(tool("tool:2", "knowledge_base_search"), .1),
                  flow._candidate(tool("tool:3", "other"), .6)]
    row = {"query": "知识库", "installed": candidates, "accepted": ["tool:1", "tool:2", "tool:3"],
           "knowledge_validation": {"tool_name": "knowledge_base_search", "status": "configurable", "ready_refs": []}}
    state = {"requirements": {"r": row}}
    ordered = flow.coverage_rows(state)[0]["covered_resources"]
    assert [item["candidate_ref"] for item in ordered] == ["tool:1", "tool:3", "tool:2"]
    assert ordered[-1]["retrieval_score"] == .1
    row["knowledge_validation"]["ready_refs"] = ["tool:2"]
    row["knowledge_preference"] = {"tool_name": "knowledge_base_search", "status": "configurable"}
    row["source_preference"] = ["tool:2"]
    assert flow.coverage_rows(state)[0]["covered_resources"] == ordered
    row["accepted"] = ["tool:1", "tool:3"]
    assert [item["candidate_ref"] for item in flow.coverage_rows(state)[0]["covered_resources"]] == ["tool:1", "tool:3"]


def test_equal_scores_use_stable_reference_order(setup_policy):
    candidates = [flow._candidate(tool("tool:2", "knowledge_base_search"), .9),
                  flow._candidate(tool("tool:1", "datamate_search"), .9)]
    row = {"query": "knowledge", "installed": candidates, "accepted": ["tool:1", "tool:2"]}
    assert [item["candidate_ref"] for item in flow.coverage_rows({"requirements": {"r": row}})[0]["covered_resources"]] == [
        "tool:1", "tool:2",
    ]


def test_native_bonus_is_small_and_uses_resource_identity(setup_policy, monkeypatch):
    from tool_collection.mcp.nl2agent_mcp_tools import ResourceRequirement

    requirement = ResourceRequirement(requirement_id="r", query="retrieve documents")
    monkeypatch.setattr(legacy, "_resource_similarity",
                        lambda query, value: .8 if value == "retrieve documents" else .2)
    native = tool("tool:2", "knowledge_base_search", "retrieve documents")
    alternative = {**native, "name": "other", "names": ["other"]}
    native_score = legacy._score_resource_requirement(requirement, native)
    other_score = legacy._score_resource_requirement(requirement, alternative)
    assert native_score - other_score == pytest.approx(.02)
    native["descriptions"] = ["opaque"]
    assert legacy._score_resource_requirement(requirement, native) < other_score


@pytest.mark.asyncio
async def test_card_rechecks_visibility_before_recommending(setup_policy, monkeypatch):
    candidate = flow._candidate(tool("tool:2", "knowledge_base_search"), .1)
    state = {"conversation_id": "2", "run_id": "run", "version": 1, "card": None, "batch": None,
             "requirements": {"r": {"query": "知识库", "installed": [candidate], "accepted": ["tool:2"],
                 "knowledge_validation": {"tool_name": "knowledge_base_search", "status": "configurable", "ready_refs": []}}}}
    monkeypatch.setattr(flow, "read_resource_state", AsyncMock(return_value=state))
    monkeypatch.setattr(flow.legacy, "_load_installed_resource_catalog", AsyncMock(return_value=[]))
    publish = AsyncMock()
    monkeypatch.setattr(flow, "update_resource_state", publish)
    with pytest.raises(ResourceStateError, match="resource_evidence_changed") as error:
        await flow.show_card(setup_policy)
    assert error.value.retryable
    publish.assert_not_called()


@pytest.mark.asyncio
async def test_later_rejected_batch_preserves_earlier_native_coverage(setup_policy, monkeypatch):
    catalog = [tool("tool:2", "knowledge_base_search")]
    catalog.extend(tool(f"tool:{index}", f"other_{index}") for index in range(10, 16))
    candidates = [flow._candidate(item, .1) for item in catalog]
    state = {"conversation_id": "2", "run_id": "run", "version": 1, "card": None,
             "batch": {"id": "first", "requirements": ["r"]}, "requirements": {"r": {
                 "query": "知识库", "installed": candidates, "installable": [],
                 "knowledge_validation": {"tool_name": "knowledge_base_search", "status": "configurable", "ready_refs": []},
             }}}
    async def update(scope, change):
        state.update(change(state))
        return state
    monkeypatch.setattr(flow, "read_resource_state", AsyncMock(side_effect=lambda scope: state))
    monkeypatch.setattr(flow, "update_resource_state", update)
    monkeypatch.setattr(flow.legacy, "_load_installed_resource_catalog", AsyncMock(return_value=catalog))
    await flow.verify(setup_policy, "first", [VerificationCheck(requirement_id="r", accepted=["tool:2"])])
    assert state["requirements"]["r"]["verification_offset"] == 6
    result = await flow.verify(setup_policy, state["batch"]["id"], [VerificationCheck(requirement_id="r", accepted=[])])
    assert result["verification_batch_id"] is None
    assert result["requirements"][0]["covered_resources"] == [candidates[0]]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["text", "hybrid", "fallback"])
async def test_discovery_does_not_add_low_score_native_in_any_route(setup_policy, monkeypatch, mode):
    catalog = [tool("tool:1", "datamate_search", "知识库检索"), tool("tool:2", "knowledge_base_search")]
    state = {"conversation_id": "2", "run_id": "run", "version": 1, "card": None, "batch": None,
             "purpose": "recommend", "requirements": {"r": {"query": "知识库检索", "search_queries": {"zh": "知识库检索", "en": "corporate archive"}}}}
    async def update(scope, change):
        state.update(change(state))
        return state
    monkeypatch.setattr(flow, "read_resource_state", AsyncMock(side_effect=lambda scope: state))
    monkeypatch.setattr(flow, "update_resource_state", update)
    monkeypatch.setattr(flow, "_progress", AsyncMock())
    monkeypatch.setattr(flow.legacy, "_load_installed_resource_catalog", AsyncMock(return_value=catalog))
    monkeypatch.setattr(flow.legacy, "_load_internal_uninstalled_resource_catalog", AsyncMock(return_value=[]))
    monkeypatch.setattr(flow.semantic, "resolve_model", AsyncMock(return_value=None if mode == "text" else object()))
    monkeypatch.setattr(flow.semantic, "retrieve", AsyncMock(
        side_effect=TimeoutError() if mode == "fallback" else None,
        return_value={"r": {"installed": [], "installable": []}},
    ))
    result = await flow.discover(setup_policy, None, "recommend")
    refs = [item["candidate_ref"] for item in result["requirements"][0]["installed_candidates"]]
    assert "tool:2" not in refs
    checks = [VerificationCheck(requirement_id="r", accepted=refs, assessments=[
        {"candidate_ref": ref, "satisfies": True, "reason": "Meets the knowledge retrieval requirement."}
        for ref in refs])]
    await flow.verify(setup_policy, result["verification_batch_id"], checks)
    assert flow.coverage_rows(state)[0]["covered_resources"][0]["name"] == "datamate_search"
