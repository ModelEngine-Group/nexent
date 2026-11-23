# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Paired development trials on a dedicated, fixture-backed AgentOS Runtime."""

import asyncio
import json
import logging
import re
from collections import Counter
from contextlib import ExitStack, asynccontextmanager

from backend.http.client import create_httpx_client
from contracts.agentos import EvaluationAgentRun
from contracts.constants.environment import EVOLUTION_REPLAY_RUNTIME_URL
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution import DevelopmentExperimentRequest
from infrastructure.agentos_client import AgentOSClient
from management.db.conversation.evolution_review import recent_reviews
from management.db.evaluation import experiments as jobs
from management.db.evaluation.candidates import prompt_example_sources
from management.db.evaluation.evaluator import get_evaluator
from management.db.evaluation.replay_cases import task_digest
from management.services.agent.preparation.evaluation_snapshot import prepare_evaluation_snapshot
from management.services.evaluation.evolution_access import published_business_agent, require_business_agent_edit
from management.services.evaluation.example_candidates import example_source_keys
from management.services.evaluation.replay_cases import get_development_case, remove_trial_inputs, stage_case_input
from management.services.evaluation.scoring import grade_observed_case
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
    options = {}
    if request.candidate_type == "skill_step":
        options = {"skill_candidate_id": request.candidate_id, "skill_variant": "base" if variant == "no_skill" else variant}
    elif variant == "result":
        options = {"prompt_candidate_id": request.candidate_id}
    spec = await prepare_evaluation_snapshot(
        EvaluationAgentRun(agent_id=request.agent_id, version_no=request.version_no, query=""), user, tenant,
        language=request.language, **options)
    if variant == "no_skill":
        spec = spec.model_copy(update={"omit_root_skill_candidate_id": request.candidate_id})
    return spec


async def _excluded_sources(request, tenant):
    if request.candidate_type != "prompt":
        return set()
    return await _io("read-training-sources", prompt_example_sources, tenant, request.agent_id,
                     request.version_no, request.candidate_id)


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
    cases = {}
    for case_id in request.case_ids:
        case = await _io("read-experiment-case", get_development_case, tenant, user, request.agent_id,
                         request.version_no, case_id)
        if excluded.intersection(example_source_keys(case["task"])):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select fresh materials outside the prompt examples")
        cases[str(case_id)] = case["digest"]
    snapshots = {}
    arms = ("base", "result", "no_skill") if request.candidate_type == "skill_step" else ("base", "result")
    for variant in arms:
        spec = await _snapshot(request, tenant, user, variant)
        snapshots[variant] = snapshot_digest(spec)
    plan = {"request": request.model_dump(), "snapshots": snapshots, "cases": cases, "evaluator": rule}
    return await _io("submit-development-experiment", jobs.submit, tenant, user, request, plan)


def experiment_report(tenant, user, eid, *, cancel=False):
    scope = jobs.scope(tenant, eid)
    if scope is None:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Unknown development experiment")
    require_business_agent_edit(scope["agent_id"], tenant, user)
    if cancel:
        jobs.cancel(tenant, eid)
    rows = jobs.trials(tenant, eid)
    pairs = {}
    for row in rows:
        pairs.setdefault(row["case_id"], {})[row["variant"]] = row
    counts = Counter(improved=0, regressed=0, both_pass=0, both_fail=0, inconclusive=0)
    labels = {("fail", "pass"): "improved", ("pass", "fail"): "regressed",
              ("pass", "pass"): "both_pass", ("fail", "fail"): "both_fail"}
    valid_triplets = verified_guide_pairs = 0
    for pair in pairs.values():
        outcome = labels.get((pair["base"]["status"], pair["result"]["status"]), "inconclusive")
        counts[outcome] += 1
        pair["comparison"] = outcome
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
    if states <= {"pending"}:
        status = "pending"
    elif states & {"running", "pending"}:
        status = "running"
    else:
        status = "cancelled" if "cancelled" in states else "finished"
    return {"experiment_id": eid, **scope, "status": status, "total_pairs": len(pairs),
            **({"valid_triplets": valid_triplets, "verified_guide_pairs": verified_guide_pairs}
               if any("no_skill" in p for p in pairs.values()) else {}),
            "valid_pairs": len(pairs) - counts["inconclusive"], "counts": dict(counts), "pairs": pairs}


