# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bound model-backed evolution generators without affecting ordinary authoring or chat."""

from contracts.constants import environment
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, RuntimeUpstreamError
from contracts.evolution_metering import generation_budget
from contracts.evolution_sources import task_digest
from management.clients.model import invoke_chat_prompt_in_worker
from management.db.evaluation import generation_attempts


def source_digest(method, feedback_id, *resource):
    return task_digest([method, feedback_id] if feedback_id is not None else [method, *resource])


def reserve_generation(tenant, user, source, model):
    config = generation_budget(tenant)
    if config is not None and str(model) not in config.models:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "No billing ceiling for the selected generation model")
    attempt = (generation_attempts.reserve(tenant, user, source, model, metering_revision=config.revision())
               if config else generation_attempts.reserve(tenant, user, source, model))
    return attempt, config is not None


def reject_stopped_generation(tenant, attempt_id):
    if generation_attempts.stopped(tenant, attempt_id):
        raise AppException(ErrorCode.COMMON_RATE_LIMIT_EXCEEDED, "Generation token or cost budget exhausted")


def finish_generation(tenant, attempt_id):
    if not generation_attempts.complete(tenant, attempt_id):
        reject_stopped_generation(tenant, attempt_id)
        raise AppException(ErrorCode.SYSTEM_TIMEOUT, "Candidate generation exceeded its time budget")


def invoke_candidate_model(*, source, model_id, system_prompt, user_prompt, user_id, tenant_id):
    attempt, metered = reserve_generation(tenant_id, user_id, source, model_id)
    try:
        output = invoke_chat_prompt_in_worker(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            user_id=user_id,
            tenant_id=tenant_id,
            max_output_tokens=environment.EVOLUTION_GENERATION_MAX_OUTPUT_TOKENS,
            timeout_seconds=environment.EVOLUTION_GENERATION_TIMEOUT_SECONDS,
            **({"generation_attempt": attempt} if metered else {}),
        )
    except RuntimeUpstreamError as exc:
        if metered and exc.status_code == 429 and b'"EVOLUTION_GENERATION_BUDGET"' in exc.content:
            raise AppException(ErrorCode.COMMON_RATE_LIMIT_EXCEEDED, "Generation token or cost budget exhausted") from exc
        raise
    except TimeoutError as exc:
        # Keep an uncertain upstream call charged and its slot reserved until expiry.
        raise AppException(ErrorCode.SYSTEM_TIMEOUT, "Candidate generation exceeded its time budget") from exc
    finish_generation(tenant_id, attempt)
    return output
