# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Recall and independent assessment regressions for interchangeable tools."""
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from contracts.nl2agent_resources import RequirementDiscoveryInput, RequirementEdit, ResourceCardAction, VerificationCheck
from services import nl2agent_resource_flow as flow
from services.nl2agent_state_service import ResourceScope, ResourceStateError


def resource(index, name, description):
    return {"candidate_ref": f"tool:{index}", "name": name, "description": description,
            "resource_type": "tool", "source": "LOCAL_TOOL", "names": [name],
            "descriptions": [description], "labels": ["search"], "interfaces": [],
            "installed": True, "quality": 1.0}


@pytest.mark.parametrize("catalog_size", [5, 37, 80])
def test_actual_web_declarations_keep_bounded_alternatives(catalog_size):
    description = ("Performs a internet search based on your query (think a Google search) then returns "
                   "the top search results. A tool for retrieving publicly available information, news, "
                   "general knowledge, or non-proprietary data from the internet. Use this for real-time "
                   "open-domain updates, broad topics, or or general knowledge queries")
    catalog = [resource(108, "exa_search", description), resource(126, "tavily_search", description),
               resource(114, "linkup_search", description), resource(361, "deepseek_search",
                   "Search public webpages using DeepSeek for current information and return citable sources."),
               resource(113, "knowledge_base_search", "Search domain-specific information in a knowledge base.")]
    catalog.extend({**resource(1000 + i, f"workspace_operation_{i}",
                              "Create or move workspace files and directories."), "labels": []}
                   for i in range(catalog_size - len(catalog)))
    result = flow._rank("r", "在线搜索补充公开背景资料", catalog,
                        search_queries={"zh": "联网搜索活动相关公开信息",
                                        "en": "web search public background information"})
    assert 1 <= len(result) <= 9
    assert {row["name"] for row in result} <= {item["name"] for item in catalog}
    assert all(row["retrieval_score"] >= .5 for row in result)


def test_recall_does_not_expand_cutoff_ties(mocker):
    catalog = [resource(i, f"resource_{i}", "") for i in range(80)]
    mocker.patch.object(flow.legacy, "_score_resource_requirement", side_effect=lambda req, item:
                        0.8 if int(item["candidate_ref"].split(":")[1]) < 20 else 0.49)
    result = flow._rank("r", "search information", catalog)
    assert len(result) == 3
    assert all(item["retrieval_score"] == 0.8 for item in result)
    mocker.patch.object(flow.legacy, "_score_resource_requirement", return_value=0.8)
    assert len(flow._rank("r", "search information", catalog)) == 3


def state():
    return {"batch": {"id": "batch", "requirements": ["r"]}, "requirements": {"r": {
        "verification_policy": "all_qualified", "installed": [
            {"candidate_ref": "tool:1"}, {"candidate_ref": "tool:2"}, {"candidate_ref": "tool:3"}],
        "installable": [],
    }}}


def assessment(ref, satisfies=True):
    return {"candidate_ref": ref, "satisfies": satisfies,
            "reason": "Declared public web retrieval." if satisfies else "Only searches a private knowledge base."}


def test_independent_assessments_keep_all_matching_resources():
    check = VerificationCheck(requirement_id="r", accepted=["tool:1", "tool:2"], assessments=[
        assessment("tool:1"), assessment("tool:2"), assessment("tool:3", False)])
    assert flow.validate_checks(state(), "batch", [check]) == {"r": ["tool:1", "tool:2"]}


def test_new_batches_reject_single_selection_without_assessments():
    with pytest.raises(ResourceStateError, match="verification_assessments_required"):
        flow.validate_checks(state(), "batch", [VerificationCheck(requirement_id="r", accepted=["tool:1"])])


def test_empty_candidate_batch_accepts_an_explicit_empty_assessment():
    snapshot = state()
    snapshot["requirements"]["r"]["installed"] = []
    assert flow.validate_checks(snapshot, "batch", [VerificationCheck(
        requirement_id="r", accepted=[], assessments=[])]) == {"r": []}