def workspace_choices(tenant, user, agent_id, version):
    require_business_agent_edit(agent_id, tenant, user)
    published_business_agent(tenant, agent_id, version)
    return {**jobs.workspace_choices(tenant, agent_id, version),
            "reviews": recent_reviews(tenant, agent_id, version)}


def _grade(request, job, task, observed):
    plan = job["plan"]
    eid = request.evaluator_id
    closed = any(e.get("type") == "final_answer" for e in observed.events)
    rule = plan["evaluator"]
    system = compose_auxiliary_prompt(request.language, "evaluation_judge").system if rule["evaluator_type"] != "code" else ""
    return grade_observed_case(
        {eid: rule}, tenant_id=job["tenant_id"], user_id=job["created_by"], query=task["query"],
        expected=task["expected"], actual=observed.answer if closed else None, runtime_events=observed.events,
        required_evidence={eid: {"actual", "expected"}}, judge_model_id=request.judge_model_id, judge_system_prompt=system,
    )[eid]


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
    client = AgentOSClient(EVOLUTION_REPLAY_RUNTIME_URL, create_httpx_client)
    stack = ExitStack()
    stage = asyncio.create_task(_io("stage-development-input", stack.enter_context, stage_case_input(*args, job["receipt_id"])))
    try:
        try:
            inputs = await asyncio.shield(stage)
        except asyncio.CancelledError:
            await stage
            raise
        payload = spec.model_copy(update={"input": inputs, "conversation_id": -job["trial_id"],
                                          "replay_trial_id": job["receipt_id"]})
        observed = await client.run_prepared_evaluation(payload, user, tenant)
    finally:
        await _io("release-development-input", stack.close)
    receipt = observed.replay_receipt
    if not receipt or receipt.trial_id != job["receipt_id"]:
        return "invalid", {"error": "missing_or_unsuccessful_runtime_receipt"}
    if receipt.outcome != "completed":
        return "invalid", {"error": "unsuccessful_runtime", "runtime_outcome": receipt.outcome}
    skill = receipt.skill
    if "no_skill" in job["plan"]["snapshots"]:
        target = next((ref for ref in spec.resource.skill_refs if ref.package_candidate_id == request.candidate_id), None)
        omitted = job["variant"] == "no_skill"
        if (not target or not skill or skill.candidate_id != request.candidate_id or skill.instance_id != target.instance_id
                or skill.variant != job["variant"] or skill.mounted_revision != (None if omitted else target.revision)
                or omitted and (skill.listed or skill.guide_reads)):
            return "invalid", {"error": "skill_observation_mismatch"}
    await _io("recheck-development-experiment", require_business_agent_edit, request.agent_id, tenant, user)
    grade = await run_blocking("grade-development-trial", _grade, request, job, case["task"], observed,
                               lane="evaluation", owner="management")
    return grade["status"], {"judgment": grade, "answer": observed.answer, "event_count": len(observed.events),
                             **({"skill": skill.model_dump()} if skill else {}),
                             "reported_step_input_tokens": reported_step_input_tokens(observed.events),
                             "events_digest": task_digest(observed.events), "case_digest": case["digest"],
                             "snapshot_digest": digest, "evaluator_version": job["plan"]["evaluator"]["version_no"]}


async def _work_one(job):
    budget = DevelopmentExperimentRequest.model_validate(job["plan"]["request"]).timeout_seconds
    trial = asyncio.create_task(asyncio.wait_for(execute_trial(job), timeout=budget))
    try:
        while not trial.done():
            done, _ = await asyncio.wait({trial}, timeout=20)
            if not done and not await _io("heartbeat-development-trial", jobs.heartbeat, job):
                return
        status, result = trial.result()
    except TimeoutError:
        status, result = "error", {"error": "time_budget_exceeded"}
    except Exception as exc:
        status, result = "error", {"error": type(exc).__name__}
        logger.warning("Development trial %s failed (%s)", job["trial_id"], type(exc).__name__)
    finally:
        if not trial.done():
            trial.cancel()
            await asyncio.gather(trial, return_exceptions=True)
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
