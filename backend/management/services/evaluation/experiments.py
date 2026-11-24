# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Paired development trials on a dedicated, fixture-backed AgentOS Runtime."""

import asyncio
import json
import logging
import re
import time
from collections import Counter
from contextlib import ExitStack, asynccontextmanager

from backend.http.client import create_httpx_client
from contracts.agentos import EvaluationAgentRun, NewSkillTrial, ToolSetCheck
from contracts.constants.environment import EVOLUTION_REPLAY_RUNTIME_URL
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution import DevelopmentExperimentRequest, DevelopmentRunBudget
from contracts.evolution_metering import evaluation_budget
from contracts.evaluation_answer import has_completed_root_answer
from infrastructure.agentos_client import AgentOSClient
from infrastructure.rdb.skill_candidate_records import read_bound_skill_candidate, read_new_skill_trial
from management.db.conversation.evolution_review import recent_review_batches, recent_reviews
from management.db.evaluation import experiments as jobs
from management.db.evaluation.candidates import prompt_example_sources
from management.db.evaluation.evaluator import get_evaluator
from management.db.evaluation.replay_cases import regression_members, task_digest
from management.services.agent.preparation.evaluation_snapshot import prepare_evaluation_snapshot
from management.services.evaluation.evolution_access import published_business_agent, require_business_agent_edit
from management.services.evaluation.example_candidates import example_source_keys
from management.services.evaluation.replay_cases import (
    freeze_regression_members, get_development_case, remove_trial_inputs, require_trace_baseline, stage_case_input,
)
from management.services.evaluation.scoring import grade_observed_case
from management.services.evaluation.judge_binding import judge_binding, judges_for_plan
from management.services.evaluation.screening import screen_development
from management.services.evaluation.skill_candidates import pin_skill_candidate
from management.services.evaluation.replay_dialogue import judge_file_state, run_turns, skill_evidence
from management.services.evaluation.tool_use import judge_dialogue_tools
from management.services.evaluation.tool_set_candidates import resolve_tool_set
from nexent.core.agents.prompt.auxiliary import compose_auxiliary_prompt
from nexent.core.concurrency import run_blocking

logger = logging.getLogger(__name__)


def snapshot_digest(snapshot):
    """Normalize compiler-local model aliases while retaining every model revision and binding."""
    spec = snapshot.model_dump(mode="json")
    models = spec["models"]
    aliases = {}
    for index, model in enumerate([models["llm"], *models.get("additional_llms", [])]):
        alias = model["alias"]
        if re.fullmatch(r"agent_model_[a-f0-9]{32}", alias):
            aliases[alias] = f"__frozen_model_{index}"
            model["alias"] = aliases[alias]

    def normalize(resource):
        if resource["model_alias"] in aliases:
            resource["model_alias"] = aliases[resource["model_alias"]]
        for child in resource["subagents"]:
            normalize(child)

    normalize(spec["resource"])
    return task_digest(spec)


async def _io(name, fn, *args):
    return await run_blocking(name, fn, *args, lane="control-io", owner="management")


async def _snapshot(request, tenant, user, variant):
    if request.components:
        return await _combination_snapshot(request, tenant, user, variant)
    options = {}
    if request.candidate_type in {"skill_step", "skill_discovery", "skill_script"}:
        options = {"skill_candidate_id": request.candidate_id, "skill_variant": "base" if variant == "no_skill" else variant}
    elif request.candidate_type == "prompt" and variant == "result":
        options = {"prompt_candidate_id": request.candidate_id}
    spec = await prepare_evaluation_snapshot(
        EvaluationAgentRun(agent_id=request.agent_id, version_no=request.version_no, query=""), user, tenant,
        language=request.language, **options)
    if request.candidate_type == "tool_build":
        from management.services.evaluation.tool_build_candidate import pin_build
        return await _io("pin-reviewed-tool-build", pin_build, spec, tenant, request.candidate_id, variant)
    if request.candidate_type == "tool_mapping":
        from management.services.evaluation.tool_mapping_candidates import pin_mapping
        return await _io("pin-tool-mapping", pin_mapping, spec, tenant, request.candidate_id, snapshot_digest(spec), variant)
    if request.candidate_type == "tool_set":
        removed = await _io("resolve-tool-set", resolve_tool_set, tenant, request.agent_id, request.version_no,
                            request.candidate_id, spec, snapshot_digest(spec))
        if variant == "result":
            spec = await prepare_evaluation_snapshot(
                EvaluationAgentRun(agent_id=request.agent_id, version_no=request.version_no, query=""), user, tenant,
                language=request.language, excluded_root_tools=frozenset(removed))
        spec = spec.model_copy(update={"tool_set_check": ToolSetCheck(arm=variant, removed=removed)})
    if variant == "no_skill":
        spec = spec.model_copy(update={"omit_root_skill_candidate_id": request.candidate_id})
    if request.candidate_type == "skill_new":
        proposal = await _new_skill_proposal(request, tenant)
        baseline = spec.model_copy(update={"observe_root_skill_choices": True})
        if snapshot_digest(baseline) != proposal["baseline_digest"]:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The source Agent changed after drafting the Skill")
        trial = NewSkillTrial(candidate_id=request.candidate_id, name=proposal["name"],
                              digest=proposal["digest"], arm=variant)
        spec = spec.model_copy(update={"new_skill_trial": trial})
    if request.candidate_type in {"baseline", "skill_discovery", "skill_new"}:
        spec = spec.model_copy(update={"observe_root_skill_choices": True})
    return spec


