# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import AsyncMock

import pytest

from contracts.nl2agent_resources import RequirementDiscoveryInput, ResourceCardAction
from infrastructure.system_configuration.catalog import DEFAULT_CATALOG, NL2AGENT_RESOURCE_DENYLIST
from infrastructure.system_configuration.runtime import ConfigurationNotReadyError
from services import nl2agent_resource_flow as flow
from services.nl2agent_state_service import ResourceScope, ResourceStateError


@pytest.fixture
def workflow(monkeypatch):
    state = {}
    refs = []
    scope = ResourceScope("tenant", "user", 1, "2", "run")

    async def update(_scope, change):
        value = change(state or None)
        if value is not state:
            state.clear()
            state.update(value)
        return dict(state)

    async def inline(_name, call, *args, **_kwargs):
        return call(*args)

    monkeypatch.setattr(flow, "get_config_snapshot", lambda: DEFAULT_CATALOG.build_snapshot({
        **DEFAULT_CATALOG.defaults, NL2AGENT_RESOURCE_DENYLIST: refs,
    }))
    monkeypatch.setattr(flow, "read_resource_state", AsyncMock(side_effect=lambda _: dict(state)))
    monkeypatch.setattr(flow, "update_resource_state", update)
    monkeypatch.setattr(flow, "run_blocking", inline)
    monkeypatch.setattr(flow, "_progress", AsyncMock())
    return scope, state, refs


def declaration(ref, *, installed=True):
    return {
        "candidate_ref": ref, "resource_type": "tool" if installed else "mcp_server",
        "source": "LOCAL_TOOL" if installed else "TENANT_MCP_REPOSITORY",
        "name": "search", "description": "Search the public web.", "installed": installed,
    }


@pytest.mark.asyncio
async def test_denylist_filters_both_catalogs_before_ranking_and_replaces_cached_batch(workflow, monkeypatch):
    scope, state, refs = workflow
    installed = [declaration(f"tool:{i}") for i in range(1, 5)]
    installable = [declaration("tenant_mcp_repository:1", installed=False)]
    monkeypatch.setattr(flow.legacy, "_load_installed_resource_catalog", AsyncMock(return_value=installed))
    monkeypatch.setattr(flow.legacy, "_load_internal_uninstalled_resource_catalog", AsyncMock(return_value=installable))
    monkeypatch.setattr(flow.legacy, "_score_resource_requirement", lambda *_args, **_kwargs: 0.8)
    monkeypatch.setattr(flow.semantic, "resolve_model", AsyncMock(return_value=object()))

    async def semantic(_tenant, _model, queries, available, repository, _progress):
        assert [item["candidate_ref"] for item in available] == [item["candidate_ref"] for item in installed
                                                               if item["candidate_ref"] not in refs]
        assert [item["candidate_ref"] for item in repository] == [item["candidate_ref"] for item in installable
                                                                if item["candidate_ref"] not in refs]
        return {key: {"installed": [], "installable": []} for key in queries}

    monkeypatch.setattr(flow.semantic, "retrieve", semantic)
    requirements = [RequirementDiscoveryInput(
        query="Search the web", search_queries={"zh": "网页检索", "en": "web search"},
    )]
    initial = await flow.discover(scope, requirements, "generate")
    assert [item["candidate_ref"] for item in initial["requirements"][0]["installed_candidates"]] == [
        "tool:1", "tool:2", "tool:3",
    ]

    refs.extend(["tool:1", "tenant_mcp_repository:1"])
    refreshed = await flow.verify(scope, initial["verification_batch_id"], [])
    assert refreshed["verification_batch_id"] != initial["verification_batch_id"]
    assert [item["candidate_ref"] for item in refreshed["requirements"][0]["installed_candidates"]] == [
        "tool:2", "tool:3", "tool:4",
    ]
    assert refreshed["requirements"][0]["installable_candidates"] == []
    assert state["requirements"]["r1"]["query"] == requirements[0].query
    with pytest.raises(ResourceStateError, match="verification_batch_stale"):
        await flow.verify(scope, initial["verification_batch_id"], [])
    refs.clear()
    next_run = ResourceScope(scope.tenant_id, scope.user_id, scope.agent_id, scope.conversation_id, "next")
    restored = await flow.discover(next_run, requirements, "generate")
    assert restored["requirements"][0]["installed_candidates"][0]["candidate_ref"] == "tool:1"
    assert restored["requirements"][0]["installable_candidates"][0]["candidate_ref"] == "tenant_mcp_repository:1"


@pytest.mark.asyncio
async def test_old_card_continuation_refreshes_only_impacted_requirements(workflow):
    scope, state, refs = workflow
    rejected = {
        "query": "Find results", "installed": [flow._candidate(declaration("tool:1"), 0.8)],
        "accepted": ["tool:1"], "candidate_assessments": {"tool:1": {"satisfies": True}},
    }
    unchanged = {
        "query": "Read results", "installed": [flow._candidate(declaration("tool:2"), 0.8)],
        "accepted": ["tool:2"],
    }
    state.update({
        "version": 4, "run_id": "previous", "conversation_id": scope.conversation_id,
        "purpose": "generate", "batch": None, "card": {"id": "card", "subtype": "requirement_resources"},
        "requirements": {"r1": rejected, "r2": unchanged},
    })
    refs.append("tool:1")
    result = await flow.apply_card_action(scope, "requirement_resources", "continue", ResourceCardAction(
        state_version=4, card_id="card", selected_resource_refs=["tool:1"],
    ))
    assert result["next_step"] == "verify_resources"
    assert state["requirements"] == {"r1": {"query": "Find results"}, "r2": unchanged}
    assert state["card"] is None and state["version"] == 5
    assert "continuation" not in state


def test_unavailable_configuration_refuses_to_recommend(monkeypatch):
    def unavailable():
        raise ConfigurationNotReadyError("not loaded")

    monkeypatch.setattr(flow, "get_config_snapshot", unavailable)
    with pytest.raises(ResourceStateError, match="resource_configuration_unavailable") as error:
        flow.resource_denylist()
    assert error.value.retryable
