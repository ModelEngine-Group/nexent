# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime AgentOS endpoint and event collection for prepared evaluations."""

import json
import logging

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from contracts.agentos import (
    BODY_KEY, PRINCIPAL_KEY, AgentOperation, CompatibilityOperation, EvaluationAgentResult, EvaluationAgentRun, PreparedEvaluationRun,
)
from runtime.agentos.compatibility import run_until_disconnect

logger = logging.getLogger(__name__)


def create_evaluation_router() -> APIRouter:
    router = APIRouter()

    @router.post(CompatibilityOperation.EVALUATION_CASE.value, include_in_schema=False)
    async def retired_evaluation_case(request: Request):
        actor = request.scope.get(PRINCIPAL_KEY)
        if actor is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            EvaluationAgentRun.model_validate_json(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
        return JSONResponse({"code": "AGENTOS_EVALUATION_PREPARED_REQUIRED"}, status_code=410)

    @router.post(AgentOperation.EVALUATION_CASE.value, include_in_schema=False)
    async def run_prepared_case(request: Request):
        actor = request.scope.get(PRINCIPAL_KEY)
        if actor is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = PreparedEvaluationRun.model_validate_json(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
        from runtime.agentos.prepared_evaluation import execute_prepared_evaluation

        return await run_until_disconnect(request, execute_prepared_evaluation(payload, actor))

    return router


async def collect_observer_output(agent_run_info, runner, thread_manager) -> EvaluationAgentResult:
    final_answer_parts: list[str] = []
    runtime_events: list[dict] = []
    async for chunk in runner(
        agent_run_info,
        thread_manager=thread_manager,
    ):
        try:
            data = json.loads(chunk)
            if isinstance(data, dict):
                runtime_events.append(data)
                if data.get("type") == "final_answer":
                    content = data.get("content")
                    if isinstance(content, str):
                        final_answer_parts.append(content)
        except Exception:
            logger.debug(
                "Failed to parse observer chunk: %r", chunk[:200], exc_info=True
            )
    remaining = agent_run_info.observer.get_cached_message()
    for msg in remaining:
        try:
            data = json.loads(msg)
            if isinstance(data, dict):
                runtime_events.append(data)
        except Exception:
            logger.debug(
                "Failed to parse straggler observer message", exc_info=True
            )
    return EvaluationAgentResult(answer="".join(final_answer_parts).strip(), events=runtime_events)
