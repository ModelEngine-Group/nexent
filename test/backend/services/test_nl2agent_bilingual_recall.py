# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Bilingual recall and authoritative requirement-state regressions."""

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from contracts.nl2agent_resources import RequirementDiscoveryInput, RequirementEdit, VerificationCheck
from management.services.agent.creation import build_nl2agent_system_prompt
from services import nl2agent_resource_flow as flow
from services.nl2agent_state_service import ResourceScope, ResourceStateError
from tool_collection.mcp import nl2agent_resource_tools as tools


PAIR = {"zh": "联网搜索", "en": "web search"}


@pytest.fixture(autouse=True)
def lexical_environment(mocker):
    mocker.patch.object(flow.semantic, "resolve_model", new=AsyncMock(return_value=None))
    mocker.patch.object(flow, "_progress", new=AsyncMock())


def resource(ref, name, description):
    return {
        "candidate_ref": ref, "resource_type": "tool", "source": "LOCAL_TOOL", "name": name,
        "description": description, "names": [name], "descriptions": [description],
        "labels": [], "interfaces": [], "installed": True, "quality": 1.0,
    }


@pytest.mark.parametrize("query,pair,name,description", [
    ("联网搜索", PAIR, "deepseek_search", "Search public webpages for current information"),
    ("Search public webpages", {"zh": "联网搜索", "en": "Search public webpages"},
     "网页助手", "联网搜索"),
])
def test_opposite_language_reaches_candidates(query, pair, name, description):
    candidates = flow._rank("r1", query, [resource("tool:1", name, description)], search_queries=pair)
    assert [item["candidate_ref"] for item in candidates] == ["tool:1"]


def test_each_route_keeps_its_quota_and_uses_maximum_score(mocker):
    catalog = [resource(f"tool:{i}", f"resource-{i}", "") for i in range(7)]
    def score(requirement, item):
        index = int(item["candidate_ref"].split(":")[1])
        if requirement.query == PAIR["zh"]:
            return [0.9, 0.8, 0.7, 0.1, 0.1, 0.1, 0.49][index]
        return [0.1, 0.1, 0.95, 0.85, 0.75, 0.65, 0.49][index]
    mocker.patch.object(flow.legacy, "_score_resource_requirement", side_effect=score)
    result = flow._rank("r1", PAIR["zh"], catalog, search_queries=PAIR)
    assert [row["candidate_ref"] for row in result] == ["tool:2", "tool:0", "tool:3", "tool:1", "tool:4"]
    assert result[0]["retrieval_score"] == 0.95
    assert len({row["candidate_ref"] for row in result}) == len(result)
    assert "tool:6" not in {row["candidate_ref"] for row in result}


@pytest.mark.parametrize("score,expected", [(0.4999, []), (0.5, ["tool:1"])])
def test_route_threshold_is_inclusive(mocker, score, expected):
    mocker.patch.object(flow.legacy, "_score_resource_requirement", return_value=score)
    # Thresholds apply independently to every expression.
    result = flow._rank("r", "联网搜索", [resource("tool:1", "unrelated", "web")], search_queries=PAIR)
    assert [row["candidate_ref"] for row in result] == expected


@pytest.fixture
def memory(mocker):
    scope = ResourceScope("tenant", "user", 1, "2", "run")
    state = {}
    async def update(_scope, change):
        value = dict(change(state or None))
        state.clear()
        state.update(value)
        return state.copy()
    mocker.patch.object(flow, "update_resource_state", side_effect=update)
    mocker.patch.object(flow, "read_resource_state", side_effect=lambda _: state.copy())
    installed = mocker.patch.object(flow.legacy, "_load_installed_resource_catalog", new=AsyncMock(return_value=[]))
    repository = mocker.patch.object(flow.legacy, "_load_internal_uninstalled_resource_catalog", new=AsyncMock(return_value=[]))
    return scope, state, installed, repository


