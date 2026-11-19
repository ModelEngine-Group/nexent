# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Reuse source catalogs within a stage without caching authorization across stages."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from contracts.nl2agent_resources import VerificationCheck
from services import nl2agent_resource_flow as flow
from services.nl2agent_state_service import ResourceScope, ResourceStateError
from tool_collection.mcp.nl2agent_mcp_tools import ResourceCandidate


@pytest.fixture
def workflow(mocker):
    scope = ResourceScope("tenant", "user", 1, "2", "run")
    resource = {
        "candidate_ref": "tool:7", "resource_type": "tool", "source": "LOCAL_TOOL",
        "name": "search", "names": ["search"], "description": "Search", "descriptions": ["Search"],
        "installed": True, "quality": 1, "config": [], "inputs": {}, "labels": [], "interfaces": [],
        "private_marker": "catalog-only-secret",
    }
    state = {
        "conversation_id": "2", "run_id": "run", "version": 1, "card": None, "batch": None,
        "purpose": "bind", "requirements": {"r": {
            "query": "Search", "search_queries": {"zh": "搜索", "en": "search"},
        }},
    }

    async def update(_scope, change):
        result = change(deepcopy(state))
        state.clear()
        state.update(deepcopy(result))
        return deepcopy(state)

    async def blocking(_name, fn, *args, **kwargs):
        kwargs.pop("owner", None)
        kwargs.pop("lane", None)
        return fn(*args, **kwargs)

    mocker.patch.object(flow, "read_resource_state", new=AsyncMock(side_effect=lambda _: deepcopy(state)))
    mocker.patch.object(flow, "update_resource_state", side_effect=update)
    mocker.patch.object(flow, "run_blocking", side_effect=blocking)
    mocker.patch.object(flow, "_progress", new=AsyncMock())
    mocker.patch.object(flow.semantic, "resolve_model", new=AsyncMock(return_value=None))
    installed = mocker.patch.object(flow.legacy, "_load_installed_resource_catalog",
                                    new=AsyncMock(return_value=[resource]))
    installable = mocker.patch.object(flow.legacy, "_load_internal_uninstalled_resource_catalog",
                                      new=AsyncMock(return_value=[]))
    mocker.patch.object(flow.legacy, "query_all_enabled_tool_instances", return_value=[])
    mocker.patch.object(flow.legacy, "query_enabled_skill_instances", return_value=[])
    mocker.patch.object(flow, "_repository_mcp_installation_status", new=AsyncMock(return_value={}))
    return scope, state, resource, installed, installable


def checks(batch):
    rows = batch["requirements"]
    return [VerificationCheck(
        requirement_id=row["requirement_id"],
        accepted=[item["candidate_ref"] for item in row["installed_candidates"] + row["installable_candidates"]],
        assessments=[{"candidate_ref": item["candidate_ref"], "satisfies": True, "reason": "Declares search"}
                     for item in row["installed_candidates"] + row["installable_candidates"]],
    ) for row in rows]


@pytest.mark.asyncio
@pytest.mark.parametrize("repository", [False, True])
async def test_each_stage_reuses_catalog_and_next_stage_rereads(workflow, repository):
    scope, state, resource, installed, installable = workflow
    if repository:
        resource.update(candidate_ref="tenant_mcp_repository:7", resource_type="mcp_server",
                        source="TENANT_MCP_REPOSITORY", installed=False)
        installed.return_value = []
        installable.return_value = [resource]
    reader = installable if repository else installed
    batch = await flow.discover(scope, None, "bind")
    assert reader.await_count == 2
    reader.reset_mock()
    await flow.verify(scope, batch["verification_batch_id"], checks(batch))
    assert reader.await_count == 1
    reader.reset_mock()
    card = await flow.show_card(scope)
    assert reader.await_count == 1
    assert card["subtype"] == ("requirement_coverage" if repository else "installed_resource_binding")
    assert "catalogs" not in card and "catalogs" not in state
    assert "catalog-only-secret" not in repr(card) + repr(state)
    if not repository:
        assert card["resources"][0]["candidate"]["candidate_ref"] == "tool:7"


