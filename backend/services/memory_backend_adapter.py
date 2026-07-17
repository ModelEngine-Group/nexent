"""Wire the SDK ``MemoryService`` facade to backend services.

The SDK does not depend on PostgreSQL or Elasticsearch. It accepts two
async hooks (``backend_store`` / ``backend_search``) and dispatches the
payloads through them. This module provides the backend-side adapter that
bridges those hooks to ``services.memory_record_service`` and
``services.memory_retrieval_service``.

Usage from the agent build path::

    from services.memory_backend_adapter import (
        build_memory_service_for_agent,
    )
    memory_service = build_memory_service_for_agent(
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        embedding_model_info=embedding_model_info,
    )
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from nexent.memory.embedding_model import EmbeddingModelInfo
from nexent.memory.models import (
    MemoryLayer,
    MemorySearchRequest,
    MemorySearchResult,
)
from nexent.memory.service import MemoryService

from .memory_record_service import (
    _resolve_tenant_embedding_model_info,
    get_memory_record_service,
)
from .memory_retrieval_service import get_memory_retrieval_service


logger = logging.getLogger("memory_backend_adapter")


async def _backend_store_hook(
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Adapter for ``MemoryService.store_memory`` -> ``MemoryRecordService``."""
    service = get_memory_record_service()
    layer_value = payload.get("layer", MemoryLayer.AGENT.value)
    if isinstance(layer_value, MemoryLayer):
        layer_value = layer_value.value

    memory_type_value = payload.get("memory_type")
    if isinstance(memory_type_value, MemoryLayer):
        memory_type_value = memory_type_value.value

    tenant_id = payload["tenant_id"]
    embedding = payload.get("embedding")
    embedding_model_info = None

    if embedding is None and layer_value == MemoryLayer.AGENT.value:
        embedding_model_info = _resolve_tenant_embedding_model_info(tenant_id)

    result = service.create_memory(
        tenant_id=tenant_id,
        user_id=payload["user_id"],
        content=payload["content"],
        layer=layer_value,
        memory_type=memory_type_value,
        agent_id=payload.get("agent_id"),
        conversation_id=payload.get("conversation_id"),
        idempotency_key=payload.get("idempotency_key"),
        embedding=embedding,
        embedding_model_info=embedding_model_info,
        actor="agent",
    )
    return result


async def _backend_search_hook(
    payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Adapter for ``MemoryService.search_memory`` -> ``MemoryRetrievalService``."""
    retrieval = get_memory_retrieval_service()
    request = MemorySearchRequest(
        tenant_id=payload["tenant_id"],
        user_id=payload["user_id"],
        agent_id=payload.get("agent_id"),
        conversation_id=payload.get("conversation_id"),
        layers=payload.get("layers") or [MemoryLayer.AGENT],
        query=payload.get("query", ""),
        top_k=int(payload.get("top_k") or 5),
        threshold=payload.get("threshold") or 0.65,
        embedding=payload.get("embedding"),
    )
    results: List[MemorySearchResult] = await retrieval.search(
        request, write_hits=True
    )
    return [
        {
            "memory_id": r.memory_id,
            "content": r.content,
            "score": r.score,
            "layer": r.layer.value if hasattr(r.layer, "value") else r.layer,
            "source": r.source,
            "is_external": r.is_external,
            "metadata": r.metadata,
        }
        for r in results
    ]


def build_memory_service_for_agent(
    *,
    tenant_id: str,
    user_id: str,
    agent_id: str,
    embedding_model_info: Optional[EmbeddingModelInfo] = None,
) -> MemoryService:
    """Construct a per-agent ``MemoryService`` wired to the backend hooks.

    The returned facade is the value passed to ``StoreMemoryTool`` and
    ``SearchMemoryTool`` when building the agent.
    """
    return MemoryService(
        embedding_model=None,
        embedding_model_info=embedding_model_info,
        backend_store=_backend_store_hook,
        backend_search=_backend_search_hook,
    )


def build_memory_service_for_dreaming() -> MemoryService:
    """Return a facade for Dreaming promotion (no embedding model needed).

    Dreaming promotes already-stored agent memories to user long-term
    memory and never needs the search hook. The store hook enforces the
    ``actor="dreaming"`` policy via ``MemoryRecordService``.
    """
    return MemoryService(
        embedding_model=None,
        embedding_model_info=None,
        backend_store=_backend_store_hook,
        backend_search=None,
    )