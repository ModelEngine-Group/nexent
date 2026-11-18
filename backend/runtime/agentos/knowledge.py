# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""AgentOS KB admission and inspection over Runtime-owned durable jobs."""

from contracts.agentos import BODY_KEY, PRINCIPAL_KEY
from contracts.agentos_knowledge import (
    KnowledgeBaseInspect,
    KnowledgeChunks,
    KnowledgeFileDelete,
    KnowledgeFileUpload,
    KnowledgeJobLookup,
    KnowledgeOperation,
    KnowledgeSample,
    KnowledgeSearch,
)
from contracts.knowledge_base_deletion import (
    KnowledgeBaseDelete,
    KnowledgeBaseDeleteLookup,
)
from contracts.knowledge_chunk_mutation import ChunkMutationIntent, ChunkMutationLookup
from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from runtime.knowledge_base.composition import default_service
from starlette.responses import JSONResponse

from backend.http.server.knowledge_errors import knowledge_error


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

    @router.post(KnowledgeOperation.SEARCH.value, include_in_schema=False)
    async def search(request: Request):
        return await dispatch(request, KnowledgeSearch, service.search, 200)

    @router.post(KnowledgeOperation.SAMPLE.value, include_in_schema=False)
    async def sample(request: Request):
        return await dispatch(request, KnowledgeSample, service.sample, 200)

    @router.post(KnowledgeOperation.CHUNKS.value, include_in_schema=False)
    async def chunks(request: Request):
        return await dispatch(request, KnowledgeChunks, service.chunks, 200)

    @router.post(KnowledgeOperation.MUTATE_CHUNK.value, include_in_schema=False)
    async def mutate_chunk(request: Request):
        return await dispatch(request, ChunkMutationIntent, service.mutate_chunk, 200)

    @router.post(KnowledgeOperation.INSPECT_CHUNK.value, include_in_schema=False)
    async def inspect_chunk(request: Request):
        return await dispatch(request, ChunkMutationLookup, service.inspect_chunk, 200)

    @router.post(KnowledgeOperation.INSPECT_BASE.value, include_in_schema=False)
    async def inspect_base(request: Request):
        return await dispatch(request, KnowledgeBaseInspect, service.inspect_base, 200)

    @router.post(KnowledgeOperation.DELETE_BASE.value, include_in_schema=False)
    async def delete_base(request: Request):
        return await dispatch(request, KnowledgeBaseDelete, service.delete_base, 202)

    @router.post(KnowledgeOperation.INSPECT_BASE_DELETION.value, include_in_schema=False)
    async def inspect_base_deletion(request: Request):
        return await dispatch(request, KnowledgeBaseDeleteLookup, service.inspect_base_deletion, 200)

    return router