async def _combination_snapshot(request, tenant, user, arm):
    active = {"base": (False, False), "only_a": (True, False), "only_b": (False, True), "result": (True, True)}[arm]
    run = EvaluationAgentRun(agent_id=request.agent_id, version_no=request.version_no, query="")
    options = {}
    skill_parts = []
    tool_check = None
    for part, changed in zip(request.components, active, strict=True):
        if part.candidate_type.startswith("skill_"):
            skill_parts.append((part, "result" if changed else "base"))
        elif part.candidate_type == "prompt" and changed:
            options["prompt_candidate_id"] = part.candidate_id
        elif part.candidate_type == "tool_set":
            released = await prepare_evaluation_snapshot(run, user, tenant, language=request.language)
            removed = await _io("resolve-combined-tool-set", resolve_tool_set, tenant, request.agent_id,
                                request.version_no, part.candidate_id, released, snapshot_digest(released))
            tool_check = ToolSetCheck(arm="result" if changed else "base", removed=removed)
            if changed:
                options["excluded_root_tools"] = frozenset(removed)
    spec = await prepare_evaluation_snapshot(run, user, tenant, language=request.language, **options)
    for part, variant in skill_parts:
        await _io("pin-combined-skill", pin_skill_candidate, spec.resource, tenant, part.candidate_id, variant)
    if tool_check:
        spec = spec.model_copy(update={"tool_set_check": tool_check})
    if any(part.candidate_type == "skill_discovery" for part, _ in skill_parts):
        spec = spec.model_copy(update={"observe_root_skill_choices": True})
    return spec


async def _check_components(request, tenant, user):
    skill_instances = set()
    for part in request.components:
        plan = await _io("load-single-component", jobs.read_plan, tenant, part.experiment_id, True)
        source = (plan or {}).get("request", {})
        if (source.get("agent_id"), source.get("version_no"), source.get("candidate_type"), source.get("candidate_id")) != (
                request.agent_id, request.version_no, part.candidate_type, part.candidate_id):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select single experiments for this released Agent")
        rows = await _io("read-component-results", jobs.trials, tenant, part.experiment_id)
        valid = set()
        for row in rows:
            if not row["receipt_id"] or row["status"] not in {"pass", "fail"}:
                continue
            case_digest = plan["cases"].get(str(row["case_id"]))
            arm_digest = plan["snapshots"].get(row["variant"])
            result = row["result"] or {}
            if (case_digest and arm_digest and result.get("case_digest") == case_digest
                    and result.get("snapshot_digest") == arm_digest):
                valid.add((row["case_id"], row["variant"]))
        if (any(r["status"] in {"pending", "running", "cancelled"} for r in rows)
                or not any((cid, "base") in valid for cid, arm in valid if arm == "result")):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Finish both single experiments with a graded pair")
        if part.candidate_type.startswith("skill_"):
            binding = await _io("check-combined-skill-binding", read_bound_skill_candidate, tenant, request.agent_id,
                                request.version_no, part.candidate_id)
            if not binding or binding["instance_id"] in skill_instances:
                raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select two different resource bindings")
            skill_instances.add(binding["instance_id"])
        for arm in ("base", "result"):
            compiled = await _snapshot(DevelopmentExperimentRequest.model_validate(source), tenant, user, arm)
            if source.get("language", "zh") != request.language or snapshot_digest(compiled) != plan["snapshots"][arm]:
                raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "A component changed since its single experiment")


async def _new_skill_proposal(request, tenant):
    proposal = await _io("read-proposed-skill", read_new_skill_trial, tenant, request.agent_id,
                         request.version_no, request.candidate_id)
    if not proposal:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "New Skill proposal is outside this Agent version")
    return proposal


