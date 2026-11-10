# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime AgentOS compatibility handler for synthetic evaluation cases."""

import json
import logging

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from contracts.agent import AgentRequest
from contracts.agentos import (
    BODY_KEY, PRINCIPAL_KEY, AgentOperation, CompatibilityOperation, EvaluationAgentResult, EvaluationAgentRun, PreparedEvaluationRun,
)
from infrastructure.agentos_identity import ServicePrincipal
from runtime.agentos.compatibility import run_until_disconnect

logger = logging.getLogger(__name__)


def create_evaluation_router(execute=None) -> APIRouter:
    router = APIRouter()
    execute = execute or execute_evaluation_case

    @router.post(CompatibilityOperation.EVALUATION_CASE.value, include_in_schema=False)
    async def run_evaluation_case(request: Request):
        actor = request.scope.get(PRINCIPAL_KEY)
        if actor is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = EvaluationAgentRun.model_validate_json(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
        return await execute(payload, actor)

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


async def execute_evaluation_case(payload: EvaluationAgentRun, actor: ServicePrincipal) -> EvaluationAgentResult:
    from management.services.agent.service import prepare_agent_run
    from runtime.adapters.nexent.runner import agent_run
    from runtime.executions import agent_run_manager as run_manager
    from runtime.thread_management import runtime_thread_manager

    return await _collect_case_events(
        payload, actor, prepare_agent_run, agent_run, run_manager, runtime_thread_manager,
    )


async def _collect_case_events(payload, actor, prepare, runner, run_manager, thread_manager) -> EvaluationAgentResult:
    run_conversation_id = payload.conversation_id
    user_id, tenant_id = actor.user_id, actor.tenant_id
    agent_request = AgentRequest(
        query=payload.query,
        conversation_id=run_conversation_id,
        history=payload.history,
        minio_files=None,
        agent_id=payload.agent_id,
        version_no=payload.version_no,
        is_debug=True,
    )
    agent_run_info = None
    terminal_status = "failed"
    try:
        agent_run_info, _memory_context = await prepare(
            agent_request=agent_request,
            user_id=user_id,
            tenant_id=tenant_id,
            allow_memory_search=False,
        )
        result = await collect_observer_output(agent_run_info, runner, thread_manager)
        terminal_status = "completed"
        return result
    finally:
        if agent_run_info is not None:
            run_manager.unregister_agent_run(
                run_conversation_id,
                user_id,
                status=terminal_status,
                agent_run_info=agent_run_info,
            )


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
