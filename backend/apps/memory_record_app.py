"""HTTP endpoints for managing internal memory records (Phase 2).

These endpoints are intentionally restricted to manual management of
tenant/user long-term memory. Agent short-term memory writes are routed
through the in-process ``StoreMemoryTool`` -> ``MemoryService`` pipeline,
not through HTTP, to keep the agent side lightweight.

Routes:

- POST   ``/memory/records``            Create a memory record
- GET    ``/memory/records/{memory_id}`` Read a record
- GET    ``/memory/records``            List records (with filters)
- PATCH  ``/memory/records/{memory_id}`` Update a record
- DELETE ``/memory/records/{memory_id}`` Soft-delete a record
- POST   ``/memory/records/search``     Run a retrieval
- GET    ``/memory/context``            Build an agent prompt context block

All endpoints scope results by ``(tenant_id, user_id, ...)`` derived from
the auth token. Tenant isolation keys are required and cannot be supplied
by the client.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.memory_context_service import get_memory_context_service
from services.memory_record_service import (
    MemoryRecordError,
    get_memory_record_service,
)
from services.memory_retrieval_service import get_memory_retrieval_service
from utils.auth_utils import get_current_user_id


logger = logging.getLogger("memory_record_app")
logger.setLevel(logging.DEBUG)
router = APIRouter(prefix="/memory")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateMemoryRequest(BaseModel):
    layer: str = Field(..., description="tenant | user | agent")
    content: str = Field(..., min_length=1)
    memory_type: Optional[str] = Field(
        default=None,
        description="long_term | short_term; defaults by layer",
    )
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    concept_tags: List[str] = Field(default_factory=list)
    idempotency_key: Optional[str] = None


class UpdateMemoryRequest(BaseModel):
    content: Optional[str] = None
    status: Optional[str] = None
    concept_tags: Optional[List[str]] = None


class SearchMemoryRequest(BaseModel):
    query: str
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    layers: Optional[List[str]] = None
    top_k: int = 5
    threshold: float = 0.65
    hybrid: bool = Field(
        default=False,
        description=(
            "When true, agent short-term memory is retrieved via a hybrid "
            "(BM25 + kNN) query against Elasticsearch instead of pure "
            "kNN. Defaults to false to preserve prior behavior."
        ),
    )
    weight_accurate: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description=(
            "Weight of the fuzzy (BM25) branch when hybrid=true. The "
            "complementary 1 - weight is given to the semantic kNN branch."
        ),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/records")
def create_record(
    payload: CreateMemoryRequest,
    authorization: Optional[str] = Header(None),
):
    """Create a memory record.

    Agents should not call this endpoint for short-term memory; they go
    through ``StoreMemoryTool``. The endpoint exists for tenant/user
    manual management and for Dreaming promotion.
    """
    user_id, tenant_id = get_current_user_id(authorization)
    service = get_memory_record_service()
    try:
        result = service.create_memory(
            tenant_id=tenant_id,
            user_id=user_id,
            content=payload.content,
            layer=payload.layer,
            memory_type=payload.memory_type,
            agent_id=payload.agent_id,
            conversation_id=payload.conversation_id,
            concept_tags=payload.concept_tags,
            idempotency_key=payload.idempotency_key,
            created_by=user_id,
            actor="system",
        )
    except MemoryRecordError as exc:
        raise HTTPException(
            status_code=HTTPStatus.NOT_ACCEPTABLE, detail=str(exc)
        )

    if not result.get("indexed") and result.get("layer") == "agent":
        logger.debug(
            "Created agent short-term memory memory_id=%s without ES indexing; "
            "check tenant embedding model configuration.",
            result.get("memory_id"),
        )

    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@router.get("/records/{memory_id}")
def read_record(
    memory_id: int = Path(..., description="Auto-incremented memory primary key."),
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id = get_current_user_id(authorization)
    service = get_memory_record_service()
    record = service.get_memory_for_user(
        memory_id=memory_id, tenant_id=tenant_id, user_id=user_id
    )
    if record is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Memory record not found"
        )
    return JSONResponse(status_code=HTTPStatus.OK, content=record)


@router.get("/records")
def list_records(
    authorization: Optional[str] = Header(None),
    layer: Optional[str] = Query(default=None),
    memory_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default="active"),
    agent_id: Optional[str] = Query(default=None),
    conversation_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    user_id, tenant_id = get_current_user_id(authorization)
    service = get_memory_record_service()
    rows = service.list_memories(
        tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        layer=layer.strip().lower() if layer else None,
        memory_type=memory_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"items": rows, "count": len(rows)},
    )


@router.patch("/records/{memory_id}")
def update_record(
    memory_id: int = Path(..., description="Auto-incremented memory primary key."),
    payload: UpdateMemoryRequest = Body(...),
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id = get_current_user_id(authorization)
    update_data: Dict[str, Any] = {"updated_by": user_id}
    if payload.content is not None:
        update_data["content"] = payload.content
    if payload.status is not None:
        update_data["status"] = payload.status
    if payload.concept_tags is not None:
        update_data["concept_tags"] = payload.concept_tags

    service = get_memory_record_service()
    ok = service.update_memory(memory_id, tenant_id, update_data)
    if not ok:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Failed to update memory record",
        )
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"success": True, "memory_id": memory_id},
    )


@router.delete("/records/{memory_id}")
def delete_record(
    memory_id: int = Path(..., description="Auto-incremented memory primary key."),
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id = get_current_user_id(authorization)
    service = get_memory_record_service()
    ok = service.soft_delete_memory(memory_id, tenant_id, updated_by=user_id)
    if not ok:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Failed to delete memory record",
        )
    return JSONResponse(
        status_code=HTTPStatus.OK, content={"success": True}
    )


@router.post("/records/search")
async def search_records(
    payload: SearchMemoryRequest,
    authorization: Optional[str] = Header(None),
):
    """Run a memory retrieval and return ranked hits.

    Layer resolution, embedding model lookup, and query vector computation are
    all handled inside the service layer.
    """
    user_id, tenant_id = get_current_user_id(authorization)
    retrieval = get_memory_retrieval_service()
    results = await retrieval.search_memories(
        tenant_id=tenant_id,
        user_id=user_id,
        query=payload.query,
        agent_id=payload.agent_id,
        conversation_id=payload.conversation_id,
        layers=payload.layers,
        top_k=payload.top_k,
        threshold=payload.threshold,
        hybrid=payload.hybrid,
        weight_accurate=payload.weight_accurate,
    )
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "items": [result.model_dump() for result in results],
            "count": len(results),
        },
    )


@router.get("/context")
async def build_context(
    authorization: Optional[str] = Header(None),
    query: Optional[str] = Query(default=None),
    agent_id: Optional[str] = Query(default=None),
    conversation_id: Optional[str] = Query(default=None),
    layers: Optional[str] = Query(
        default=None, description="Comma-separated layer names"
    ),
    top_k: int = Query(default=5, ge=1, le=100),
    threshold: float = Query(default=0.65, ge=0.0, le=1.0),
):
    """Return a memory context block ready for prompt injection."""
    user_id, tenant_id = get_current_user_id(authorization)

    parsed_layers: Optional[List[str]] = None
    if layers:
        parsed_layers = [v.strip().lower() for v in layers.split(",")]

    service = get_memory_context_service()
    context = await service.build_context(
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        query=query,
        top_k=top_k,
        threshold=threshold,
        layers=parsed_layers,
    )

    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "tenant_long_term": [r.model_dump() for r in context.tenant_long_term],
            "user_long_term": [r.model_dump() for r in context.user_long_term],
            "agent_short_term": [
                r.model_dump() for r in context.agent_short_term
            ],
            "external": [r.model_dump() for r in context.external],
            "prompt_text": context.to_prompt_text(),
        },
    )