async def _excluded_sources(request, tenant):
    if request.candidate_type == "tool_build":
        from management.services.evaluation.tool_build_candidate import verified_build
        _, feedback = await _io("read-verified-build-sources", verified_build, tenant, request.agent_id,
                                request.version_no, request.candidate_id)
        return set(feedback["source_keys"])
    if request.candidate_type == "tool_mapping":
        return await _io("mapping-example-sources", prompt_example_sources, tenant, request.agent_id,
                         request.version_no, request.candidate_id, "agent.tool_format", "T2_MAPPING")
    if request.candidate_type == "skill_new":
        return set((await _new_skill_proposal(request, tenant))["source_keys"])
    if request.components:
        prompt = next((p for p in request.components if p.candidate_type == "prompt"), None)
        if not prompt:
            return set()
        candidate_id = prompt.candidate_id
    elif request.candidate_type == "prompt":
        candidate_id = request.candidate_id
    else:
        return set()
    return await _io("read-training-sources", prompt_example_sources, tenant, request.agent_id,
                     request.version_no, candidate_id)


async def create_experiment(request, tenant, user):
    await _io("authorize-development-experiment", require_business_agent_edit, request.agent_id, tenant, user)
    existing = await _io("read-experiment-submission", jobs.previous_submission, tenant, user, request)
    if existing is not None:
        return existing
    if request.suggestion_id is not None and request.suggestion_target_case_id is None:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select the target task for this suggestion")
    if not EVOLUTION_REPLAY_RUNTIME_URL:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Configure the isolated replay Runtime before starting a trial")
    rule = await _io("read-experiment-evaluator", get_evaluator, request.evaluator_id, tenant)
    if not rule or rule["status"] != "PUBLISHED":
        raise AppException(ErrorCode.AGENT_EVALUATION_EVALUATOR_NOT_PUBLISHED)
    if rule["evaluator_type"] != "code" and request.judge_model_id is None:
        raise AppException(ErrorCode.COMMON_PARAMETER_INVALID, "Select a judge model for this evaluator")
    excluded = await _excluded_sources(request, tenant)
    if request.components:
        await _check_components(request, tenant, user)
    script_build = None
    if request.candidate_type in {"skill_step", "skill_discovery", "skill_script"}:
        bound = await _io("verify-skill-method", read_bound_skill_candidate, tenant, request.agent_id,
                          request.version_no, request.candidate_id)
        method = {"skill_discovery": "S1", "skill_step": "S2", "skill_script": "S4"}[request.candidate_type]
        if not bound or bound["method"] != method:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Choose the experiment matching the Skill candidate")
        if method == "S4":
            script_build = bound["script_build"]
            excluded.update(script_build["source_keys"])
    fixed = {}
    if request.candidate_type != "baseline":
        fixed = await _io("freeze-fixed-regression-suite", freeze_regression_members, tenant, user,
                          request.agent_id, request.version_no)
    if request.screening and set(request.screening.target_case_ids).intersection(map(int, fixed)):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select development targets outside the fixed regression suite")
    source_cases = script_build["source_cases"] if script_build else []
    if set(source_cases).intersection([*request.case_ids, *map(int, fixed)]):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Keep original script examples separate from fresh tasks and regression")
    cases = {}
    replay_turns = 0
    trace_baseline_digest = None
    development_sources, fixed_sources = set(), set()
    proposed_name = (await _new_skill_proposal(request, tenant))["name"] if request.candidate_type == "skill_new" else None
    applicable = set()
    for case_id in dict.fromkeys([*request.case_ids, *map(int, fixed), *source_cases]):
        case = await _io("read-experiment-case", get_development_case, tenant, user, request.agent_id,
                         request.version_no, case_id)
        replay_turns += 1 + len(case["task"].get("followups") or [])
        sources = example_source_keys(case["task"])
        if request.candidate_type != "baseline" and str(case_id) not in fixed and case["task"].get("trace_source"):
            if trace_baseline_digest is None:
                baseline = request.model_copy(update={"components": None, "candidate_id": None, "candidate_type": "baseline"})
                trace_baseline_digest = snapshot_digest(await _snapshot(baseline, tenant, user, "base"))
            await _io("verify-reproduced-trace-case", require_trace_baseline, tenant, request.agent_id,
                      request.version_no, case, rule, request.language, request.judge_model_id, trace_baseline_digest)
        if case_id not in source_cases and excluded.intersection(sources):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select fresh materials outside the examples used to generate the candidate")
        if (request.evaluates_skill_choices() and case_id in request.case_ids
                and case["task"].get("expected_skill_names") is None):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Label the acceptable Skill choices for each task")
        if proposed_name and case_id in request.case_ids and str(case_id) not in fixed:
            if not any(k.startswith(("group:", "file:", "conversation:", "file-state:")) for k in sources):
                raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Identify the source material of each new Skill test")
            applicable.add(proposed_name in case["task"]["expected_skill_names"])
        cases[str(case_id)] = case["digest"]
        if str(case_id) in fixed and case["digest"] != fixed[str(case_id)]["digest"]:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Fixed regression task no longer matches its source")
        if str(case_id) in fixed:
            fixed_sources.update(sources)
        else:
            development_sources.update(sources)
    if proposed_name and applicable != {True, False}:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Include an unseen task for the new Skill and an unseen task outside its scope")
    if development_sources & fixed_sources:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Choose development materials outside the fixed regression suite")
    snapshots = {}
    arms = {"baseline": ("base",), "skill_step": ("base", "result", "no_skill"),
            "combination": ("base", "only_a", "only_b", "result")}.get(
        request.candidate_type, ("base", "result"))
    budget = request.budget or DevelopmentRunBudget()
    planned_turns = replay_turns * len(arms)
    if planned_turns > budget.max_replay_turns:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR,
                           f"Experiment requires {planned_turns} replay turns; budget allows {budget.max_replay_turns}")
    allowance = evaluation_budget(tenant)
    if allowance is None and (budget.max_model_tokens is not None or budget.max_model_micros is not None):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Configure evaluation model tariffs before setting model budgets")
    billable_models = set()
    if allowance:
        if rule["evaluator_type"] != "code":
            billable_models.add(request.judge_model_id)
        billable_models.update(member["scoring"]["judge_model_id"] for member in fixed.values()
                               if member["scoring"]["evaluator"]["evaluator_type"] != "code")
    bindings_by_arm = {}
    for variant in arms:
        spec = await _snapshot(request, tenant, user, variant)
        snapshots[variant] = snapshot_digest(spec)
        if allowance:
            billable_models.update(ref.model_id for ref in [spec.models.llm, *spec.models.additional_llms])
        if request.candidate_type in {"tool_mapping", "tool_build"}:
            bindings_by_arm[variant] = spec.resource
    plan = {"request": request.model_dump(), "snapshots": snapshots, "cases": cases, "evaluator": rule}
    plan["budget"] = {**budget.model_dump(), "planned_replay_turns": planned_turns}
    if allowance:
        if any(str(model) not in allowance.models for model in billable_models):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Configure billing ceilings for every replay and judge model")
        plan["metering"] = dict(
            revision=allowance.revision(),
            max_model_tokens=min(allowance.daily_tokens, budget.max_model_tokens or allowance.daily_tokens),
            max_model_micros=min(allowance.daily_micros,
                                 allowance.daily_micros if budget.max_model_micros is None else budget.max_model_micros),
        )
    if script_build:
        plan["script_build"] = script_build
    if request.candidate_type == "tool_mapping":
        from management.services.evaluation.tool_mapping_candidates import mapping_difference
        plan["tool_mapping"] = mapping_difference(bindings_by_arm["base"], bindings_by_arm["result"])
    if request.candidate_type == "tool_build":
        from management.services.evaluation.tool_build_candidate import build_difference
        plan["tool_build"] = build_difference(bindings_by_arm["base"], bindings_by_arm["result"])
    if request.screening:
        plan["judges"] = await _io("freeze-development-judges", judges_for_plan, tenant, rule, request, fixed)
    if request.candidate_type != "baseline":
        plan["regression_cases"] = fixed
    return await _io("submit-development-experiment", jobs.submit, tenant, user, request, plan)


