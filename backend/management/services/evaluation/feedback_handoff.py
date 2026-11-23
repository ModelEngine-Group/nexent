# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Give a resource editor only the development excerpts approved by the Agent editor."""

from hashlib import sha256

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution import DevelopmentExperimentRequest, PromptCandidateRequest, SkillStepCandidateRequest
from infrastructure.rdb.skill_candidate_records import read_bound_skill_candidate
from infrastructure.skill_execution import capture_skill_files
from infrastructure.skill_package import encode_skill_package
from management.db.evaluation import experiments as jobs
from management.db.evaluation.candidates import text_digest
from management.db.skill.repository import get_skill_by_id, query_skill_instances_by_agent_id
from management.services.evaluation.evolution_access import published_business_agent, require_business_agent_edit
from management.services.evaluation.experiments import _io, _snapshot, snapshot_digest
from management.services.evaluation.example_candidates import generate_example_candidates
from management.services.evaluation.prompt_candidates import generate_prompt_candidate
from management.services.evaluation.replay_cases import get_development_case
from management.services.evaluation.skill_candidates import generate_skill_discovery_candidate, generate_skill_step_candidate


def _approved_excerpt(excerpt, required_status, trial, task):
    result = trial["result"] or {}
    actual = result.get("answer")
    observed = excerpt.observed
    matched = isinstance(actual, str) and (bool(observed.strip()) and observed in actual or actual == observed == "")
    if (trial["status"] != required_status or not trial.get("receipt_id")
            or not excerpt.expected.strip() or excerpt.expected not in task["expected"]
            or not matched):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Excerpt must match the selected observed development result")
    return {"example_id": f"case-{excerpt.case_id}-trial-{trial['receipt_id']}",
            "expected": excerpt.expected, "observed": observed or "[Observed empty final answer]"}


def _require_baseline_guide(target, skill_id, candidate_id, trials):
    if target is None or target["skill_id"] != skill_id:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The evaluated Skill does not match this S2 request")
    for trial in trials:
        observed = trial["result"].get("skill") or {}
        if (observed.get("instance_id") != target["instance_id"] or observed.get("candidate_id") != candidate_id
                or observed.get("variant") != "base" or observed.get("guide_reads", 0) < 1):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "S2 requires observed reads of the selected baseline guide in both trials")


def _prepare_handoff(tenant, user, eid, request):
    scope = jobs.scope(tenant, eid)
    if not scope:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    agent_id, version = scope["agent_id"], scope["version_no"]
    require_business_agent_edit(agent_id, tenant, user)
    plan = jobs.read_plan(tenant, eid)
    records = jobs.trials(tenant, eid)
    trials = {r["case_id"]: r for r in records if r["variant"] == "base"}
    if request.method == "S1":
        if plan["request"]["candidate_type"] not in {"baseline", "skill_discovery"}:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select a baseline with observed Skill choices")
        if any(rec["status"] in {"pending", "running", "cancelled"} for rec in records):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select a completed experiment")
        bindings = query_skill_instances_by_agent_id(agent_id, tenant, version)
        if not any(r["enabled"] and r["skill_id"] == request.skill_id for r in bindings):
            raise AppException(ErrorCode.COMMON_FORBIDDEN)
        skill = get_skill_by_id(request.skill_id, tenant)
        if not skill:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
        feedback = dict(method="S1", agent_id=agent_id, version_no=version, skill_id=request.skill_id,
                        skill_name=skill["name"], source_text=skill.get("description") or "", goal=request.goal)
        files = capture_skill_files(tenant, skill["name"])
        feedback["source_digest"] = sha256(encode_skill_package(files)).hexdigest()
        for category in ("missed", "overused", "correct"):
            excerpt = getattr(request, category)
            case = get_development_case(tenant, user, agent_id, version, excerpt.case_id)
            feedback[category] = _selection_excerpt(skill["name"], category, excerpt, trials.get(excerpt.case_id), case)
        return plan, feedback
    feedback = dict(method=request.method, agent_id=agent_id, version_no=version, skill_id=request.skill_id,
                    goal=request.goal, source_passage=request.source_passage)
    for field, status in (("failure", "fail"), ("protection", "pass")):
        excerpt = getattr(request, field)
        trial = trials.get(excerpt.case_id)
        if not trial:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Unknown development trial")
        case = get_development_case(tenant, user, agent_id, version, excerpt.case_id)
        if (trial["result"] or {}).get("case_digest") != case["digest"]:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Case does not match the trial receipt")
        feedback[field] = _approved_excerpt(excerpt, status, trial, case["task"])
    if request.method == "S2":
        provenance = plan["request"]
        bindings = query_skill_instances_by_agent_id(agent_id, tenant, version)
        if not any(row["skill_id"] == request.skill_id and row["enabled"] for row in bindings):
            raise AppException(ErrorCode.COMMON_FORBIDDEN)
        skill = get_skill_by_id(request.skill_id, tenant)
        if not skill:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
        selected = [trials[request.failure.case_id], trials[request.protection.case_id]]
        if provenance.get("candidate_type") == "baseline":
            if not all(t["result"].get("selection", {}).get("reads", {}).get(skill["name"], 0) > 0 for t in selected):
                raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "S2 requires actual guide reads in both baseline tasks")
        else:
            target = (read_bound_skill_candidate(tenant, agent_id, version, provenance["candidate_id"])
                      if provenance.get("candidate_type") == "skill_step" else None)
            _require_baseline_guide(target, request.skill_id, provenance.get("candidate_id"), selected)
        files = capture_skill_files(tenant, skill["name"])
        feedback["source_digest"] = sha256(encode_skill_package(files)).hexdigest()
        source = files["SKILL.md"].decode("utf-8")
    else:
        source = published_business_agent(tenant, agent_id, version).get("prompt") or ""
        feedback["source_digest"] = text_digest(source)
    if source.count(request.source_passage) != 1:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select a unique passage from the target resource")
    return plan, feedback


