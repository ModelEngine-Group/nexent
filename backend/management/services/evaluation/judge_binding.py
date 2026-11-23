# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution_sources import task_digest
from infrastructure.agent_model_config import model_record_revision
from infrastructure.rdb.model_records import get_model_by_model_id
from nexent.core.agents.prompt.auxiliary import compose_auxiliary_prompt


def judge_binding(tenant, model_id, language):
    record = get_model_by_model_id(model_id, tenant)
    if not record or not (record.get("update_time") or record.get("create_time")):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Cannot verify the judge model revision")
    return {"model_id":model_id, "revision":model_record_revision(record),
            "template_digest":task_digest(compose_auxiliary_prompt(language, "evaluation_judge").system)}


def judges_for_plan(tenant, rule, request, fixed):
    selected = [(rule,request.judge_model_id,request.language)]
    for case in fixed.values():
        scoring = case["scoring"]
        selected.append((scoring["evaluator"],scoring["judge_model_id"],scoring["language"]))
    judges = {}
    for evaluator, model_id, language in selected:
        key = f"{model_id}/{language}"
        if evaluator["evaluator_type"] != "code" and key not in judges:
            judges[key] = judge_binding(tenant, model_id, language)
    return judges
