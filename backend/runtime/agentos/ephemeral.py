# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Signed request-owned execution for prepared ephemeral AgentOS runs."""

import asyncio
import json
import logging
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import Field, TypeAdapter, ValidationError
from starlette.responses import JSONResponse, StreamingResponse

from contracts.agentos import BODY_KEY, PRINCIPAL_KEY, AgentOperation, PreparedAgentCreatorRun, PreparedEphemeralRun, PreparedSkillCreatorRun
from contracts.constants.constants import SAFE_AGENT_STREAM_ERROR_MESSAGE
from contracts.constants.environment import RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS, RUNTIME_CANCEL_POLL_INTERVAL_SECONDS
from contracts.errors.exceptions import RuntimeQueueTimeoutError, sampling_configuration_error_payload
from infrastructure.redis.run_state import runtime_state_service
from nexent.core.concurrency import ManagedTaskSpec, ThreadCapacityExceeded, ThreadQueueTimedOut, run_blocking
from nexent.monitor import AgentRunMetadata, agent_monitoring_context
from runtime.adapters.nexent.runner import DeferredAgentRun, agent_run
from runtime.agentos.compatibility import run_until_disconnect
from runtime.agentos.debug import debug_owner
from runtime.agentos.prepared_evaluation import discard_prepared_workspace, load_prepared_run, prepare_run_snapshot
from runtime.agentos.prepared_agent_creator import prepare_agent_creator_run
from runtime.agentos.prepared_skill_creator import prepare_skill_creator_run
from runtime.executions import AgentRunConcurrencyExceededError, agent_run_manager
from runtime.thread_management import runtime_thread_manager, unregister_after_worker_exit

logger = logging.getLogger(__name__)
_EPHEMERAL_PAYLOAD = TypeAdapter(Annotated[
    PreparedEphemeralRun | PreparedSkillCreatorRun | PreparedAgentCreatorRun, Field(discriminator="mode"),
])


def _sse(event: dict) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n\n"


async def _watch_debug_stop(run_id, owner, info):
    while not info.stop_event.is_set():
        if await runtime_state_service.is_cancelled_async(owner, run_id):
            agent_run_manager.stop_local_run(run_id, owner, expected_run=info)
            return
        await asyncio.sleep(RUNTIME_CANCEL_POLL_INTERVAL_SECONDS)


async def _observer_stream(info, execution, deferred, *, creator_mode=None):
    try:
        async with aclosing(agent_run(
            info, thread_manager=runtime_thread_manager, execution=execution, deferred_run=deferred,
        )) as events:
            async for chunk in events:
                event = json.loads(chunk)
                if isinstance(event, dict) and event.get("type") != "skill_artifact":
                    yield _sse(event)
                    if creator_mode == "nl2agent" and event.get("type") == "nl2a":
                        return
        if creator_mode:
            # The SDK drains observer messages and consumes worker exceptions without re-raising.
            execution.future.result()
            yield 'event: agentos_execution_complete\ndata: {}\n\n'
    except asyncio.CancelledError:
        # Explicit cancellation ends the stream. Preserve ASGI task cancellation on disconnect.
        if not info.stop_event.is_set() or asyncio.current_task().cancelling():
            raise
        if creator_mode == "nl2agent" and info.observer.boundary_reached:
            # A card can set the stop event before the SDK drains its observer queue.
            for chunk in info.observer.get_cached_message():
                event = json.loads(chunk)
                yield _sse(event)
                if event.get("type") == "nl2a":
                    return
    except Exception as exc:
        logger.exception("Ephemeral AgentOS execution failed")
        if creator_mode:
            name = "NL2Agent" if creator_mode == "nl2agent" else "NL2Skill"
            error = sampling_configuration_error_payload(exc) or {"type": "error", "content": f"{name} execution failed."}
            yield "event: agentos_execution_error\n" + _sse(error)
        else:
            yield _sse({"type": "error", "content": SAFE_AGENT_STREAM_ERROR_MESSAGE})


def _close_execution(execution, deferred):
    if not execution.future.done() and not execution.cancel_event.is_set():
        deferred.cancel()
        runtime_thread_manager.cancel(
            execution.execution_id, reason="ephemeral AgentOS stream closed",
            wait_timeout=0, mark_stuck_on_timeout=False,
        )


