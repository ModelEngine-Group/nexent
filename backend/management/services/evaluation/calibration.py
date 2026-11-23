# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compare a published evaluator with business labels on supplied observations."""

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evaluation import EvaluatorCalibrationRequest
from management.db.evaluation.evaluator import get_evaluator
from management.services.evaluation.evolution_access import require_business_agent_edit
from management.services.evaluation.scoring import grade_observed_case
from nexent.core.agents.prompt.auxiliary import compose_auxiliary_prompt


def calibrate_evaluator(request: EvaluatorCalibrationRequest, tenant_id: str, user_id: str) -> dict:
    require_business_agent_edit(request.agent_id, tenant_id, user_id)

    eid = request.evaluator_id
    evaluator = get_evaluator(eid, tenant_id)
    if not evaluator or evaluator.get("status") != "PUBLISHED":
        raise AppException(ErrorCode.AGENT_EVALUATION_EVALUATOR_NOT_PUBLISHED)

    uses_model = evaluator.get("evaluator_type") != "code"
    if uses_model and request.judge_model_id is None:
        raise AppException(ErrorCode.COMMON_PARAMETER_INVALID, "A judge model is required for an LLM evaluator")
    system = compose_auxiliary_prompt(request.language, "evaluation_judge").system if uses_model else ""
    counts = dict(agree=0, false_accept=0, false_reject=0, invalid=0, missing_evidence=0)
    rows = []
    for index, example in enumerate(request.examples):
        judgment = grade_observed_case(
            {eid: evaluator}, tenant_id=tenant_id, user_id=user_id, query=example.query,
            actual=example.actual, expected=example.expected, runtime_events=example.runtime_events,
            required_evidence={eid: request.required_evidence}, judge_model_id=request.judge_model_id,
            judge_system_prompt=system,
        )[eid]
        status = judgment["status"]
        if status in {"invalid", "missing_evidence"}:
            outcome = status
        elif status == example.human_verdict:
            outcome = "agree"
        else:
            outcome = "false_accept" if status == "pass" else "false_reject"
        counts[outcome] += 1
        rows.append({"index": index, "human_verdict": example.human_verdict, **judgment})
    return {
        "evaluator_id": eid, "evaluator_version": evaluator["version_no"],
        "judge_model_id": request.judge_model_id if uses_model else None,
        "counts": counts, "examples": rows,
    }
