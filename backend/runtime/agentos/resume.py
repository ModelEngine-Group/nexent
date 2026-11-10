# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Signed AgentOS lifecycle commands for retained ordinary conversation runs."""

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import TypeAdapter, ValidationError
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse, StreamingResponse

from contracts.agentos import (
    BODY_KEY, PRINCIPAL_KEY, REPLAY_COUNT_HEADER, AgentActiveRun, AgentMessageRunLookup, AgentOperation, AgentResume, AgentRunLookup,
    AgentRunReference, AgentRunState, AgentStop, CompatibilityStop, DebugRunReference,
)
from infrastructure.rdb.agent_execution import active_execution, read_execution, read_terminal_execution_for_message
from infrastructure.rdb.conversation_state import conversation_belongs_to
from infrastructure.redis.agent_events import START, RunJournal
from infrastructure.redis.run_state import runtime_state_service
from nexent.core.concurrency import run_blocking
from runtime.agentos import debug


async def _control_io(task, function, *args, **kwargs):
    return await run_blocking(task, function, *args, lane="control-io", owner="runtime", **kwargs)


def _stream_error(code):
    return f"event: agentos_error\ndata: {json.dumps({'code': code})}\n\n"


async def _owned_journal(payload: AgentRunReference, actor) -> RunJournal:
    owned = await _control_io(
        "agentos-run-ownership", conversation_belongs_to, payload.conversation_id,
        user_id=actor.user_id, tenant_id=actor.tenant_id,
    )
    if not owned:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})
    if not runtime_state_service.enabled:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_EVENT_STORE_UNAVAILABLE"})

    return RunJournal(actor.tenant_id, actor.user_id, payload.conversation_id, payload.run_id)


async def find_active(payload: CompatibilityStop, actor) -> AgentActiveRun:
    try:
        run_id = await _control_io(
            "agentos-active-execution", active_execution, payload.conversation_id, actor.user_id, actor.tenant_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"}) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_EXECUTION_STORE_UNAVAILABLE"}) from exc
    return AgentActiveRun(run_id=run_id)


async def run_state(payload: AgentRunLookup, actor, *, request_stop: bool = False) -> AgentRunState:
    prevent_start = isinstance(payload, AgentStop) and payload.prevent_start
    if prevent_start and payload.conversation_id is None:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_REQUEST"})
    try:
        record = await _control_io(
            "agentos-read-execution", read_execution, payload.run_id, actor.user_id, actor.tenant_id,
            payload.conversation_id, request_stop=request_stop, prevent_start=prevent_start,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"}) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_EXECUTION_STORE_UNAVAILABLE"}) from exc

    if record is not None:
        latest_event_id = None
        if runtime_state_service.enabled:
            journal = RunJournal(actor.tenant_id, actor.user_id, record["conversation_id"], payload.run_id)
            try:
                state = await _control_io("agentos-run-cursor", journal.run_state)
            except (RedisError, RuntimeError):
                state = None
            if state is not None and state[0] != START:
                latest_event_id = f"{payload.run_id}:{state[0].split('-')[0]}"
        return AgentRunState(run_id=payload.run_id, latest_event_id=latest_event_id, **record)

    if payload.conversation_id is None:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})
    journal = await _owned_journal(payload, actor)
    try:
        state = await _control_io("agentos-run-state", journal.run_state, request_stop=request_stop)
    except (RedisError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_EVENT_STORE_UNAVAILABLE"}) from exc
    if state is None:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})
    event_id, status, cancellation_requested = state
    latest_event_id = None if event_id == START else f"{payload.run_id}:{event_id.split('-')[0]}"
    return AgentRunState(
        conversation_id=payload.conversation_id, run_id=payload.run_id, status=status,
        latest_event_id=latest_event_id, cancellation_requested=cancellation_requested,
    )


