# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Signed AgentOS lifecycle commands for retained ordinary conversation runs."""

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from redis.exceptions import RedisError
from starlette.responses import JSONResponse, StreamingResponse

from contracts.agentos import BODY_KEY, PRINCIPAL_KEY, AgentOperation, AgentResume, AgentRunReference, AgentRunState
from infrastructure.rdb.conversation_state import conversation_belongs_to
from infrastructure.redis.agent_events import START, RunJournal
from infrastructure.redis.run_state import runtime_state_service
from nexent.core.concurrency import run_blocking


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


async def run_state(payload: AgentRunReference, actor, *, request_stop: bool = False) -> AgentRunState:
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

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-AgentOS-Run-ID": payload.run_id,
    })


def create_run_lifecycle_router():
    router = APIRouter()

    def handler(schema, command, **options):
        async def handle(request: Request):
            actor = request.scope.get(PRINCIPAL_KEY)
            if actor is None:
                return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
            try:
                payload = schema.model_validate_json(request.scope[BODY_KEY])
            except ValidationError:
                return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
            return await command(payload, actor, **options)

        return handle

    router.add_api_route(
        AgentOperation.RESUME.value, handler(AgentResume, resume_run), methods=["POST"], include_in_schema=False,
    )
    router.add_api_route(
        AgentOperation.INSPECT.value, handler(AgentRunReference, run_state), methods=["POST"], include_in_schema=False,
    )
    router.add_api_route(
        AgentOperation.STOP.value, handler(AgentRunReference, run_state, request_stop=True),
        methods=["POST"], include_in_schema=False,
    )
    return router
