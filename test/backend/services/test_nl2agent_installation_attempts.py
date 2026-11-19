# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Installation claims are scoped, idempotent and recover without repeating writes."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from contracts.nl2agent_resources import (
    ResourceInstallationAttemptRequest,
    ResourceInstallationRequest,
)
from management.db.mcp import remote
from management.db.skill import repository
from management.services.skill import transfer
from nexent.core import concurrency
from services import nl2agent_resource_flow as flow
from services.nl2agent_state_service import ResourceScope, ResourceStateError


@pytest.fixture
def scope():
    return ResourceScope("tenant", "user", 42, "7", "run")


@pytest.mark.parametrize("source,records,expected", [
    ("NEXENT_OFFICIAL_SKILL", [], None),
    ("NEXENT_OFFICIAL_SKILL", [{"name": "target", "status": "available", "skill_id": 1}], None),
    ("NEXENT_OFFICIAL_SKILL", [{"name": "other", "status": "installed", "skill_id": 1}], None),
    ("NEXENT_OFFICIAL_SKILL", [{"name": "target", "status": "installed", "skill_id": 0}], None),
    ("NEXENT_OFFICIAL_SKILL", [{"name": "target", "status": "installed", "skill_id": 3}],
     {"resource_type": "skill", "resource_id": 3}),
    ("TENANT_SKILL_REPOSITORY", None, None),
    ("TENANT_SKILL_REPOSITORY", {"source": "repository", "created_by": "user", "skill_id": 4},
     {"resource_type": "skill", "resource_id": 4}),
    ("TENANT_MCP_REPOSITORY", [], None),
    ("TENANT_MCP_REPOSITORY", [{"mcp_name": "other"}], None),
    ("TENANT_MCP_REPOSITORY", [{"mcp_name": "target", "created_by": "user", "market_id": 3, "mcp_id": 5}],
     {"resource_type": "mcp_server", "resource_id": 5}),
])
def test_lookup_returns_only_matching_owned_installation(mocker, scope, source, records, expected):
    official = mocker.patch.object(transfer, "get_official_skills_with_status", return_value=records)
    skill = mocker.patch.object(repository, "get_skill_by_name", return_value=records)
    mcp = mocker.patch.object(remote, "get_mcp_records_by_tenant", return_value=records)
    assert flow._lookup_installation(scope, {"source": source, "candidate_ref": "tenant_mcp_repository:3"},
                                     "target") == expected
    if source == "NEXENT_OFFICIAL_SKILL":
        official.assert_called_once_with(tenant_id="tenant")
    elif source == "TENANT_SKILL_REPOSITORY":
        skill.assert_called_once_with("target", "tenant")
    else:
        mcp.assert_called_once_with("tenant")


@pytest.mark.parametrize("source,record", [
    ("TENANT_SKILL_REPOSITORY", {"source": "upload", "created_by": "user", "skill_id": 4}),
    ("TENANT_SKILL_REPOSITORY", {"source": "repository", "created_by": "other", "skill_id": 4}),
    ("TENANT_MCP_REPOSITORY", {"mcp_name": "target", "created_by": "other", "market_id": 3}),
    ("TENANT_MCP_REPOSITORY", {"mcp_name": "target", "created_by": "user", "market_id": 4}),
])
def test_lookup_rejects_colliding_names_from_other_sources_or_owners(mocker, scope, source, record):
    mocker.patch.object(repository, "get_skill_by_name", return_value=record)
    mocker.patch.object(remote, "get_mcp_records_by_tenant", return_value=[record])
    with pytest.raises(ResourceStateError, match="installation_name_conflict"):
        flow._lookup_installation(scope, {"source": source, "candidate_ref": "tenant_mcp_repository:3"}, "target")


@pytest.fixture
def installation(mocker, scope):
    candidate = {"candidate_ref": "tenant_mcp_repository:3", "source": "TENANT_MCP_REPOSITORY",
                 "resource_type": "mcp_server", "name": "Weather", "description": "Forecast", "retrieval_score": 0.8}
    state = {"conversation_id": "7", "run_id": "run", "version": 2, "purpose": "generate",
             "card": {"id": "card", "subtype": "requirement_coverage"}, "requirements": {}}
    mocker.patch.object(flow, "read_resource_state", new=AsyncMock(side_effect=lambda _: deepcopy(state)))
    mocker.patch.object(flow, "coverage_rows", side_effect=lambda _: [
        {"requirement_id": "other", "installable_resources": []},
        {"requirement_id": "r1", "installable_resources": [candidate]},
    ])

    async def update(_scope, change):
        updated = change(deepcopy(state))
        state.clear()
        state.update(updated)
        return deepcopy(state)

    write = mocker.patch.object(flow, "update_resource_state", new=AsyncMock(side_effect=update))
    lookup = mocker.patch.object(flow, "_lookup_installation", return_value=None)

    async def run(_task, function, *args, **kwargs):
        return function(*args)

    mocker.patch.object(concurrency, "run_blocking", new=run)
    return state, candidate, lookup, write


def request(operation="claim", **values):
    return ResourceInstallationAttemptRequest(agent_id=42, conversation_id=7, card_id="card", state_version=2,
                                             requirement_id="r1", candidate_ref="tenant_mcp_repository:3",
                                             operation=operation, **values)