@pytest.mark.parametrize("assessments,accepted,code", [
    ([assessment("tool:1")], ["tool:1"], "verification_assessments_incomplete"),
    ([assessment("tool:1"), assessment("tool:1"), assessment("tool:3")], ["tool:1"],
     "verification_assessments_incomplete"),
    ([assessment("tool:1"), assessment("tool:2"), assessment("tool:4")], ["tool:1"],
     "verification_assessments_incomplete"),
    ([assessment("tool:1"), assessment("tool:2"), assessment("tool:3", False)], ["tool:1"],
     "verification_acceptance_mismatch"),
    ([assessment("tool:1"), assessment("tool:2", False), assessment("tool:3", False)], ["tool:1", "tool:2"],
     "verification_acceptance_mismatch"),
])
def test_assessment_completeness_and_acceptance_consistency(assessments, accepted, code):
    check = VerificationCheck(requirement_id="r", accepted=accepted, assessments=assessments)
    with pytest.raises(ResourceStateError, match=code):
        flow.validate_checks(state(), "batch", [check])


@pytest.mark.parametrize("changes", [{"reason": " "}, {"satisfies": "true"}])
def test_assessment_rejects_empty_reason_or_coerced_boolean(changes):
    with pytest.raises(ValidationError):
        VerificationCheck(requirement_id="r", accepted=[], assessments=[{**assessment("tool:1"), **changes}])


def test_legacy_inflight_batches_remain_compatible():
    snapshot = state()
    snapshot["requirements"]["r"].pop("verification_policy")
    assert flow.validate_checks(snapshot, "batch", [VerificationCheck(
        requirement_id="r", accepted=["tool:1"])]) == {"r": ["tool:1"]}


def test_coverage_and_binding_defaults_preserve_all_positive_candidates():
    from management.services.agent.nl2agent_tools import ResourceCandidate

    catalog = [{**resource(index, name, "Search public web information"), "config": []}
               for index, name in enumerate(["exa_search", "linkup_search", "tavily_search", "deepseek_search"])]
    candidates = [flow._candidate(item, 0.8) for item in catalog]
    accepted = [item["candidate_ref"] for item in candidates]
    coverage = flow.coverage_rows({"requirements": {"r": {
        "query": "Search public web", "accepted": accepted, "installed": candidates, "installable": [],
    }}})[0]
    assert coverage["coverage_status"] == "covered"
    assert [item["candidate_ref"] for item in coverage["covered_resources"]] == accepted
    # Use the real card-resource projection; recommendation flags do not filter candidates.
    output = [flow.legacy._recommended_resource(
        actual=actual, supplied=ResourceCandidate(
            candidate_ref=item["candidate_ref"], resource_type="tool", source="LOCAL_TOOL",
            name=item["name"], description=item["description"], requirement_ids=["r"], score=0.8),
        recommended_refs={accepted[0]},
    ) for actual, item in zip(catalog, coverage["covered_resources"])]
    assert [item.candidate.candidate_ref for item in output] == accepted
    assert [item.recommendation for item in output] == ["recommended", "optional", "optional", "optional"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["text", "hybrid", "fallback"])
