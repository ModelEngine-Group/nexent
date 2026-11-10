# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Signed AgentOS subscription to a retained ordinary conversation run."""

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from redis.exceptions import RedisError
from starlette.responses import JSONResponse, StreamingResponse

from contracts.agentos import BODY_KEY, PRINCIPAL_KEY, AgentOperation, AgentResume
from infrastructure.rdb.conversation_state import conversation_belongs_to
from infrastructure.redis.agent_events import START, RunJournal
from infrastructure.redis.run_state import runtime_state_service
from nexent.core.concurrency import run_blocking


async def _control_io(task, function, *args, **kwargs):
    return await run_blocking(task, function, *args, lane="control-io", owner="runtime", **kwargs)


def _stream_error(code):
    return f"event: agentos_error\ndata: {json.dumps({'code': code})}\n\n"


async def resume_run(payload, actor):
    owned = await _control_io(
        "agentos-resume-ownership", conversation_belongs_to, payload.conversation_id,
        user_id=actor.user_id, tenant_id=actor.tenant_id,
    )
    if not owned:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})
    if not runtime_state_service.enabled:
        raise HTTPException(status_code=503, detail={"code": "AGENTOS_EVENT_STORE_UNAVAILABLE"})

    sequence = 0
    after_id = START
    if payload.after_event_id is not None:
        cursor_run, cursor_index = payload.after_event_id.split(":")
        if cursor_run != payload.run_id:
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_CURSOR_RUN_MISMATCH"})
        sequence = int(cursor_index)
        after_id = f"{sequence}-0"

    journal = RunJournal(actor.tenant_id, actor.user_id, payload.conversation_id, payload.run_id)
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


def create_resume_router():
    router = APIRouter()

    @router.post(AgentOperation.RESUME.value, include_in_schema=False)
    async def resume(request: Request):
        actor = request.scope.get(PRINCIPAL_KEY)
        if actor is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = AgentResume.model_validate_json(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
        return await resume_run(payload, actor)

    return router
