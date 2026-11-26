# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unified resource cards reuse evidence without conflating gaps and binding readiness."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from contracts.nl2agent_resources import ResourceCardAction, RequirementEdit
from services import nl2agent_resource_flow as flow
from services.nl2agent_state_service import ResourceScope, ResourceStateError


@pytest.fixture
def scope():
    return ResourceScope("tenant", "user", 1, "conversation", "run")


def state():
    candidate = {"candidate_ref": "tool:1", "resource_type": "tool", "source": "LOCAL_TOOL",
                 "name": "Search", "description": "Search public websites", "retrieval_score": 0.9}
    return {"version": 2, "run_id": "run", "conversation_id": "conversation", "purpose": "generate",
            "card": None, "batch": None, "requirements": {
                "r1": {"query": "Search websites", "search_queries": {"zh": "联网搜索", "en": "web search"},
                       "installed": [candidate], "installable": [], "accepted": ["tool:1"]},
                "r2": {"query": "Send mail", "search_queries": {"zh": "发送邮件", "en": "send email"},
                       "installed": [], "installable": [], "accepted": []},
            }}


def storage(monkeypatch, initial):
    current = deepcopy(initial)

    async def read(_):
        return deepcopy(current)

    async def update(_, change):
        nonlocal current
        current = change(deepcopy(current))
        return deepcopy(current)

    monkeypatch.setattr(flow, "read_resource_state", read)
    monkeypatch.setattr(flow, "update_resource_state", update)
    return read


@pytest.mark.asyncio
async def test_unified_card_includes_bindable_resources_despite_gap(monkeypatch, scope):
    storage(monkeypatch, state())
    async def authorized(*args, **kwargs):
        if "catalogs" in kwargs:
            kwargs["catalogs"]["installed"] = []
        return {}
    monkeypatch.setattr(flow, "_authorized_batch_result", authorized)
    monkeypatch.setattr(flow, "_repository_mcp_installation_status", AsyncMock(return_value={}))
    monkeypatch.setattr(flow.legacy, "recommend_installed_resources_impl", AsyncMock(return_value=type(
        "Result", (), {"resources": []})()))
    card = await flow.show_card(scope)
    assert card["subtype"] == "requirement_resources"
    assert card["purpose"] == "generate"
    assert card["requirements"][0]["search_queries"]["en"] == "web search"
    assert card["requirements"][1]["coverage_status"] == "uncovered"
    assert "resources" in card
    flow.legacy.recommend_installed_resources_impl.assert_awaited_once()


def test_modified_query_invalidates_only_its_derived_queries_and_evidence():
    initial = state()
    updated = flow.apply_requirement_edits(initial, [
        RequirementEdit(requirement_id="r1", query="Search websites"),
        RequirementEdit(requirement_id="r2", query="Send email with attachments"),
    ])
    assert updated["requirements"]["r1"] == {**initial["requirements"]["r1"], "required": True}
    assert updated["requirements"]["r2"] == {"query": "Send email with attachments", "required": True}


@pytest.mark.asyncio
async def test_unified_edit_is_accepted_before_model_reprepares_only_changed_query(monkeypatch, scope):
    initial = state()
    initial["card"] = {"id": "card", "subtype": "requirement_resources"}
    read = storage(monkeypatch, initial)
    result = await flow.apply_card_action(scope, "requirement_resources", "confirm_requirements", ResourceCardAction(
        card_id="card", state_version=2, requirements=[
            RequirementEdit(requirement_id="r1", query="Search websites"),
            RequirementEdit(requirement_id="r2", query="Send email with attachments"),
        ]))
    assert result["next_step"] == "verify_resources"
    discover = await flow.discover(scope, None, "generate")
    assert discover == {"status": "success", "next_step": "prepare_search_queries", "requirements": [
        {"requirement_id": "r2", "query": "Send email with attachments"}]}
    assert (await read(scope))["requirements"]["r1"]["accepted"] == ["tool:1"]