@pytest.mark.asyncio
async def test_search_completion_rechecks_revoked_access(workflow):
    scope, _, resource, installed, _ = workflow
    installed.side_effect = [[resource], []]
    with pytest.raises(ResourceStateError, match="resource_evidence_changed"):
        await flow.discover(scope, None, "bind")
    assert installed.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["verify", "card", "cached_batch", "replayed_verification"])
async def test_new_stage_or_replay_cannot_reuse_old_authorization(workflow, stage):
    scope, _, _, installed, _ = workflow
    batch = await flow.discover(scope, None, "bind")
    submitted = checks(batch)
    if stage in {"card", "replayed_verification"}:
        await flow.verify(scope, batch["verification_batch_id"], submitted)
    installed.return_value = []
    installed.reset_mock()
    with pytest.raises(ResourceStateError, match="resource_evidence_changed"):
        if stage in {"verify", "replayed_verification"}:
            await flow.verify(scope, batch["verification_batch_id"], submitted)
        elif stage == "card":
            await flow.show_card(scope)
        else:
            await flow.discover(scope, None, "bind")
    installed.assert_awaited_once()


@pytest.mark.asyncio
async def test_catalog_failure_propagates_at_new_stage(workflow):
    scope, _, _, installed, _ = workflow
    batch = await flow.discover(scope, None, "bind")
    installed.side_effect = ConnectionError("unavailable")
    with pytest.raises(ConnectionError, match="unavailable"):
        await flow.verify(scope, batch["verification_batch_id"], checks(batch))


@pytest.mark.asyncio
async def test_next_batch_loads_missing_source_kind_once(workflow, mocker):
    scope, _, resource, installed, installable = workflow
    installed.return_value = [{**resource, "candidate_ref": f"tool:{index}"} for index in range(1, 7)]
    installable.return_value = [{**resource, "candidate_ref": "tenant_mcp_repository:7",
                                "resource_type": "mcp_server", "source": "TENANT_MCP_REPOSITORY",
                                "installed": False}]
    mocker.patch.object(flow.semantic, "resolve_model", new=AsyncMock(return_value=object()))
    mocker.patch.object(flow.semantic, "retrieve", new=AsyncMock(return_value={
        "r": {"installed": [(.9, item) for item in installed.return_value], "installable": []},
    }))
    batch = await flow.discover(scope, None, "bind")
    assert len(batch["requirements"][0]["installed_candidates"]) == 6
    assert batch["requirements"][0]["installable_candidates"] == []
    installed.reset_mock()
    installable.reset_mock()
    result = await flow.verify(scope, batch["verification_batch_id"], checks(batch))
    assert result["requirements"][0]["installable_candidates"][0]["candidate_ref"] == "tenant_mcp_repository:7"
    installed.assert_awaited_once()
    installable.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("provided", [False, True])
async def test_recommendation_default_loads_but_explicit_empty_catalog_does_not(workflow, provided):
    scope, _, _, installed, _ = workflow
    candidate = ResourceCandidate(candidate_ref="tool:7", resource_type="tool", source="LOCAL_TOOL", name="search",
                                  score=.9, requirement_ids=["r"])
    args = dict(agent_id=scope.agent_id, tenant_id=scope.tenant_id, user_id=scope.user_id,
                candidates=[candidate], recommended_refs=["tool:7"], include_knowledge_recommendations=False)
    if provided:
        with pytest.raises(flow.legacy.Nl2AgentResourceError, match="resource_not_visible"):
            await flow.legacy.recommend_installed_resources_impl(**args, catalog=[])
        installed.assert_not_awaited()
    else:
        result = await flow.legacy.recommend_installed_resources_impl(**args)
        assert result.resources[0].candidate.candidate_ref == "tool:7"
        installed.assert_awaited_once()