def regression_coverage(frozen, pairs, arms=("base", "result")):
    failed, incomplete = [], []
    for key in frozen:
        case_id = int(key)
        pair = pairs.get(case_id, {})
        candidate = pair.get("result", {}).get("status")
        if any(pair.get(arm, {}).get("status") not in {"pass", "fail"} for arm in arms):
            incomplete.append(case_id)
        elif candidate == "fail":
            failed.append(case_id)
    return {"case_ids": sorted(map(int, frozen)), "failed": sorted(failed), "incomplete": sorted(incomplete)}


def combination_effect(pair, labels):
    base, a, b, combined = (pair.get(arm, {}).get("status") for arm in ("base", "only_a", "only_b", "result"))
    effect = "unchanged_or_shared"
    if any(s not in {"pass", "fail"} for s in (base, a, b, combined)):
        effect = "inconclusive"
    elif combined == "fail" and "pass" in (a, b):
        effect = "lost_single_pass"
    elif base == "fail" and combined == "pass":
        effect = "retained_single_gain" if "pass" in (a, b) else "joint_only"
    return {"effect": effect, "a_vs_base": labels.get((base, a), "inconclusive"),
            "b_vs_base": labels.get((base, b), "inconclusive"),
            "combined_vs_a": labels.get((a, combined), "inconclusive"),
            "combined_vs_b": labels.get((b, combined), "inconclusive")}


