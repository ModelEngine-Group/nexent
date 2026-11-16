# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Request-owned tool calling for Management's deterministic tool validation."""

import asyncio
import logging
from types import SimpleNamespace

from contracts.agentos import (
    BODY_KEY,
    PRINCIPAL_KEY,
    AgentOperation,
    AgentToolInvocation,
    AgentToolResult,
    EvaluationAnalysisTool,
)
from fastapi import APIRouter, HTTPException, Request
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.concurrency import (
    ManagedTaskSpec,
    RunCancellationScope,
    ThreadCapacityExceeded,
    ThreadQueueTimedOut,
)
from nexent.core.utils.observer import MessageObserver
from nexent.monitor import set_monitoring_context, set_monitoring_operation
from pydantic import ValidationError
from runtime.agentos.prepared_analysis import materialize_analysis_tools
from runtime.thread_management import runtime_thread_manager
from starlette.responses import JSONResponse

from backend.http.server.agentos_lifecycle import run_until_disconnect

logger = logging.getLogger(__name__)
TOOL_INVOCATION_SECONDS = 600


def execute_tool(payload, actor, scope):
    kind, _ = EvaluationAnalysisTool.binding_identity(payload.tool.tool_id)
    if kind is not EvaluationAnalysisTool.TEXT:
        raise ValueError("Unsupported tool invocation")
    config = materialize_analysis_tools(
        [payload.tool], actor, run_id=payload.run_id, cancellation_scope=scope
    )[payload.tool.tool_id]
    set_monitoring_context(tenant_id=actor.tenant_id)
    set_monitoring_operation(
        "tool_validation",
        display_name=getattr(config.metadata.get("llm_model"), "display_name", None),
    )
    observer = MessageObserver(lang=payload.language)
    tool = NexentAgent.create_local_tool(
        SimpleNamespace(observer=observer, cancellation_scope=scope), config
    )
    return AgentToolResult(result=tool.forward(**payload.inputs))


def create_tool_router(manager=runtime_thread_manager):
    router = APIRouter()

    @router.post(AgentOperation.INVOKE_TOOL.value, include_in_schema=False)
    async def invoke(request: Request):
        actor = request.scope.get(PRINCIPAL_KEY)
        if actor is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = AgentToolInvocation.model_validate_json(request.scope[BODY_KEY])
            if (
                EvaluationAnalysisTool.binding_identity(payload.tool.tool_id)[0]
                is not EvaluationAnalysisTool.TEXT
            ):
                raise ValueError("Unsupported tool invocation")
        except (ValidationError, ValueError):
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)

        async def run():
            scope = RunCancellationScope()
            try:
                async with asyncio.timeout(TOOL_INVOCATION_SECONDS):
                    return await manager.run(
                        "model-tool-io",
                        ManagedTaskSpec(
                            task_name="agentos-tool",
                            owner="runtime.agentos.tools",
                            run_id=payload.run_id,
                            close_hook=scope.cancel,
                        ),
                        execute_tool,
                        payload,
                        actor,
                        scope,
                    )
            except (ThreadCapacityExceeded, ThreadQueueTimedOut):
                return JSONResponse({"code": "AGENTOS_TOOL_CAPACITY"}, status_code=503)
            except HTTPException as error:
                return JSONResponse(
                    {"code": "AGENTOS_TOOL_BINDING_REJECTED"},
                    status_code=error.status_code,
                )
            except TimeoutError as error:
                logger.warning(
                    "agentos_tool_timeout run_id=%s phase=invoke threshold_seconds=%s exception_type=%s",
                    payload.run_id,
                    TOOL_INVOCATION_SECONDS,
                    type(error).__name__,
                )
                return JSONResponse({"code": "AGENTOS_TOOL_TIMEOUT"}, status_code=504)
            except Exception as error:  # noqa: BLE001 - Redact provider and tool failures at HTTP boundary.
                logger.warning(
                    "agentos_tool_failed run_id=%s exception_type=%s",
                    payload.run_id,
                    type(error).__name__,
                )
                return JSONResponse({"code": "AGENTOS_TOOL_FAILED"}, status_code=502)
            finally:
                scope.cancel()

        return await run_until_disconnect(request, run())

    return router