@pytest.mark.asyncio
async def test_claim_returns_one_permit_and_followups_are_read_only(scope, installation):
    state, candidate, lookup, write = installation
    first = await flow.installation_attempt(scope, request())
    assert first["status"] == "claimed" and first["target_name"].startswith("nl2a-")
    assert state["installation_attempts"][candidate["candidate_ref"]] == {
        "target_name": first["target_name"], "attempt_id": first["attempt_id"],
    }
    for operation in ("claim", "check"):
        assert await flow.installation_attempt(scope, request(operation, target_name="ignored")) == {
            "status": "pending", "target_name": first["target_name"],
        }
    write.assert_awaited_once()
    lookup.return_value = {"resource_type": "mcp_server", "resource_id": 9}
    assert await flow.installation_attempt(scope, request("check")) == {
        "status": "installed", "resource_type": "mcp_server", "resource_id": 9,
    }
    assert write.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["check", "release"])
async def test_recovery_without_claim_never_queries_or_writes(scope, installation, operation):
    _, _, lookup, write = installation
    assert await flow.installation_attempt(scope, request(operation)) == {"status": "not_started"}
    lookup.assert_not_called()
    write.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("same_attempt", [True, False])
async def test_release_only_removes_matching_attempt(scope, installation, same_attempt):
    state, _, _, _ = installation
    claim = await flow.installation_attempt(scope, request())
    result = await flow.installation_attempt(scope, request(
        "release", attempt_id=claim["attempt_id"] if same_attempt else "forged",
    ))
    if same_attempt:
        assert result == {"status": "not_started"} and state["installation_attempts"] == {}
        assert (await flow.installation_attempt(scope, request()))["status"] == "claimed"
    else:
        assert result == {"status": "pending", "target_name": claim["target_name"]}
        assert state["installation_attempts"]["tenant_mcp_repository:3"]["attempt_id"] == claim["attempt_id"]


@pytest.mark.asyncio
async def test_concurrent_claim_loser_receives_pending_without_overwrite(mocker, scope, installation):
    state, _, _, write = installation

    async def concurrent_update(_scope, change):
        current = {**state, "installation_attempts": {
            "tenant_mcp_repository:3": {"attempt_id": "winner", "target_name": "winner-name"},
        }}
        return change(current)

    write.side_effect = concurrent_update
    assert await flow.installation_attempt(scope, request()) == {"status": "pending", "target_name": "winner-name"}


@pytest.mark.asyncio
@pytest.mark.parametrize("official,explicit,conflict", [(True, False, False), (False, False, False), (False, True, True)])
async def test_existing_installation_cannot_be_claimed_under_explicit_colliding_name(
    scope, installation, official, explicit, conflict,
):
    _, candidate, lookup, write = installation
    if official:
        candidate["source"] = "NEXENT_OFFICIAL_SKILL"
    lookup.return_value = {"resource_type": "skill" if official else "mcp_server", "resource_id": 9}
    if conflict:
        with pytest.raises(ResourceStateError, match="installation_name_conflict"):
            await flow.installation_attempt(scope, request(target_name="existing"))
    else:
        result = await flow.installation_attempt(scope, request())
        assert result == {"status": "installed", **lookup.return_value}
        if official:
            assert lookup.call_args.args[-1] == "Weather"
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_explicit_name_is_reserved_exactly(scope, installation):
    result = await flow.installation_attempt(scope, request(target_name="my-weather"))
    assert result["status"] == "claimed" and result["target_name"] == "my-weather"


@pytest.mark.asyncio
async def test_stale_card_and_unknown_candidate_fail_before_lookup(scope, installation):
    state, _, lookup, write = installation
    state["version"] = 3
    with pytest.raises(ResourceStateError, match="resource_card_stale"):
        await flow.installation_attempt(scope, request())
    state["version"] = 2
    with pytest.raises(ResourceStateError, match="resource_not_available_for_installation"):
        await flow.installation_attempt(scope, request().model_copy(update={"candidate_ref": "other"}))
    lookup.assert_not_called()
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_card_changed_during_lookup_cannot_reserve(scope, installation):
    state, _, lookup, _ = installation

    def change_card(*args):
        state["version"] = 3

    lookup.side_effect = change_card
    with pytest.raises(ResourceStateError, match="resource_card_stale"):
        await flow.installation_attempt(scope, request())
    assert "installation_attempts" not in state


@pytest.mark.asyncio
async def test_installation_details_uses_authorized_candidate(mocker, scope, installation):
    mocker.patch.object(flow, "_repository_mcp_installation_status", new=AsyncMock(return_value={}))
    resource = SimpleNamespace(model_dump=lambda **_: {"name": "Weather", "source": "TENANT_MCP_REPOSITORY"})
    recommend = mocker.patch.object(flow.legacy, "recommend_uninstalled_resources_impl", new=AsyncMock(
        return_value=SimpleNamespace(resources=[resource]),
    ))
    result = await flow.installation_details(scope, ResourceInstallationRequest.model_validate(
        {key: value for key, value in request().model_dump().items() if key not in {"operation", "target_name", "attempt_id"}},
    ))
    assert result == {"subtype": "suggested_resource_installation", "agent_id": 42,
                      "resources": [{"name": "Weather", "source": "TENANT_MCP_REPOSITORY"}]}
    assert recommend.call_args.kwargs["tenant_id"] == "tenant"
    assert recommend.call_args.kwargs["user_id"] == "user"
    assert recommend.call_args.kwargs["recommended_refs"] == ["tenant_mcp_repository:3"]
    assert recommend.call_args.kwargs["candidates"][0].requirement_ids == ["r1"]