def experiment_report(tenant, user, eid, *, cancel=False):
    scope = jobs.scope(tenant, eid)
    if scope is None:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Unknown development experiment")
    require_business_agent_edit(scope["agent_id"], tenant, user)
    if cancel:
        jobs.cancel(tenant, eid)
    fixed = scope.get("regression_cases")
    rows = jobs.trials(tenant, eid)
    pairs = {}
    for row in rows:
        pairs.setdefault(row["case_id"], {})[row["variant"]] = row
    for key in scope.get("planned_cases", fixed or {}):
        pair = pairs.setdefault(int(key), {})
        for arm in scope.get("planned_arms", ("base", "result")):
            pair.setdefault(arm, {"status": "missing_evidence", "result": {"error": "missing_planned_trial"}})
    counts = Counter(improved=0, regressed=0, both_pass=0, both_fail=0, inconclusive=0)
    labels = {("fail", "pass"): "improved", ("pass", "fail"): "regressed",
              ("pass", "pass"): "both_pass", ("fail", "fail"): "both_fail"}
    valid_triplets = verified_guide_pairs = 0
    effects = Counter()
    valid_baselines = 0
    selection_counts = {}
    for pair in pairs.values():
        for arm, row in pair.items():
            selection = (row.get("result") or {}).get("selection")
            if selection and row["status"] in {"pass", "fail"}:
                selection_counts.setdefault(arm, Counter())[selection["outcome"]] += 1
        if "base" not in pair:
            counts["inconclusive"] += 1
            pair["comparison"] = "inconclusive"
            continue
        if "result" not in pair:
            valid_baselines += int(pair["base"]["status"] in {"pass", "fail"})
            pair["comparison"] = "baseline_only"
            continue
        outcome = labels.get((pair["base"]["status"], pair["result"]["status"]), "inconclusive")
        counts[outcome] += 1
        pair["comparison"] = outcome
        if scope.get("components"):
            pair["combination"] = combination_effect(pair, labels)
            effects[pair["combination"]["effect"]] += 1
        if "no_skill" in pair:
            control = pair["no_skill"]["status"]
            complete = outcome != "inconclusive" and control in {"pass", "fail"}
            valid_triplets += int(complete)
            if complete and all(((pair[arm]["result"] or {}).get("skill") or {}).get("guide_reads", 0) > 0
                                for arm in ("base", "result")):
                verified_guide_pairs += 1
            pair["skill_vs_absent"] = {
                arm: labels[(control, pair[arm]["status"])] if complete else "inconclusive" for arm in ("base", "result")
            }
    states = {row["status"] for row in rows}
    if states == {"pending"}:
        status = "pending"
    elif states & {"running", "pending"}:
        status = "running"
    else:
        status = "cancelled" if "cancelled" in states else "finished"
    pair_count = sum("result" in p for p in pairs.values())
    decision = {}
    if scope.get("screening"):
        plan = jobs.read_plan(tenant, eid)
        decision["screening"] = screen_development(plan, pairs, cancelled=scope["cancelled"] or cancel)
    if scope.get("metering"):
        meter = scope["metering"]
        decision["model_budget"] = {
            **{k: meter[k] for k in ("max_model_tokens", "max_model_micros")},
            **(jobs.model_budget_report(tenant, eid) or {}),
        }
    return {"experiment_id": eid, "agent_id": scope["agent_id"], "version_no": scope["version_no"],
            **decision,
            **({"budget": {**scope["budget"], "deadline": scope["deadline"],
                           "expired_trials": sum((row.get("result") or {}).get("error") == "experiment_time_budget_exceeded"
                                                 for row in rows)}} if scope.get("budget") else {}),
            **({"script_source_cases": scope["script_source_cases"]} if scope.get("script_source_cases") else {}),
            **({"fixed_regression": regression_coverage(fixed, pairs, ("base", "only_a", "only_b", "result")
                                                       if scope.get("components") else ("base", "result"))}
               if fixed is not None else {}),
            **({"components": scope["components"], "valid_quartets": sum(effects.values()) - effects["inconclusive"],
                "combination_counts": dict(effects)} if scope.get("components") else {}),
            "status": status, "total_pairs": pair_count,
            "total_tasks": len(pairs), "valid_baselines": valid_baselines, "selection_counts": selection_counts,
            **({"valid_triplets": valid_triplets, "verified_guide_pairs": verified_guide_pairs}
               if any("no_skill" in p for p in pairs.values()) else {}),
            "valid_pairs": pair_count - counts["inconclusive"], "counts": dict(counts), "pairs": pairs}


