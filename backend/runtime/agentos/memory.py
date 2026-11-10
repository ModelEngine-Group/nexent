# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Store Agent Memory inside Runtime through the signed AgentOS boundary."""

import logging
import math
from functools import cache, partial

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from contracts.agentos import (
    BODY_KEY, PRINCIPAL_KEY, AgentMemoryReceipt, AgentMemoryStore, EmbeddingInvocation, MemoryOperation,
)
from contracts.constants import environment
from infrastructure.agent_model_config import model_record_revision
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.model_adapter import get_adapter_from_config
from infrastructure.rdb.memory_store import (
    MemoryStoreConflictError, MemoryStoreScopeError, find_existing_memory, mirror_current_memory,
    read_memory_embedding_model_id, write_agent_memory,
)
from infrastructure.rdb.model_records import get_model_by_model_id
from infrastructure.vdb.client import create_elasticsearch_core
from infrastructure.vdb.memory_index import MemoryIndexService
from nexent.core.concurrency import run_blocking
from nexent.memory.embedding_model import EmbeddingModelInfo
from runtime.model.service import ModelService

logger = logging.getLogger(__name__)


def _load_embedding(tenant_id: str) -> EmbeddingModelInfo | None:
    model_id = read_memory_embedding_model_id(tenant_id)
    if model_id is None:
        return None
    record = get_model_by_model_id(model_id, tenant_id)
    if not record or record.get("model_type") not in {"embedding", "multi_embedding"} or not record.get("model_name"):
        return None
    try:
        dimension = int(record["max_tokens"])
    except (KeyError, TypeError, ValueError):
        return None
    if dimension <= 0:
        return None
    return EmbeddingModelInfo(
        model_id=model_id, revision=model_record_revision(record), dimension=dimension,
        model_name=record["model_name"], model_repo=record.get("model_repo"), base_url="", api_key="",
    )


async def _control(label, fn, *args):
    return await run_blocking(label, fn, *args, lane="control-io", owner="runtime.memory")


class AgentMemoryStoreService:
    def __init__(self, model_service, index_service: MemoryIndexService):
        self.model_service = model_service
        self.index_service = index_service

    async def _embed(self, payload, model, actor):
        try:
            result = await self.model_service.invoke(EmbeddingInvocation(
                model_id=model.model_id, expected_revision=model.revision, input=[payload.content],
            ), actor)
            output = result.output
            if (isinstance(output, list) and len(output) == 1 and isinstance(output[0], list)
                    and len(output[0]) == model.dimension
                    and all(type(value) in (int, float) and math.isfinite(value) for value in output[0])):
                return output[0]
        except Exception as exc:
            logger.warning("Memory embedding failed tenant=%s model_id=%s error_type=%s",
                           actor.tenant_id, model.model_id, type(exc).__name__)
        return None

    async def store(self, payload: AgentMemoryStore, actor: ServicePrincipal) -> AgentMemoryReceipt:
        scope = (actor.tenant_id, actor.user_id, payload.agent_id, payload.conversation_id, payload.idempotency_key)
        existing = await _control("memory-find-existing", find_existing_memory, *scope, payload.content)
        if existing is not None:
            return AgentMemoryReceipt(memory_id=existing, event="UNCHANGED")

        model = await _control("memory-load-embedding", _load_embedding, actor.tenant_id)
        if model is None:
            raise MemoryStoreModelError("MEMORY_EMBEDDING_NOT_CONFIGURED")
        if payload.embedding is not None and len(payload.embedding) != model.dimension:
            raise MemoryStoreModelError("MEMORY_EMBEDDING_DIMENSION_MISMATCH")

        embedding = payload.embedding if payload.embedding is not None else await self._embed(payload, model, actor)
        index_name = model.get_index_name()
        memory_id, event = await _control("memory-write-record", write_agent_memory, *scope, payload.content, index_name)
        indexed = False
        if event != "UNCHANGED":
            publish = partial(self.index_service.index_record, embedding=embedding, embedding_model_info=model)
            try:
                mirrored = await run_blocking(
                    "memory-index-record", mirror_current_memory, actor.tenant_id, payload.idempotency_key,
                    memory_id, payload.content, index_name, publish, lane="background-service", owner="runtime.memory",
                )
                indexed = bool(mirrored and embedding is not None)
            except Exception as exc:
                logger.warning("Memory index sync failed memory_id=%s error_type=%s", memory_id, type(exc).__name__)
        return AgentMemoryReceipt(memory_id=memory_id, event=event, indexed=indexed)


class MemoryStoreModelError(ValueError):
    """The Memory store cannot use the selected embedding model or supplied vector."""


def _build_memory_store_service(model_service, index_service=None):
    if index_service is None:
        index_service = MemoryIndexService(create_core=lambda: create_elasticsearch_core(
            host=environment.ES_HOST, api_key=environment.ES_API_KEY,
        ))
    return AgentMemoryStoreService(model_service, index_service)


@cache
def get_memory_store_service() -> AgentMemoryStoreService:
    return _build_memory_store_service(ModelService(get_model_by_model_id, get_adapter_from_config))


def create_memory_store_router(model_service=None, index_service=None) -> APIRouter:
    service = get_memory_store_service() if model_service is None else _build_memory_store_service(
        model_service, index_service,
    )
    router = APIRouter()

    @router.post(MemoryOperation.STORE.value, include_in_schema=False)
    async def store_memory(request: Request):
        actor = request.scope.get(PRINCIPAL_KEY)
        if actor is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = AgentMemoryStore.model_validate_json(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
        try:
            return await service.store(payload, actor)
        except MemoryStoreScopeError:
            return JSONResponse({"code": "MEMORY_SCOPE_NOT_FOUND"}, status_code=404)
        except MemoryStoreConflictError:
            return JSONResponse({"code": "MEMORY_IDEMPOTENCY_CONFLICT"}, status_code=409)
        except MemoryStoreModelError as exc:
            return JSONResponse({"code": str(exc)}, status_code=422)

    return router
