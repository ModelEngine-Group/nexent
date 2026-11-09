# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind authenticated AgentOS transport to the current Agent execution handlers."""

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from contracts.agentos import BODY_KEY, PRINCIPAL_KEY, CompatibilityOperation, CompatibilityRun, CompatibilityStop


def create_compatibility_router(run, stop) -> APIRouter:
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

    return router