class _EphemeralResponse(StreamingResponse):
    def __init__(self, info, execution, deferred, metadata: AgentRunMetadata, *, debug_owner=None, creator_mode=None):
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        self.debug_run_id = f"debug-{info.workspace_run_id}" if debug_owner is not None else None
        if self.debug_run_id is not None:
            headers["run_id"] = self.debug_run_id
        super().__init__(
            _observer_stream(info, execution, deferred, creator_mode=creator_mode), media_type="text/event-stream", headers=headers,
        )
        self.info = info
        self.execution = execution
        self.deferred = deferred
        self.metadata = metadata
        self.debug_owner = debug_owner

    async def stream_response(self, send):
        watcher = None
        try:
            if self.debug_run_id is not None:
                registration = asyncio.create_task(run_blocking(
                    "agentos-register-debug", agent_run_manager.register_agent_run,
                    self.debug_run_id, self.info, self.debug_owner, lane="control-io", owner="runtime",
                ))
                try:
                    await asyncio.shield(registration)
                except asyncio.CancelledError:
                    await asyncio.gather(registration, return_exceptions=True)
                    raise
                if runtime_state_service.enabled:
                    watcher = asyncio.create_task(_watch_debug_stop(self.debug_run_id, self.debug_owner, self.info))
            with agent_monitoring_context(self.metadata):
                await super().stream_response(send)
        finally:
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)

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
                    try:
                        if self.debug_run_id is not None:
                            status = "stopped" if self.info.stop_event.is_set() else self.info.attempt_outcome or "completed"
                            await run_blocking(
                                "agentos-release-debug", unregister_after_worker_exit, agent_run_manager,
                                self.debug_run_id, self.debug_owner, status, self.info, lane="control-io", owner="runtime",
                            )
                    finally:
                        discard_prepared_workspace(self.info)


async def _open_ephemeral(payload, actor):
    deferred = DeferredAgentRun()
    creator_mode = None if isinstance(payload, PreparedEphemeralRun) else payload.mode
    if isinstance(payload, PreparedEphemeralRun):
        agent_id = payload.resource.agent_id
        capacity = agent_run_manager.reserve_agent_capacity(agent_id, RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS)
        materialize = prepare_run_snapshot
    elif isinstance(payload, PreparedAgentCreatorRun):
        agent_id, capacity, materialize = payload.agent_id, None, prepare_agent_creator_run
    else:
        agent_id, capacity, materialize = None, None, prepare_skill_creator_run
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
        if capacity is not None:
            execution.future.add_done_callback(lambda _: agent_run_manager.release_agent_capacity(capacity))
        await runtime_thread_manager.wait_until_started(execution)
        info = await load_prepared_run(payload, actor, materialize)
    except BaseException:
        if execution is not None:
            _close_execution(execution, deferred)
        elif capacity is not None:
            agent_run_manager.release_agent_capacity(capacity)
        raise
    info.thread_future = execution.future
    info.thread_manager = runtime_thread_manager
    info.thread_execution_id = execution.execution_id
    metadata = AgentRunMetadata(
        user_id=actor.user_id, tenant_id=actor.tenant_id, agent_id=agent_id,
        query=payload.input.query, language=payload.language, is_debug=True, memory_enabled=False,
        history_count=len(payload.input.history), minio_files_count=len(payload.input.attachment_refs),
        extra_metadata={"agentos_run_id": payload.run_id},
    )
    debug = isinstance(payload, PreparedEphemeralRun) and payload.debug
    return _EphemeralResponse(
        info, execution, deferred, metadata, debug_owner=debug_owner(actor) if debug else None, creator_mode=creator_mode,
    )


def create_ephemeral_run_router() -> APIRouter:
    router = APIRouter()

    @router.post(AgentOperation.RUN_EPHEMERAL.value, include_in_schema=False)
    async def run_ephemeral(request: Request):
        actor = request.scope.get(PRINCIPAL_KEY)
        if actor is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = _EPHEMERAL_PAYLOAD.validate_json(request.scope[BODY_KEY])
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