def workspace_choices(tenant, user, agent_id, version):
    require_business_agent_edit(agent_id, tenant, user)
    published_business_agent(tenant, agent_id, version)
    fixed = regression_members(tenant, agent_id)
    for member in fixed:
        scoring = member.pop("scoring")
        if scoring:
            rule = scoring["evaluator"]
            member["rubric"] = {"name": rule["name"], "version_no": rule["version_no"]}
    return {**jobs.workspace_choices(tenant, agent_id, version), "fixed_regression": fixed,
            "model_budget_available": evaluation_budget(tenant) is not None,
            "reviews": recent_reviews(tenant, agent_id, version),
            "review_batches": recent_review_batches(tenant, agent_id, version)}


def _grade(request, job, task, observed):
    plan = job["plan"]
    scoring = (plan.get("regression_cases", {}).get(str(job.get("case_id"))) or {}).get("scoring")
    rule = scoring["evaluator"] if scoring else plan["evaluator"]
    eid = rule["evaluator_id"] if scoring else request.evaluator_id
    closed = has_completed_root_answer(observed.events)
    language = scoring["language"] if scoring else request.language
    judge_model_id = scoring["judge_model_id"] if scoring else request.judge_model_id
    frozen_judges = plan.get("judges")
    def judge_matches():
        return (frozen_judges is None or rule["evaluator_type"] == "code" or
                frozen_judges.get(f"{judge_model_id}/{language}") == judge_binding(job["tenant_id"], judge_model_id, language))
    changed = {"status":"invalid","reason":"judge_binding_changed","evaluator_id":eid,"evaluator_version":rule.get("version_no")}
    if not judge_matches():
        return changed
    system = compose_auxiliary_prompt(language, "evaluation_judge").system if rule["evaluator_type"] != "code" else ""
    grade = grade_observed_case(
        {eid: rule}, tenant_id=job["tenant_id"], user_id=job["created_by"], query=task["query"],
        expected=task["expected"], actual=observed.answer if closed else None, runtime_events=observed.events,
        required_evidence={eid: {"actual", "expected"}}, judge_model_id=judge_model_id, judge_system_prompt=system,
        **({"evaluation_attempt": job["evaluation_attempt"]} if job.get("evaluation_attempt") else {}),
    )[eid]
    if not judge_matches():
        return changed
    return {**grade, "evaluator_id": eid, "evaluator_version": rule.get("version_no")}


def reported_step_input_tokens(events):
    """Sum per-step input counters; summaries and estimates cannot substitute for usage."""
    counts = {}
    for event in events:
        if event.get("type") != "token_count":
            continue
        payload = event.get("content")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                return None
        if not isinstance(payload, dict):
            return None
        if "step_number" not in payload and "step_input_tokens" not in payload:
            continue
        step, tokens = payload.get("step_number"), payload.get("step_input_tokens")
        if type(step) is not int or step < 0 or type(tokens) is not int or tokens < 0:
            return None
        key = (event.get("invocation_id"), event.get("agent_id"), step)
        if any(value is not None and type(value) not in (str, int) for value in key[:2]) or key in counts:
            return None
        counts[key] = tokens
    return sum(counts.values()) if counts else None


def judge_skill_selection(expected, reads):
    unexpected = sorted(set(reads).difference(expected))
    if unexpected:
        outcome = "wrong"
    elif reads:
        outcome = "hit"
    else:
        outcome = "missed" if expected else "correct_skip"
    return {"expected": expected, "reads": reads, "unexpected": unexpected, "outcome": outcome}