async def test_all_alternatives_survive_pages_and_binding_defaults(mocker, mode):
    scope = ResourceScope("tenant", "user", 1, "2", "run")
    saved = {}
    catalog = [{**resource(i, f"search_provider_{i}", "Search public web background information"),
                "config": []} for i in range(8)]

    async def update(_scope, change):
        value = dict(change(saved or None))
        saved.clear()
        saved.update(value)
        return dict(saved)

    async def inline(_name, fn, *args, **kwargs):
        kwargs.pop("owner", None)
        return fn(*args, **kwargs)

    mocker.patch.object(flow, "update_resource_state", side_effect=update)
    mocker.patch.object(flow, "read_resource_state", side_effect=lambda _: dict(saved))
    mocker.patch.object(flow, "run_blocking", side_effect=inline)
    mocker.patch.object(flow, "_progress", new=AsyncMock())
    mocker.patch.object(flow.semantic, "resolve_model", new=AsyncMock(
        return_value=None if mode == "text" else object()))
    mocker.patch.object(flow.semantic, "retrieve", new=AsyncMock(
        side_effect=TimeoutError() if mode == "fallback" else None,
        return_value={"r1": {"installed": [], "installable": []}}))
    mocker.patch.object(flow.legacy, "_load_installed_resource_catalog", new=AsyncMock(return_value=catalog))
    mocker.patch.object(flow.legacy, "_load_internal_uninstalled_resource_catalog", new=AsyncMock(return_value=[]))
    mocker.patch.object(flow.legacy, "query_all_enabled_tool_instances", return_value=[])
    result = await flow.discover(scope, [RequirementDiscoveryInput(
        query="Search public web background information", search_queries={
            "zh": "联网搜索公开背景资料", "en": "web search public background information"})], "generate")
    assert result["requirements"][0]["verification_policy"] == "all_qualified"
    row = saved["requirements"]["r1"]
    expected = {"tool:0", "tool:1", "tool:2"}
    assert set(row["retrieval_evidence"]["installed"]["text_refs"]) == expected
    batches = []
    while result["verification_batch_id"]:
        batch_id = result["verification_batch_id"]
        offered = flow._candidates_in_batch(saved["requirements"]["r1"])
        refs = [item["candidate_ref"] for item in offered]
        check = VerificationCheck(requirement_id="r1", accepted=refs,
                                  assessments=[assessment(ref) for ref in refs])
        if not batches:
            snapshot = dict(saved)
            with pytest.raises(ResourceStateError, match="verification_assessments_required"):
                await flow.verify(scope, batch_id, [VerificationCheck(requirement_id="r1", accepted=refs[:1])])
            assert saved == snapshot
        result = await flow.verify(scope, batch_id, [check])
        batches.append((batch_id, check))
    assert len(batches) == 1
    assert set(saved["requirements"]["r1"]["accepted"]) == expected
    assert set(saved["requirements"]["r1"]["candidate_assessments"]) == expected
    # Replays are idempotent and changing an assessment reason is a conflicting submission.
    await flow.verify(scope, batches[0][0], [batches[0][1]])
    changed = batches[0][1].model_copy(deep=True)
    changed.assessments[0].reason = "A different reason"
    with pytest.raises(ResourceStateError, match="verification_batch_conflict"):
        await flow.verify(scope, batches[0][0], [changed])
    card = await flow.show_card(scope)
    assert {item["candidate_ref"] for item in card["requirements"][0]["covered_resources"]} == expected
    assert {item["candidate"]["candidate_ref"] for item in card["resources"]} == expected
    assert sum(item["recommendation"] == "recommended" for item in card["resources"]) == 1
    returned = await flow.apply_card_action(scope, card["subtype"], "confirm_requirements", ResourceCardAction(
        card_id=card["card_id"], state_version=card["state_version"], requirements=[RequirementEdit(requirement_id=row["requirement_id"], query=row["query"]) for row in card["requirements"]]))
    clarification = returned["card"]
    await flow.apply_card_action(scope, clarification["subtype"], "confirm_requirements", ResourceCardAction(
        card_id=clarification["card_id"], state_version=clarification["state_version"], requirements=[
            RequirementEdit(requirement_id="r1", query=saved["requirements"]["r1"]["query"])],
    ))
    assert set(saved["requirements"]["r1"]["candidate_assessments"]) == expected
    assert saved["submitted_batches"] == {}


@pytest.mark.parametrize("language", ["zh", "en"])
def test_model_prompt_demands_independent_assessments(language):
    from runtime.agentos.agent_creator_config import build_nl2agent_system_prompt

    prompt = build_nl2agent_system_prompt(language)
    assert '"assessments"' in prompt and '"satisfies"' in prompt and '"reason"' in prompt
    assert '"all_qualified"' in prompt
