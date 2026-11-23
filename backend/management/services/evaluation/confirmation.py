# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Editor submission and curator approval of an immutable independent comparison."""

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution import DevelopmentExperimentRequest
from contracts.evolution_sources import task_digest
from management.db.evaluation import confirmation_locks, experiments as jobs
from management.db.evaluation.evaluator import get_evaluator
from management.db.evaluation.replay_cases import regression_members
from management.services.evaluation import experiments
from management.services.evaluation.evolution_access import require_business_agent_edit
from management.services.evaluation.judge_binding import judges_for_plan
from management.services.evaluation.screening import screen_development
from nexent.core.concurrency import run_blocking


async def _io(name, fn, *args):
    return await run_blocking(name, fn, *args, lane="control-io", owner="management")


def _rubric_content(rule):
    # Creating a new draft only changes the list pointer/timestamp on the old published rubric.
    return {key:value for key,value in rule.items() if key not in {"is_current","update_time"}}


async def verified_recipe(tenant, editor, eid, plan, *, prepared=None):
    request = DevelopmentExperimentRequest.model_validate(plan["request"])
    await _io("authorize-confirmation-candidate", require_business_agent_edit, request.agent_id, tenant, editor)
    if not request.screening:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select an experiment with preregistered screening criteria")
    current = await _io("check-current-regression-suite", regression_members, tenant, request.agent_id)
    tested = {member["digest"]:member["scoring"] for member in plan["regression_cases"].values()}
    if any(member["digest"] not in tested or tested[member["digest"]] != member["scoring"] for member in current):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Run the candidate against the current fixed regression suite")
    rule = await _io("verify-confirmation-rubric", get_evaluator, request.evaluator_id, tenant)
    if not rule or _rubric_content(rule) != _rubric_content(plan["evaluator"]):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The tested evaluator has changed")
    judges = await _io("check-confirmation-judges", judges_for_plan, tenant, rule, request, plan["regression_cases"])
    if judges != plan.get("judges", {}):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The tested judge settings cannot be reproduced")
    snapshots = {}
    for arm in ("base", "result"):
        spec = await experiments._snapshot(request, tenant, editor, arm)
        snapshots[arm] = experiments.snapshot_digest(spec)
        if snapshots[arm] != plan["snapshots"].get(arm):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The compiled resources differ from the tested candidate")
        if prepared is not None:
            prepared[arm] = spec
    return {"format":"nexent-confirmation-candidate-v1", "tenant_id":tenant,"experiment_id":eid,
            **request.model_dump(include={"agent_id","version_no","candidate_type","candidate_id","components",
                                          "language","timeout_seconds","evaluator_id","judge_model_id"}),
            "plan_digest":task_digest(plan),"snapshots":snapshots,"rubric_digest":task_digest(plan["evaluator"]),"judges":judges}


async def nominate_candidate(tenant, editor, eid):
    scope = await _io("read-confirmation-candidate-scope", jobs.scope, tenant, eid)
    if not scope:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    await _io("authorize-confirmation-nomination", require_business_agent_edit, scope["agent_id"], tenant, editor)
    plan = await _io("read-candidate-plan", jobs.read_plan, tenant, eid, True)
    if not plan:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Development experiment is no longer active")
    recipe = await verified_recipe(tenant, editor, eid, plan)
    def submit():
        require_business_agent_edit(scope["agent_id"], tenant, editor)
        with confirmation_locks.nomination_evidence(tenant, eid, recipe["plan_digest"]) as (session, frozen, pairs):
            if screen_development(frozen, pairs, cancelled=False)["status"] != "eligible":
                raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Development screening has not passed")
            return confirmation_locks.save_nomination(session, eid, editor, recipe)
    return await _io("submit-confirmation-candidate", submit)


async def approve_comparison(tenant, curator, suite_id, request):
    row = await _io("authorize-confirmation-lock", confirmation_locks.lock_inputs, tenant, curator, suite_id, request)
    recipe = await verified_recipe(tenant, row["submitted_by"], request.experiment_id, row["plan"])
    return await _io("lock-confirmation-comparison", confirmation_locks.lock_comparison,
                     tenant, curator, suite_id, request, recipe)