async def execute_trial(job):
    request = DevelopmentExperimentRequest.model_validate(job["plan"]["request"])
    tenant, user = job["tenant_id"], job["created_by"]
    args = (tenant, user, request.agent_id, request.version_no, job["case_id"])
    case = await _io("load-frozen-development-case", get_development_case, *args)
    # An identical prompt can acquire more source evidence while the trial is queued.
    excluded = await _excluded_sources(request, tenant)
    if excluded.intersection(example_source_keys(case["task"])):
        return "invalid", {"error": "example_source_overlap"}
    digest = job["plan"]["snapshots"][job["variant"]]
    spec = await _snapshot(request, tenant, user, job["variant"])
    if case["digest"] != job["plan"]["cases"][str(job["case_id"])] or snapshot_digest(spec) != digest:
        return "invalid", {"error": "frozen_input_changed"}
    if job["plan"].get("metering"):
        attempt = await _io("authorize-trial-model-budget", jobs.authorize_model_attempt, job, request.timeout_seconds)
        if not attempt:
            return "invalid", {"error": "experiment_model_budget_unavailable"}
        job = {**job, "evaluation_attempt": attempt}

    async def before_dispatch(turn_index):
        await _io("recheck-development-experiment", require_business_agent_edit, request.agent_id, tenant, user)
        if not await _io("authorize-development-dispatch", jobs.authorize_dispatch, job, turn_index):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Development trial is no longer authorized to dispatch")

    client = AgentOSClient(EVOLUTION_REPLAY_RUNTIME_URL, create_httpx_client)
    return await run_verified_arm(
        request, job, case, spec, client, lambda index: stage_case_input(*args, job["receipt_id"], index),
        before_dispatch=before_dispatch,
    )


async def run_verified_arm(request, job, case, spec, client, stage_input, *, before_dispatch=None):
    """Execute and grade one verified arm; the caller owns the evidence and storage scope."""
    tenant, user = job["tenant_id"], job["created_by"]
    digest = job["plan"]["snapshots"][job["variant"]]
    stack = ExitStack()
    async def load_input(index):
        stage = asyncio.create_task(_io("stage-development-input", stack.enter_context,
                                        stage_input(index)))
        try:
            return await asyncio.shield(stage)
        except asyncio.CancelledError:
            await stage
            raise
    try:
        task = case["task"]
        if request.candidate_type == "skill_script" and task.get("tool_use"):
            rules = [{**rule, "expected_script_files": rule.get("expected_script_files") or {}}
                     if rule["name"] == "run_skill_script" and rule.get("expected_script_stdout") is not None else rule
                     for rule in task["tool_use"]["rules"]]
            task = {**task, "tool_use": {**task["tool_use"], "rules": rules}}
        started = time.monotonic_ns()
        observations, turns, error = await run_turns(
            client, spec, task, load_input, job, user, tenant, before_dispatch=before_dispatch,
        )
        execution_ms = (time.monotonic_ns() - started + 999999) // 1000000
    finally:
        await _io("release-development-input", stack.close)
    dialogue = {"turns": turns} if turns else {}
    if error:
        return "invalid", {**error, **dialogue}
    await _io("recheck-development-experiment", require_business_agent_edit, request.agent_id, tenant, user)
    final = observations[-1]
    events = [e for obs in observations for e in obs.events]
    grading_task = task
    if turns:
        # Rubrics see the conversation leading to the final deliverable. The runtime never sees the rubric.
        messages = [message for turn in turns for message in
                    ({"role": "user", "content": turn["query"]}, {"role": "assistant", "content": turn["answer"]})]
        grading_task = {**task, "query": json.dumps(messages[:-1], ensure_ascii=False)}
    grade = await run_blocking("grade-development-trial", _grade, request, job, grading_task,
                               final.model_copy(update={"events": events}), lane="evaluation", owner="management")
    if job.get("evaluation_attempt") and grade["status"] == "invalid" and not getattr(spec, "confirmation_bucket", None):
        usage = await _io("read-trial-budget-state", jobs.model_budget_report, tenant, job["experiment_id"])
        if usage and usage["stopped_reason"]:
            return "invalid", {"error": usage["stopped_reason"], "judgment": grade, **dialogue}
    receipts = [obs.replay_receipt for obs in observations]
    receipt = receipts[-1]
    skills, reads = skill_evidence(receipts)
    selection = None
    if spec.observe_root_skill_choices and task.get("expected_skill_names") is not None:
        selection = judge_skill_selection(task["expected_skill_names"], reads)
    catalog = receipt.tool_catalog
    if catalog and turns:
        catalogs = [r.tool_catalog for r in receipts]
        catalog = catalog.model_copy(update={field: sorted({name for c in catalogs for name in getattr(c, field)})
            for field in ("schema_tools", "executable", "instruction_mentions", "native_definitions", "prompt_tools")}
            | {"model_inputs": sum(c.model_inputs for c in catalogs)})
    tool_grade = None
    if task.get("tool_use"):
        published = await _io("read-released-tool-exclusions", published_business_agent,
                              tenant, spec.resource.agent_id, spec.resource.version_no)
        absent = set(published.get("released_tool_exclusions") or ())
        if spec.tool_set_check and spec.tool_set_check.arm == "result":
            absent.update(spec.tool_set_check.removed)
        tool_grade = judge_dialogue_tools(task["tool_use"], [r.tool_observation for r in receipts], absent=absent)
    usage = [reported_step_input_tokens(obs.events) for obs in observations]
    status = grade["status"]
    if tool_grade and status in {"pass", "fail"} and tool_grade["status"] != "pass":
        status = tool_grade["status"]
    file_grade = judge_file_state(task["file_state"], receipts) if task.get("file_state") else None
    if file_grade and status == "pass":
        status = file_grade["status"]
    trace_review = {}
    source = case["task"].get("trace_source")
    if request.candidate_type == "baseline" and source:
        outcomes = {
            ("reproduce", "fail"): "reproduced", ("reproduce", "pass"): "not_reproduced",
            ("protect", "pass"): "protection_passed", ("protect", "fail"): "protection_failed",
        }
        trace_review["trace_baseline_outcome"] = outcomes.get((source["purpose"], status), "inconclusive")
    return status, {"judgment": grade, "answer": final.answer, "event_count": len(events), "execution_ms":execution_ms, **dialogue,
                             **trace_review,
                             **({"new_skill_trial": receipt.new_skill_trial.model_dump()} if getattr(receipt, "new_skill_trial", None) else {}),
                             **({"tool_use": tool_grade} if tool_grade else {}),
                             **({"file_state": file_grade} if file_grade else {}),
                             **({"tool_catalog": catalog.model_dump()} if catalog else {}),
                             **({"guide_reads": reads} if request.candidate_type == "baseline"
                                and reads is not None else {}),
                             **({"skill": skills[0]} if receipt.skill else {}),
                             **({"skills": skills} if receipt.skills else {}),
                             **({"selection": selection} if selection else {}),
                             "reported_step_input_tokens": sum(usage) if None not in usage else None,
                             "events_digest": task_digest(events), "case_digest": case["digest"],
                             "snapshot_digest": digest, "evaluator_id": grade["evaluator_id"],
                             "evaluator_version": grade["evaluator_version"]}