@pytest.mark.asyncio
async def test_unified_continue_rejects_gap_without_consuming_card(monkeypatch, scope):
    initial = state()
    initial["card"] = {"id": "card", "subtype": "requirement_resources"}
    read = storage(monkeypatch, initial)
    monkeypatch.setattr(flow, "_authorized_batch_result", AsyncMock(return_value={}))
    monkeypatch.setattr(flow.legacy, "_load_verified_nl2agent_state", AsyncMock(return_value=(
        {}, [{"resource_type": "tool", "resource_id": 1}])) )
    with pytest.raises(ResourceStateError, match="required_resource_not_bound"):
        await flow.apply_card_action(scope, "requirement_resources", "continue", ResourceCardAction(
            card_id="card", state_version=2, selected_resource_refs=["tool:1"]))
    assert (await read(scope))["card"] == initial["card"]


@pytest.mark.asyncio
async def test_recommendation_cannot_continue_or_install_without_explicit_use(monkeypatch, scope):
    initial = state()
    initial["purpose"] = "recommend"
    initial["card"] = {"id": "card", "subtype": "requirement_resources"}
    read = storage(monkeypatch, initial)
    with pytest.raises(ResourceStateError, match="invalid_resource_action"):
        await flow.apply_card_action(scope, "requirement_resources", "continue", ResourceCardAction(
            card_id="card", state_version=2, selected_resource_refs=[]))
    assert (await read(scope))["purpose"] == "recommend"


@pytest.mark.asyncio
async def test_legacy_resource_action_requires_new_search(monkeypatch, scope):
    initial = state()
    initial["card"] = {"id": "card", "subtype": "installed_resource_binding"}
    storage(monkeypatch, initial)
    with pytest.raises(ResourceStateError, match="resource_card_stale"):
        await flow.apply_card_action(scope, "installed_resource_binding", "continue", ResourceCardAction(
            card_id="card", state_version=2, selected_resource_refs=[]))


@pytest.mark.asyncio
@pytest.mark.parametrize("values,expected", [({}, "not_ready"), ({"token": "private-token"}, "ready")])
async def test_bound_skill_readiness_is_safe_and_separate_from_binding(monkeypatch, values, expected):
    from management.services.agent.nl2agent_tools import ResourceCandidate

    catalog = [{"candidate_ref": "skill:2", "resource_type": "skill", "source": "INSTALLED_SKILL",
                "name": "Summary", "description": "Summarize documents",
                "config": [{"name": "token", "type": "string", "required": True}]}]
    monkeypatch.setattr(flow.legacy, "require_agent_draft_edit", lambda **kwargs: {})
    monkeypatch.setattr(flow.legacy, "query_all_enabled_tool_instances", lambda **kwargs: [])
    monkeypatch.setattr(flow.legacy, "query_enabled_skill_instances", lambda **kwargs: [
        {"skill_id": 2, "config_values": values}])
    facts = {}
    await flow.legacy.recommend_installed_resources_impl(
        agent_id=1, tenant_id="tenant", user_id="user", catalog=catalog,
        candidates=[ResourceCandidate(candidate_ref="skill:2", resource_type="skill", source="INSTALLED_SKILL",
                                      name="Summary", description="Summarize documents", requirement_ids=["r1"], score=0.9)],
        recommended_refs=["skill:2"], include_knowledge_recommendations=False, binding_facts=facts)
    assert facts == {"skill:2": {"is_bound": True, "readiness": expected}}
    assert "private-token" not in str(facts)


@pytest.mark.asyncio
async def test_preflight_validates_without_accepting_edits_before_history_admission(monkeypatch, scope):
    initial = state()
    initial["card"] = {"id": "card", "subtype": "requirement_resources"}
    read = storage(monkeypatch, initial)
    before = await read(scope)
    result = await flow.apply_card_action(
        scope, "requirement_resources", "confirm_requirements",
        ResourceCardAction(card_id="card", state_version=2, requirements=[
            RequirementEdit(requirement_id="r1", query="Search official websites")]), validate_only=True)
    assert result == {"validated": True}
    assert await read(scope) == before