async def resume_run(payload: AgentResume, actor):
    journal = await _owned_journal(payload, actor)
    sequence = 0
    after_id = START
    if payload.after_event_id is not None:
        cursor_run, cursor_index = payload.after_event_id.split(":")
        if cursor_run != payload.run_id:
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_CURSOR_RUN_MISMATCH"})
        sequence = int(cursor_index)
        after_id = f"{sequence}-0"

    try:
        anchor, events, tail = await _control_io("agentos-resume-replay", journal.replay, after_id)
    except (RedisError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_EVENT_STORE_UNAVAILABLE"}) from exc
    if not tail:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})
    if not anchor:
        raise HTTPException(status_code=410, detail={"code": "AGENTOS_CURSOR_UNAVAILABLE"})
    if events and int(events[0][0].split("-")[0]) != sequence + 1:
        raise HTTPException(status_code=410, detail={"code": "AGENTOS_CURSOR_UNAVAILABLE"})

    async def stream():
        if anchor[0][1]["kind"] == "terminal":
            return
        index, last_id, pending = sequence, after_id, events
        while True:
            for event_id, event in pending:
                if event_id != f"{index + 1}-0":
                    yield _stream_error("AGENTOS_CURSOR_UNAVAILABLE")
                    return
                index += 1
                last_id = event_id
                sse_id = f"id: {payload.run_id}:{index}\n"
                if event["kind"] == "terminal":
                    yield sse_id + f"event: agentos_terminal\ndata: {json.dumps({'status': event['status']})}\n\n"
                    return
                yield sse_id + event["data"]
            try:
                pending = await _control_io("agentos-resume-follow", journal.wait, last_id)
            except (RedisError, RuntimeError):
                yield _stream_error("AGENTOS_EVENT_STORE_UNAVAILABLE")
                return
            if pending is None:
                yield _stream_error("AGENTOS_CURSOR_UNAVAILABLE")
                return
            if not pending:
                yield ": keep-alive\n\n"

    tail_id, tail_fields = tail[0]
    # Derive the boundary from the same Redis snapshot that supplied the initial replay.
    replay_count = max(0, int(tail_id.split("-")[0]) - sequence - (tail_fields["kind"] == "terminal"))
    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-AgentOS-Run-ID": payload.run_id,
        REPLAY_COUNT_HEADER: str(replay_count),
    })


async def stop_run(payload: AgentStop | DebugRunReference, actor):
    if isinstance(payload, DebugRunReference):
        return await debug.stop_agentos_debug(payload.run_id, actor)
    return await run_state(payload, actor, request_stop=True)


async def inspect_run(payload: AgentRunLookup | AgentMessageRunLookup, actor):
    if isinstance(payload, AgentRunLookup):
        return await run_state(payload, actor)
    try:
        result = await _control_io(
            "agentos-inspect-terminal-message", read_terminal_execution_for_message,
            payload.conversation_id, payload.assistant_message_id, actor.user_id, actor.tenant_id,
        )
    except PermissionError:
        result = None
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_EXECUTION_STORE_UNAVAILABLE"}) from exc
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})
    run_id, record = result
    return AgentRunState(run_id=run_id, latest_event_id=None, **record)


def create_run_lifecycle_router():
    router = APIRouter()

    def handler(schema, command):
        validate = TypeAdapter(schema).validate_json

        async def handle(request: Request):
            actor = request.scope.get(PRINCIPAL_KEY)
            if actor is None:
                return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
            try:
                payload = validate(request.scope[BODY_KEY])
            except ValidationError:
                return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
            return await command(payload, actor)

        return handle

    router.add_api_route(
        AgentOperation.RESUME.value, handler(AgentResume, resume_run), methods=["POST"], include_in_schema=False,
    )
    router.add_api_route(
        AgentOperation.INSPECT.value, handler(AgentRunLookup | AgentMessageRunLookup, inspect_run),
        methods=["POST"], include_in_schema=False,
    )
    router.add_api_route(
        AgentOperation.STOP.value, handler(AgentStop | DebugRunReference, stop_run),
        methods=["POST"], include_in_schema=False,
    )
    router.add_api_route(
        AgentOperation.ACTIVE.value, handler(CompatibilityStop, find_active), methods=["POST"], include_in_schema=False,
    )
    return router
