# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""AgentOS KB admission and inspection over Runtime-owned durable jobs."""

from contracts.agentos import BODY_KEY, PRINCIPAL_KEY
from contracts.agentos_knowledge import (
    KnowledgeFileDelete,
    KnowledgeFileUpload,
    KnowledgeJobLookup,
    KnowledgeOperation,
)
from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from starlette.responses import JSONResponse

from backend.http.server.knowledge_errors import knowledge_error


def default_service():
    import httpx
    from contracts.constants import environment
    from runtime.knowledge_base.service import KnowledgeService
    from runtime.model.service import ModelService

    from infrastructure.agentos_client import AgentOSClient
    from infrastructure.model_adapter import get_adapter_from_config
    from infrastructure.rdb.model_records import get_model_by_model_id

    return KnowledgeService(
        AgentOSClient(
            environment.MANAGEMENT_AGENTOS_URL,
            lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs),
        ),
        ModelService(get_model_by_model_id, get_adapter_from_config),
    )


def create_knowledge_router(service=None):
    router = APIRouter()
    service = service or default_service()

    async def dispatch(request, schema, action, status):
        principal = request.scope.get(PRINCIPAL_KEY)
        if principal is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = schema.model_validate_json(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
        try:
            result = await action(payload, principal)
            return JSONResponse(jsonable_encoder(result), status_code=status)
        except Exception as error:  # noqa: BLE001 - The HTTP boundary must redact unexpected failures.
            from runtime.model.service import ModelAccessError

            if isinstance(error, ModelAccessError):
                return JSONResponse({"code": error.code}, status_code=error.status)
            return knowledge_error(error)

    @router.post(KnowledgeOperation.UPLOAD.value, include_in_schema=False)
    async def upload(request: Request):
        return await dispatch(request, KnowledgeFileUpload, service.upload, 202)

    @router.post(KnowledgeOperation.INSPECT.value, include_in_schema=False)
    async def inspect(request: Request):
        return await dispatch(request, KnowledgeJobLookup, service.inspect, 200)

    @router.post(KnowledgeOperation.DELETE.value, include_in_schema=False)
    async def delete(request: Request):
        return await dispatch(request, KnowledgeFileDelete, service.delete, 202)

    return router
