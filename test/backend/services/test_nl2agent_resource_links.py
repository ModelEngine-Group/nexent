# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Link only visible, verified installations to the current resource card."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from contracts.nl2agent_resources import (
    MAX_REQUIREMENTS,
    RequirementEdit,
    ResourceCardAction,
    ResourceLinkRequest,
)
from nexent.core import concurrency
from services import nl2agent_resource_flow as flow
from services.nl2agent_state_service import ResourceScope, ResourceStateError


@pytest.fixture
def boundary(mocker):
    scope = ResourceScope("tenant", "user", 42, "7", "run")
    state = {"conversation_id": "7", "run_id": "run", "version": 2, "purpose": "generate",
             "card": {"id": "card", "subtype": "requirement_coverage"},
             "requirements": {"r1": {"query": "Weather"}}}
    candidate = {"candidate_ref": "tenant_skill_repository:3", "resource_type": "skill",
                 "source": "TENANT_SKILL_REPOSITORY", "name": "Weather"}
    mocker.patch.object(flow, "read_resource_state", new=AsyncMock(side_effect=lambda _: deepcopy(state)))
    mocker.patch.object(flow, "coverage_rows", side_effect=lambda _: [{
        "requirement_id": "r1", "installable_resources": [candidate],
    }])
    catalog = mocker.patch.object(flow.legacy, "_load_installed_resource_catalog", new=AsyncMock(return_value=[
        {"candidate_ref": "skill:9"},
    ]))
    lookup = mocker.patch.object(flow, "_lookup_installation", return_value={"resource_type": "skill", "resource_id": 9})

    async def run(_task, function, *args, **kwargs):
        return function(*args)

    mocker.patch.object(concurrency, "run_blocking", new=run)

    async def update(_scope, change):
        next_state = change(deepcopy(state))
        state.clear()
        state.update(next_state)
        return deepcopy(state)

    write = mocker.patch.object(flow, "update_resource_state", new=AsyncMock(side_effect=update))
    return scope, state, candidate, catalog, lookup, write


def request(**kwargs):
    return ResourceLinkRequest.model_validate({"agent_id": 42, "conversation_id": 7, "card_id": "card",
        "state_version": 2, "requirement_id": "r1", "resource_type": "skill", "resource_id": 9, **kwargs})


@pytest.mark.asyncio
async def test_manual_link_is_deduplicated_and_requires_verification(boundary):
    scope, state, _, catalog, lookup, _ = boundary
    for _ in range(2):
        await flow.link_installed_resource(scope, request())
    assert state["requirements"]["r1"] == {"query": "Weather", "linked_refs": ["skill:9"], "needs_link_verification": True}
    lookup.assert_not_called()
    catalog.assert_awaited_with(tenant_id="tenant", user_id="user")


@pytest.mark.asyncio
async def test_new_requirement_link_uses_bounded_pending_bucket(boundary):
    scope, state, _, _, _, _ = boundary
    state["pending_links"] = {f"new-{i}": ["skill:9"] for i in range(MAX_REQUIREMENTS)}
    await flow.link_installed_resource(scope, request(requirement_id=None, client_key="new-0"))
    assert state["pending_links"]["new-0"] == ["skill:9"]
    with pytest.raises(ResourceStateError, match="requirements_limit_exceeded"):
        await flow.link_installed_resource(scope, request(requirement_id=None, client_key="overflow"))
    assert len(state["pending_links"]) == MAX_REQUIREMENTS


@pytest.mark.asyncio
@pytest.mark.parametrize("change,code", [
    ("card", "resource_card_stale"), ("requirement", "unknown_requirement"),
    ("type", "invalid_resource_link"), ("attempt", "invalid_resource_link"),
    ("missing", "installed_resource_not_visible"), ("id", "invalid_resource_link"),
    ("catalog", "installed_resource_not_visible"),
])
async def test_invalid_links_never_write(boundary, change, code):
    scope, state, candidate, catalog, lookup, write = boundary
    state["installation_attempts"] = {candidate["candidate_ref"]: {"target_name": "target", "attempt_id": "attempt"}}
    values = {"candidate_ref": candidate["candidate_ref"]}
    if change == "card":
        state["card"]["subtype"] = "installed_resource_binding"
    elif change == "requirement":
        values["requirement_id"] = "unknown"
    elif change == "type":
        candidate["resource_type"] = "mcp_server"
    elif change == "attempt":
        state.pop("installation_attempts")
    elif change == "missing":
        lookup.return_value = None
    elif change == "id":
        lookup.return_value = {"resource_type": "skill", "resource_id": 10}
    else:
        catalog.return_value = []
    with pytest.raises(ResourceStateError, match=code) as error:
        await flow.link_installed_resource(scope, request(**values))
    assert error.value.retryable is (code == "installed_resource_not_visible")
    write.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("official", [False, True])
async def test_recommendation_link_checks_actual_installation_before_visibility(boundary, official):
    scope, state, candidate, _, lookup, _ = boundary
    if official:
        candidate["source"] = "NEXENT_OFFICIAL_SKILL"
    else:
        state["installation_attempts"] = {candidate["candidate_ref"]: {"target_name": "reserved"}}
    await flow.link_installed_resource(scope, request(candidate_ref=candidate["candidate_ref"]))
    lookup.assert_called_once_with(scope, candidate, "Weather" if official else "reserved")
    assert state["requirements"]["r1"]["linked_refs"] == ["skill:9"]


@pytest.mark.asyncio
async def test_card_is_revalidated_at_atomic_link_write(boundary):
    scope, state, _, catalog, _, _ = boundary

    async def load(**kwargs):
        state["version"] = 3
        return [{"candidate_ref": "skill:9"}]

    catalog.side_effect = load
    with pytest.raises(ResourceStateError, match="resource_card_stale"):
        await flow.link_installed_resource(scope, request())
    assert "linked_refs" not in state["requirements"]["r1"]


@pytest.mark.parametrize("target", [{}, {"requirement_id": "r1", "client_key": "new"}])
def test_requirement_edit_requires_exactly_one_identifier(target):
    with pytest.raises(ValidationError, match="Exactly one"):
        RequirementEdit(query="Weather", **target)


@pytest.mark.parametrize("values", [
    {"requirements": [{"requirement_id": "r1", "query": "A"}, {"requirement_id": "r1", "query": "B"}]},
    {"selected_resource_refs": ["skill:9", "skill:9"]},
])
def test_card_actions_reject_duplicate_references(values):
    with pytest.raises(ValidationError, match="Duplicate"):
        ResourceCardAction(card_id="card", state_version=2, **values)


@pytest.mark.parametrize("values", [
    {"requirement_id": None}, {"client_key": "new"},
    {"requirement_id": None, "client_key": "new", "candidate_ref": "skill:9"},
])
def test_link_requires_unambiguous_target_and_confirmed_recommendation(values):
    with pytest.raises(ValidationError):
        request(**values)
