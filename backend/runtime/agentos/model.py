# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Expose the signed AgentOS model operations."""

import logging

from fastapi import APIRouter, Request
from pydantic import TypeAdapter, ValidationError
from starlette.responses import JSONResponse

from contracts.agentos import BODY_KEY, PRINCIPAL_KEY, ModelInvocation, ModelOperation, ModelReference
from runtime.model.service import ModelAccessError, ModelService

_INVOKE = TypeAdapter(ModelInvocation)
logger = logging.getLogger(__name__)


def create_model_router(service: ModelService) -> APIRouter:
    router = APIRouter()

    async def dispatch(request, parse, action):
        principal = request.scope.get(PRINCIPAL_KEY)
        if principal is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = parse(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
        try:
            return await action(payload, principal)
        except ModelAccessError as exc:
            return JSONResponse({"code": exc.code}, status_code=exc.status)
        except Exception as exc:
            # Provider failures can contain credentials, prompts or connection details.
            logger.warning("AgentOS model request failed (%s)", type(exc).__name__)
            return JSONResponse({"code": "MODEL_REQUEST_FAILED"}, status_code=502)

    @router.post(ModelOperation.GET.value, include_in_schema=False)
    async def get_model(request: Request):
        async def get(payload, principal):
            return await service.get(payload.model_id, principal)

        return await dispatch(request, ModelReference.model_validate_json, get)

    @router.post(ModelOperation.INVOKE.value, include_in_schema=False)
    async def invoke_model(request: Request):
        return await dispatch(request, _INVOKE.validate_json, service.invoke)

    return router
