# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Card actions require actual bindings and exact continuation receipts."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from contracts.nl2agent_resources import RequirementEdit, ResourceCardAction
from services import nl2agent_resource_flow as flow
from services.nl2agent_state_service import ResourceScope, ResourceStateError


@pytest.fixture
def boundary(mocker):
    scope = ResourceScope("tenant", "user", 42, "7", "next")
    state = {"conversation_id": "7", "run_id": "previous", "version": 2, "purpose": "generate",
             "card": {"id": "card", "subtype": "installed_resource_binding"}, "requirements": {}}
    mocker.patch.object(flow, "read_resource_state", new=AsyncMock(side_effect=lambda _: deepcopy(state)))

    async def update(_scope, change):
        result = change(deepcopy(state))
        state.clear()
        state.update(result)
        return deepcopy(state)

    write = mocker.patch.object(flow, "update_resource_state", new=AsyncMock(side_effect=update))
    rows = [{"requirement_id": "r1", "query": "Weather", "required": True,
             "covered_resources": [{"candidate_ref": "tool:9"}]}]
    mocker.patch.object(flow, "coverage_rows", return_value=rows)
    bound = mocker.patch.object(flow.legacy, "_load_verified_nl2agent_state", new=AsyncMock(return_value=(
        {}, [{"resource_type": "tool", "resource_id": 9}],
    )))
    return scope, state, rows, bound, write


def action(**kwargs):
    return ResourceCardAction(card_id="card", state_version=2, **kwargs)


@pytest.mark.asyncio
async def test_continue_records_verified_requirements_and_retry_receipt(boundary):
    scope, state, _, bound, _ = boundary
    result = await flow.apply_card_action(scope, "installed_resource_binding", "continue",
                                          action(selected_resource_refs=["tool:9"]))
    assert result == {"purpose": "generate", "action": "continue", "confirmed_requirements": [
        {"query": "Weather", "required": True, "bound": True},
    ]}
    assert state["card"] is None and state["version"] == 3 and state["run_id"] == "next"
    assert state["continuation"] == {"id": "card", "version": 2}
    bound.assert_awaited_once_with(agent_id=42, tenant_id="tenant", user_id="user")
    retry = await flow.apply_card_action(scope, "installed_resource_binding", "retry_generation", action())
    assert retry == {**result, "retry_prompt": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("case,code", [
    ("missing", "invalid_resource_action"), ("unknown", "binding_not_ready"),
    ("unbound", "binding_not_ready"), ("required", "required_resource_not_bound"),
])
async def test_continue_rejects_missing_or_forged_bindings(boundary, case, code):
    scope, state, rows, bound, write = boundary
    selected = None if case == "missing" else ["tool:99"] if case == "unknown" else ["tool:9"]
    if case == "unbound":
        bound.return_value = ({}, [])
    if case == "required":
        rows.append({"query": "Email", "required": True, "covered_resources": [{"candidate_ref": "tool:10"}]})
    with pytest.raises(ResourceStateError, match=code):
        await flow.apply_card_action(scope, "installed_resource_binding", "continue", action(selected_resource_refs=selected))
    write.assert_not_awaited()
    assert state["card"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no_state", "conversation", "card", "receipt"])
async def test_generation_retry_rejects_stale_continuations(boundary, case):
    scope, state, _, _, _ = boundary
    state.update(card=None, continuation={"id": "card", "version": 2})
    if case == "no_state":
        state.clear()
    elif case == "conversation":
        state["conversation_id"] = "other"
    elif case == "card":
        state["card"] = {"id": "new", "subtype": "requirement_coverage"}
    else:
        state["continuation"]["version"] = 1
    before = deepcopy(state)
    with pytest.raises(ResourceStateError, match="resource_card_stale"):
        await flow.apply_card_action(scope, "installed_resource_binding", "retry_generation", action())
    assert state == before


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose,expected", [
    ("recommend", {"purpose": "recommend", "action": "confirm_requirements"}),
    ("generate", {"purpose": "generate", "action": "confirm_requirements", "confirmed_requirements": [],
                  "next_step": "generate_prompt"}),
])
async def test_confirmed_empty_resources_continue_according_to_original_purpose(mocker, purpose, expected):
    mocker.patch.object(flow, "show_card", new=AsyncMock(return_value=None))
    assert await flow._continue_confirmed_requirements(None, {"purpose": purpose, "requirements": {}},
                                                       "confirm_requirements") == expected


@pytest.mark.asyncio
async def test_using_recommendation_changes_purpose_to_binding(mocker, boundary):
    scope, state, _, _, _ = boundary
    state["purpose"] = "recommend"
    state["card"]["subtype"] = "resource_recommendation"
    show = mocker.patch.object(flow, "show_card", new=AsyncMock(return_value={"subtype": "installed_resource_binding"}))
    assert await flow.apply_card_action(scope, "resource_recommendation", "use_recommendation", action()) == {
        "card": {"subtype": "installed_resource_binding"},
    }
    assert state["purpose"] == "bind" and state["card"] is None and state["version"] == 3
    show.assert_awaited_once_with(scope)


@pytest.mark.asyncio
@pytest.mark.parametrize("subtype", ["requirement_coverage", "resource_recommendation"])
async def test_unsupported_card_action_is_rejected_without_state_change(boundary, subtype):
    scope, state, _, _, _ = boundary
    state["card"]["subtype"] = subtype
    before = deepcopy(state)
    with pytest.raises(ResourceStateError, match="invalid_resource_action"):
        await flow.apply_card_action(scope, subtype, "unknown", action())
    assert state == before


@pytest.mark.asyncio
async def test_confirmation_requires_requirement_edits(boundary):
    scope, state, _, _, _ = boundary
    state["card"]["subtype"] = "requirement_coverage"
    with pytest.raises(ResourceStateError, match="invalid_resource_action"):
        await flow.apply_card_action(scope, "requirement_coverage", "confirm_requirements", action())


def test_unknown_requirement_edit_cannot_create_an_arbitrary_server_id():
    with pytest.raises(ResourceStateError, match="unknown_requirement"):
        flow.apply_requirement_edits({"requirements": {}}, [RequirementEdit(requirement_id="forged", query="Weather")])
