# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind authenticated AgentOS transport to the current Agent execution handlers."""

import asyncio

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from contracts.agentos import (
    BODY_KEY, PRINCIPAL_KEY, AgentOperation, BackgroundRun, CompatibilityConversationRun, CompatibilityOperation,
    CompatibilityRun, CompatibilityStop, DebugRunReference,
)


def create_compatibility_router(run, stop, *, conversation_run=None, debug_stop=None) -> APIRouter:
    router = APIRouter()

    @router.post(CompatibilityOperation.RUN.value, include_in_schema=False)
    async def run_agent(request: Request):
        principal = request.scope.get(PRINCIPAL_KEY)
        if principal is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = CompatibilityRun.model_validate_json(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
        return await run(payload.request, principal)

    if conversation_run is not None:
        @router.post(CompatibilityOperation.CONVERSATION_RUN.value, include_in_schema=False)
        async def run_conversation(request: Request):
            principal = request.scope.get(PRINCIPAL_KEY)
            if principal is None:
                return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
            try:
                payload = CompatibilityConversationRun.model_validate_json(request.scope[BODY_KEY])
            except ValidationError:
                return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
            return await conversation_run(payload, principal)

    @router.post(CompatibilityOperation.STOP.value, include_in_schema=False)
    async def stop_agent(request: Request):
        principal = request.scope.get(PRINCIPAL_KEY)
        if principal is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = CompatibilityStop.model_validate_json(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
        return await stop(payload.conversation_id, principal)

    if debug_stop is not None:
        @router.post(CompatibilityOperation.DEBUG_STOP.value, include_in_schema=False)
        async def stop_debug(request: Request):
            principal = request.scope.get(PRINCIPAL_KEY)
            if principal is None:
                return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
            try:
                payload = DebugRunReference.model_validate_json(request.scope[BODY_KEY])
            except ValidationError:
                return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
            return await debug_stop(payload.run_id, principal)

    return router


def create_background_router(run, inspect, *, tracked_run=None) -> APIRouter:
    router = APIRouter()

    @router.post(CompatibilityOperation.BACKGROUND.value, include_in_schema=False)
    async def run_background(request: Request):
        principal = request.scope.get(PRINCIPAL_KEY)
        if principal is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = CompatibilityRun.model_validate_json(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)

        return await run_until_disconnect(request, run(payload.request, principal))

    if tracked_run is not None:
        @router.post(AgentOperation.BACKGROUND.value, include_in_schema=False)
        async def run_tracked_background(request: Request):
            principal = request.scope.get(PRINCIPAL_KEY)
            if principal is None:
                return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
            try:
                payload = BackgroundRun.model_validate_json(request.scope[BODY_KEY])
            except ValidationError:
                return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
            return await run_until_disconnect(request, tracked_run(payload, principal))

    @router.post(CompatibilityOperation.INSPECT.value, include_in_schema=False)
    async def inspect_agent(request: Request):
        principal = request.scope.get(PRINCIPAL_KEY)
        if principal is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = CompatibilityStop.model_validate_json(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
        return await inspect(payload.conversation_id, principal)

    return router


async def run_until_disconnect(request: Request, run):
    async def wait_for_disconnect():
        while (await request.receive())["type"] != "http.disconnect":
            pass

    execution = asyncio.create_task(run)
    disconnected = asyncio.create_task(wait_for_disconnect())
    try:
        completed, _ = await asyncio.wait((execution, disconnected), return_when=asyncio.FIRST_COMPLETED)
        if execution in completed:
            return execution.result()
        return JSONResponse({"code": "AGENTOS_CLIENT_DISCONNECTED"}, status_code=499)
    finally:
        disconnected.cancel()
        if not execution.done():
            execution.cancel()
        await asyncio.gather(disconnected, execution, return_exceptions=True)