def _selection_excerpt(name, category, excerpt, trial, case):
    result = (trial or {}).get("result") or {}
    observation = result.get("selection")
    if (not observation or trial["status"] not in {"pass", "fail"} or not trial.get("receipt_id")
            or result.get("case_digest") != case["digest"] or excerpt.query_excerpt not in case["task"]["query"]
            or observation["expected"] != case["task"].get("expected_skill_names")):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select an observed task and an exact query excerpt")
    expected = name in observation["expected"]
    used = name in observation["reads"]
    valid = {"missed": expected and not set(observation["expected"]).intersection(observation["reads"]),
             "overused": used and not expected,
             "correct": expected and used and observation["outcome"] == "hit" and trial["status"] == "pass"}
    if not valid[category]:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The recorded choice does not support this feedback")
    return {"example_id": f"case-{excerpt.case_id}-trial-{trial['receipt_id']}", "query": excerpt.query_excerpt,
            "target_expected": expected, "target_read": used}


async def handoff(tenant, user, eid, request):
    plan, feedback = await _io("prepare-development-handoff", _prepare_handoff, tenant, user, eid, request)
    source = await _snapshot(DevelopmentExperimentRequest.model_validate(plan["request"]), tenant, user, "base")
    if snapshot_digest(source) != plan["snapshots"]["base"]:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The baseline has changed since evaluation")
    await _io("authorize-development-handoff", require_business_agent_edit, feedback["agent_id"], tenant, user)
    return await _io("save-development-handoff", jobs.store_handoff, tenant, user, eid, feedback)


async def examples_from_experiment(tenant, user, eid, request):
    scope = await _io("identify-example-source", jobs.scope, tenant, eid)
    if not scope:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    agent, version = scope["agent_id"], scope["version_no"]
    await _io("authorize-example-source", require_business_agent_edit, agent, tenant, user)
    plan = await _io("read-example-plan", jobs.read_plan, tenant, eid)
    released = await _io("read-example-prompt", published_business_agent, tenant, agent, version)
    snapshot = await _snapshot(DevelopmentExperimentRequest.model_validate(plan["request"]), tenant, user, "base")
    if snapshot_digest(snapshot) != plan["snapshots"]["base"]:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The baseline has changed since evaluation")
    return await _io("select-prompt-examples", generate_example_candidates, tenant, user, eid, request,
                     released.get("prompt") or "", agent, version, plan["request"]["language"])


def generate_from_handoff(tenant, user, feedback_id, model_id):
    feedback = jobs.read_handoff(tenant, feedback_id)
    if not feedback:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    if feedback["method"] == "S1":
        return generate_skill_discovery_candidate(feedback, feedback_id, model_id, tenant, user)
    common = {key: feedback[key] for key in ("goal", "source_passage", "failure", "protection")}
    provenance = {"feedback_id": feedback_id, "source_digest": feedback["source_digest"]}
    if feedback["method"] == "S2":
        request = SkillStepCandidateRequest(model_id=model_id, skill_id=feedback["skill_id"], **common)
        return generate_skill_step_candidate(request, tenant, user, **provenance)
    request = PromptCandidateRequest(model_id=model_id, agent_id=feedback["agent_id"],
        version_no=feedback["version_no"], method=feedback["method"], **common)
    return generate_prompt_candidate(request, tenant, user, **provenance)
