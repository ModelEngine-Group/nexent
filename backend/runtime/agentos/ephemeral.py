# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Signed request-owned execution for prepared ephemeral AgentOS runs."""

import json
import logging
from contextlib import aclosing

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse, StreamingResponse

from contracts.agentos import BODY_KEY, PRINCIPAL_KEY, AgentOperation, PreparedEphemeralRun
from contracts.constants.constants import SAFE_AGENT_STREAM_ERROR_MESSAGE
from contracts.constants.environment import RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS
from contracts.errors.exceptions import RuntimeQueueTimeoutError
from nexent.core.concurrency import ManagedTaskSpec, ThreadCapacityExceeded, ThreadQueueTimedOut
from nexent.monitor import AgentRunMetadata, agent_monitoring_context
from runtime.adapters.nexent.runner import DeferredAgentRun, agent_run
from runtime.agentos.compatibility import run_until_disconnect
from runtime.agentos.prepared_evaluation import discard_prepared_workspace, load_prepared_run, prepare_run_snapshot
from runtime.executions import AgentRunConcurrencyExceededError, agent_run_manager
from runtime.thread_management import runtime_thread_manager

logger = logging.getLogger(__name__)


def _sse(event: dict) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n\n"


async def _observer_stream(info, execution, deferred):
    try:
        async with aclosing(agent_run(
            info, thread_manager=runtime_thread_manager, execution=execution, deferred_run=deferred,
        )) as events:
            async for chunk in events:
                event = json.loads(chunk)
                if isinstance(event, dict) and event.get("type") != "skill_artifact":
                    yield _sse(event)
    except Exception:
        logger.exception("Ephemeral AgentOS execution failed")
        yield _sse({"type": "error", "content": SAFE_AGENT_STREAM_ERROR_MESSAGE})


def _close_execution(execution, deferred):
    if not execution.future.done() and not execution.cancel_event.is_set():
        deferred.cancel()
        runtime_thread_manager.cancel(
            execution.execution_id, reason="ephemeral AgentOS stream closed",
            wait_timeout=0, mark_stuck_on_timeout=False,
        )


class _EphemeralResponse(StreamingResponse):
    def __init__(self, info, execution, deferred, metadata: AgentRunMetadata):
        super().__init__(
            _observer_stream(info, execution, deferred), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
        self.info = info
        self.execution = execution
        self.deferred = deferred
        self.metadata = metadata

    async def stream_response(self, send):
        with agent_monitoring_context(self.metadata):
            await super().stream_response(send)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                await self.body_iterator.aclose()
            finally:
                try:
                    _close_execution(self.execution, self.deferred)
                finally:
                    discard_prepared_workspace(self.info)


async def _open_ephemeral(payload, actor):
    deferred = DeferredAgentRun()
    capacity = agent_run_manager.reserve_agent_capacity(payload.resource.agent_id, RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS)
    execution = None
    try:
        execution = runtime_thread_manager.submit(
            "agent-run",
            ManagedTaskSpec(
                task_name="agentos-ephemeral-run", owner="runtime", run_id=payload.run_id,
                close_hook=deferred.cancel, pass_cancel_event=True,
            ),
            deferred.run,
        )
        execution.future.add_done_callback(lambda _: agent_run_manager.release_agent_capacity(capacity))
        await runtime_thread_manager.wait_until_started(execution)
        info = await load_prepared_run(payload, actor, prepare_run_snapshot)
    except BaseException:
        if execution is None:
            agent_run_manager.release_agent_capacity(capacity)
        else:
            _close_execution(execution, deferred)
        raise
    info.thread_future = execution.future
    metadata = AgentRunMetadata(
        user_id=actor.user_id, tenant_id=actor.tenant_id, agent_id=payload.resource.agent_id,
        query=payload.input.query, language=payload.language, is_debug=True, memory_enabled=False,
        history_count=len(payload.input.history), minio_files_count=len(payload.input.attachment_refs),
        extra_metadata={"agentos_run_id": payload.run_id},
    )
    return _EphemeralResponse(info, execution, deferred, metadata)


def create_ephemeral_run_router() -> APIRouter:
    router = APIRouter()

    @router.post(AgentOperation.RUN_EPHEMERAL.value, include_in_schema=False)
    async def run_ephemeral(request: Request):
        actor = request.scope.get(PRINCIPAL_KEY)
        if actor is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = PreparedEphemeralRun.model_validate_json(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
        try:
            return await run_until_disconnect(request, _open_ephemeral(payload, actor))
        except ThreadQueueTimedOut as exc:
            return JSONResponse({
                "code": "RUNTIME_QUEUE_TIMEOUT", "message": "Agent runtime queue wait timed out.", "retryable": True,
            }, status_code=429, headers={"Retry-After": str(RuntimeQueueTimeoutError(exc.timeout_seconds).retry_after_seconds)})
        except (ThreadCapacityExceeded, AgentRunConcurrencyExceededError):
            return JSONResponse({
                "code": "RUNTIME_CAPACITY_FULL", "message": "Agent runtime is at capacity.", "retryable": True,
            }, status_code=429, headers={"Retry-After": "1"})

    return router