async def test_missing_queries_are_prepared_before_catalog_search(memory):
    scope, state, installed, repository = memory
    result = await flow.discover(scope, [RequirementDiscoveryInput(query="联网搜索")], "generate")
    assert result["next_step"] == "prepare_search_queries"
    assert result["requirements"] == [{"requirement_id": "r1", "query": "联网搜索"}]
    installed.assert_not_called()
    repository.assert_not_called()
    result = await flow.discover(scope, None, "generate", search_queries={"r1": PAIR})
    assert result["verification_batch_id"]
    assert state["requirements"]["r1"]["query"] == "联网搜索"
    assert state["requirements"]["r1"]["search_queries"] == PAIR
    assert "accepted" not in state["requirements"]["r1"]


async def test_initial_queries_are_retained_and_do_not_establish_coverage(memory):
    scope, state, installed, _ = memory
    installed.return_value = [resource("tool:1", "web search", "Search the web")]
    result = await flow.discover(scope, [RequirementDiscoveryInput(query="联网搜索", search_queries=PAIR)], "generate")
    assert result["requirements"][0]["query"] == "联网搜索"
    assert result["requirements"][0]["installed_candidates"][0]["candidate_ref"] == "tool:1"
    assert flow.coverage_rows(state)[0]["coverage_status"] == "uncovered"
    await flow.verify(scope, result["verification_batch_id"], [VerificationCheck(requirement_id="r1", accepted=[], assessments=[
        {"candidate_ref": item["candidate_ref"], "satisfies": False, "reason": "Required capability is absent."}
        for item in flow._candidates_in_batch(state["requirements"]["r1"])])])
    assert flow.coverage_rows(state)[0]["coverage_status"] == "uncovered"


async def test_merged_candidates_are_all_verified_across_batches(memory):
    scope, state, installed, repository = memory
    catalog = [resource(f"tool:{index}", "联网搜索" if index < 3 else "web search", "") for index in range(6)]
    installed.return_value = catalog
    repository.return_value = [
        {**item, "candidate_ref": f"tenant_mcp_repository:{index}", "installed": False,
         "source": "TENANT_MCP_REPOSITORY", "resource_type": "mcp_server"}
        for index, item in enumerate(catalog)
    ]
    result = await flow.discover(scope, [RequirementDiscoveryInput(query="联网搜索", search_queries=PAIR)], "generate")
    row = state["requirements"]["r1"]
    assert len(row["installed"]) == len(row["installable"]) == 6
    first = result["requirements"][0]
    assert len(first["installed_candidates"]) + len(first["installable_candidates"]) == 6
    result = await flow.verify(scope, result["verification_batch_id"], [VerificationCheck(requirement_id="r1", accepted=[], assessments=[
        {"candidate_ref": item["candidate_ref"], "satisfies": False, "reason": "Required capability is absent."}
        for item in flow._candidates_in_batch(state["requirements"]["r1"])])])
    assert "accepted" not in state["requirements"]["r1"]
    second = result["requirements"][0]
    assert len(second["installed_candidates"]) + len(second["installable_candidates"]) == 6
    result = await flow.verify(scope, result["verification_batch_id"], [VerificationCheck(requirement_id="r1", accepted=[], assessments=[
        {"candidate_ref": item["candidate_ref"], "satisfies": False, "reason": "Required capability is absent."}
        for item in flow._candidates_in_batch(state["requirements"]["r1"])])])
    assert result["verification_batch_id"] is None
    assert state["requirements"]["r1"]["accepted"] == []
    assert flow.coverage_rows(state)[0]["coverage_status"] == "uncovered"


