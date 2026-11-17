# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Expose the signed AgentOS model operations."""

import logging

from contracts.agentos import (
    BODY_KEY,
    PRINCIPAL_KEY,
    ModelInvocation,
    ModelListQuery,
    ModelOperation,
    ModelReference,
)
from fastapi import APIRouter, Request
from nexent.storage.errors import StorageError
from pydantic import TypeAdapter, ValidationError
from runtime.model.service import ModelAccessError, ModelService
from starlette.responses import JSONResponse

from backend.http.server.knowledge_errors import knowledge_error

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
        except StorageError as exc:
            return knowledge_error(exc, prefix="MODEL")
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

    @router.post(ModelOperation.LIST.value, include_in_schema=False)
    async def list_models(request: Request):
        return await dispatch(request, ModelListQuery.model_validate_json, service.list)

    return router
