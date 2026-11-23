# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Give a resource editor only the development excerpts approved by the Agent editor."""

from hashlib import sha256

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution import DevelopmentExperimentRequest, PromptCandidateRequest, SkillStepCandidateRequest
from infrastructure.skill_execution import capture_skill_files
from infrastructure.skill_package import encode_skill_package
from management.db.evaluation import experiments as jobs
from management.db.evaluation.candidates import text_digest
from management.db.skill.repository import get_skill_by_id, query_skill_instances_by_agent_id
from management.services.evaluation.evolution_access import published_business_agent, require_business_agent_edit
from management.services.evaluation.experiments import _io, _snapshot, snapshot_digest
from management.services.evaluation.prompt_candidates import generate_prompt_candidate
from management.services.evaluation.replay_cases import get_development_case
from management.services.evaluation.skill_candidates import generate_skill_step_candidate


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


def _prepare_handoff(tenant, user, eid, request):
    scope = jobs.scope(tenant, eid)
    if not scope:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    agent_id, version = scope["agent_id"], scope["version_no"]
    require_business_agent_edit(agent_id, tenant, user)
    plan = jobs.read_plan(tenant, eid)
    trials = {r["case_id"]: r for r in jobs.trials(tenant, eid) if r["variant"] == "base"}
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
        bindings = query_skill_instances_by_agent_id(agent_id, tenant, version)
        if not any(row["skill_id"] == request.skill_id and row["enabled"] for row in bindings):
            raise AppException(ErrorCode.COMMON_FORBIDDEN)
        skill = get_skill_by_id(request.skill_id, tenant)
        if not skill:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
        files = capture_skill_files(tenant, skill["name"])
        feedback["source_digest"] = sha256(encode_skill_package(files)).hexdigest()
        source = files["SKILL.md"].decode("utf-8")
    else:
        source = published_business_agent(tenant, agent_id, version).get("prompt") or ""
        feedback["source_digest"] = text_digest(source)
    if source.count(request.source_passage) != 1:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select a unique passage from the target resource")
    return plan, feedback


async def handoff(tenant, user, eid, request):
    plan, feedback = await _io("prepare-development-handoff", _prepare_handoff, tenant, user, eid, request)
    source = await _snapshot(DevelopmentExperimentRequest.model_validate(plan["request"]), tenant, user, "base")
    if snapshot_digest(source) != plan["snapshots"]["base"]:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The baseline has changed since evaluation")
    await _io("authorize-development-handoff", require_business_agent_edit, feedback["agent_id"], tenant, user)
    return await _io("save-development-handoff", jobs.store_handoff, tenant, user, eid, feedback)


def generate_from_handoff(tenant, user, feedback_id, model_id):
    feedback = jobs.read_handoff(tenant, feedback_id)
    if not feedback:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    common = {key: feedback[key] for key in ("goal", "source_passage", "failure", "protection")}
    provenance = {"feedback_id": feedback_id, "source_digest": feedback["source_digest"]}
    if feedback["method"] == "S2":
        request = SkillStepCandidateRequest(model_id=model_id, skill_id=feedback["skill_id"], **common)
        return generate_skill_step_candidate(request, tenant, user, **provenance)
    request = PromptCandidateRequest(model_id=model_id, agent_id=feedback["agent_id"],
        version_no=feedback["version_no"], method=feedback["method"], **common)
    return generate_prompt_candidate(request, tenant, user, **provenance)