async def test_edit_requires_new_translations_and_keeps_unchanged_evidence(memory):
    scope, state, installed, _ = memory
    await flow.discover(scope, [RequirementDiscoveryInput(query="联网搜索", search_queries=PAIR)], "generate")
    unchanged = {"query": "发送邮件", "required": True, "accepted": [], "installed": [], "installable": [],
                 "search_queries": {"zh": "发送邮件", "en": "send email"}}
    state["requirements"]["keep"] = unchanged
    state.update(flow.apply_requirement_edits(state, [
        RequirementEdit(requirement_id="r1", query="搜索实时余票"),
        RequirementEdit(requirement_id="keep", query="发送邮件"),
    ]))
    installed.reset_mock()
    result = await flow.discover(scope, None, "generate")
    assert result["requirements"] == [{"requirement_id": "r1", "query": "搜索实时余票"}]
    assert "search_queries" not in state["requirements"]["r1"]
    assert state["requirements"]["keep"] == unchanged
    installed.assert_not_called()


def test_confirming_a_legacy_gap_prepares_bilingual_recall_once():
    state = {"requirements": {"r1": {"query": "联网搜索", "required": True,
              "installed": [], "installable": [], "accepted": []}}, "batch": None}
    result = flow.apply_requirement_edits(state, [RequirementEdit(requirement_id="r1", query="联网搜索")])
    assert result["requirements"]["r1"] == {"query": "联网搜索", "required": True}
    current = {**state["requirements"]["r1"], "search_queries": PAIR}
    state["requirements"]["r1"] = current
    repeated = flow.apply_requirement_edits(state, [RequirementEdit(requirement_id="r1", query="联网搜索")])
    assert repeated["requirements"]["r1"] == current


async def test_query_updates_cannot_replace_unknown_or_searched_requirements(memory):
    scope, state, _, _ = memory
    await flow.discover(scope, [RequirementDiscoveryInput(query="联网搜索", search_queries=PAIR)], "generate")
    for updates in [{"unknown": PAIR}, {"r1": {"zh": "删除文件", "en": "delete files"}}]:
        with pytest.raises(ResourceStateError, match="invalid_search_queries"):
            await flow.discover(scope, None, "generate", search_queries=updates)
    assert state["requirements"]["r1"]["query"] == "联网搜索"
    assert state["requirements"]["r1"]["search_queries"] == PAIR


@pytest.mark.parametrize("pair", [
    {}, {"zh": "联网搜索"}, {"zh": " ", "en": "search"},
    {"zh": "联网搜索", "en": "x" * 81}, {"zh": "联网搜索", "en": "search", "other": "bad"},
])
def test_invalid_bilingual_pairs_are_rejected(pair):
    with pytest.raises(ValidationError):
        RequirementDiscoveryInput(query="联网搜索", search_queries=pair)


@pytest.mark.parametrize("updates", [{}, {"r1": {"zh": "联网搜索"}}, {"": PAIR}, {str(i): PAIR for i in range(9)}])
async def test_tool_rejects_invalid_query_updates(mocker, updates):
    run = mocker.patch.object(tools, "_run")
    result = await tools.discover_requirements(search_queries=updates)
    assert result["status"] == "error"
    run.assert_not_called()


async def test_same_query_update_is_idempotent_and_cannot_cross_runs(memory):
    scope, state, installed, _ = memory
    first = await flow.discover(scope, [RequirementDiscoveryInput(query="联网搜索", search_queries=PAIR)], "generate")
    installed.reset_mock()
    repeated = await flow.discover(scope, None, "generate", search_queries={"r1": PAIR})
    assert repeated["verification_batch_id"] == first["verification_batch_id"]
    installed.assert_not_called()
    stale = ResourceScope(scope.tenant_id, scope.user_id, scope.agent_id, scope.conversation_id, "old-run")
    with pytest.raises(ResourceStateError):
        await flow.discover(stale, None, "generate", search_queries={"r1": PAIR})
    assert state["run_id"] == scope.run_id


@pytest.mark.parametrize("language", ["zh", "en"])
def test_creator_instructs_bilingual_preparation_and_original_query_verification(language):
    prompt = build_nl2agent_system_prompt(language)
    assert '"search_queries"' in prompt
    assert 'search_queries.zh' in prompt and 'search_queries.en' in prompt
    assert 'prepare_search_queries' in prompt
    assert 'nl2a_verify_requirements' in prompt
