# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bound model-backed evolution generators without affecting ordinary authoring or chat."""

from contracts.constants import environment
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution_sources import task_digest
from management.clients.model import invoke_chat_prompt_in_worker
from management.db.evaluation import generation_attempts


def source_digest(method, feedback_id, *resource):
    return task_digest([method, feedback_id] if feedback_id is not None else [method, *resource])


def finish_generation(tenant, attempt_id):
    if not generation_attempts.complete(tenant, attempt_id):
        raise AppException(ErrorCode.SYSTEM_TIMEOUT, "Candidate generation exceeded its time budget")


def invoke_candidate_model(*, source, model_id, system_prompt, user_prompt, user_id, tenant_id):
    attempt = generation_attempts.reserve(tenant_id, user_id, source, model_id)
    try:
        output = invoke_chat_prompt_in_worker(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            user_id=user_id,
            tenant_id=tenant_id,
            max_output_tokens=environment.EVOLUTION_GENERATION_MAX_OUTPUT_TOKENS,
            timeout_seconds=environment.EVOLUTION_GENERATION_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        # Keep an uncertain upstream call charged and its slot reserved until expiry.
        raise AppException(ErrorCode.SYSTEM_TIMEOUT, "Candidate generation exceeded its time budget") from exc
    finish_generation(tenant_id, attempt)
    return output