async def _work_one(job):
    budget = DevelopmentExperimentRequest.model_validate(job["plan"]["request"]).timeout_seconds
    remaining = job.get("monotonic_deadline")
    if remaining is not None:
        remaining -= time.monotonic()
        if remaining <= 0:
            await _io("expire-development-trial", jobs.finish, job, "error", {"error": "experiment_time_budget_exceeded"})
            return
    overall_limit = remaining is not None and remaining <= budget
    trial = asyncio.create_task(asyncio.wait_for(execute_trial(job), timeout=remaining if overall_limit else budget))
    try:
        while not trial.done():
            done, _ = await asyncio.wait({trial}, timeout=20)
            if not done and not await _io("heartbeat-development-trial", jobs.heartbeat, job):
                return
        status, result = trial.result()
    except TimeoutError:
        status, result = "error", {"error": "experiment_time_budget_exceeded" if overall_limit else "time_budget_exceeded"}
    except Exception as exc:
        status, result = "error", {"error": type(exc).__name__}
        logger.warning("Development trial %s failed (%s)", job["trial_id"], type(exc).__name__)
    finally:
        if not trial.done():
            trial.cancel()
            await asyncio.gather(trial, return_exceptions=True)
    if result.get("error") == "experiment_model_budget_exceeded":
        await _io("stop-metered-experiment", jobs.stop_model_budget, job)
    await _io("finish-development-trial", jobs.finish, job, status, result)


async def _worker():
    while True:
        try:
            cleanup = await _io("claim-replay-cleanup", jobs.claim_cleanup)
            if cleanup:
                await _io("remove-replay-copies", remove_trial_inputs, cleanup["created_by"], cleanup["receipt_id"],
                          cleanup["files"])
                await _io("complete-replay-cleanup", jobs.complete_cleanup, cleanup["trial_id"], cleanup["receipt_id"])
            job = await _io("claim-development-trial", jobs.claim)
            if job:
                await _work_one(job)
                continue
        except Exception as exc:
            logger.warning("Development experiment worker unavailable (%s)", type(exc).__name__)
        await asyncio.sleep(2)


@asynccontextmanager
async def experiment_lifespan():
    worker = asyncio.create_task(_worker()) if EVOLUTION_REPLAY_RUNTIME_URL else None
    try:
        yield
    finally:
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
