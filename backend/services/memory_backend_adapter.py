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
    MemoryIngestUnit,
    MemoryLayer,
    MemorySearchRequest,
    MemorySearchResult,
)
from nexent.memory.service import MemoryService

from .memory_record_service import (
    MemoryRecordError,
    _resolve_tenant_embedding_model_info,
    get_memory_record_service,
)
from .memory_retrieval_service import get_memory_retrieval_service
from .memory_external_provider_service import get_memory_external_provider_service
from .memory_ingestion_event_service import MemoryIngestionEventService


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
    if hasattr(memory_type_value, "value"):
        memory_type_value = memory_type_value.value

    tenant_id = payload["tenant_id"]
    embedding = payload.get("embedding")
    embedding_model_info = None

    if embedding is None and layer_value == MemoryLayer.AGENT.value:
        embedding_model_info = _resolve_tenant_embedding_model_info(tenant_id)
        if embedding_model_info is None:
            raise MemoryRecordError(
                "Failed to store memory: tenant embedding model is not configured"
            )

    result = service.create_memory(
        tenant_id=tenant_id,
        user_id=payload["user_id"],
        content=payload["content"],
        layer=layer_value,
        memory_type=memory_type_value,
        agent_id=payload.get("agent_id"),
        conversation_id=(
            str(payload["conversation_id"])
            if payload.get("conversation_id") not in (None, "")
            else None
        ),
        idempotency_key=payload.get("idempotency_key"),
        embedding=embedding,
        embedding_model_info=embedding_model_info,
        actor="agent",
    )

    try:
        await _fanout_external_ingest(payload, result)
    except Exception as exc:
        logger.warning(
            "event=external_memory_ingest_failed tenant_id=%s event_type=memory_stored "
            "event_id=%s error_type=%s",
            tenant_id,
            result.get("memory_id", ""),
            type(exc).__name__,
            exc_info=True,
        )

    return result


def _build_ingestion_event_service():
    """Lazily construct a MemoryIngestionEventService for transparent proxy."""
    provider_service = get_memory_external_provider_service()
    return MemoryIngestionEventService(
        provider_service._config_service,
        provider_service,
    )


async def _fanout_external_ingest(
    payload: Dict[str, Any], result: Dict[str, Any]
) -> None:
    """Fan-out a store event to all enabled external providers."""
    tenant_id = payload["tenant_id"]
    provider_service = get_memory_external_provider_service()
    enabled = provider_service._config_service.get_enabled_providers(tenant_id)
    if not enabled:
        logger.info(
            "event=external_memory_ingest_skipped tenant_id=%s event_type=memory_stored "
            "event_id=%s reason=no_enabled_providers",
            tenant_id,
            result.get("memory_id", ""),
        )
        return

    provider_names = [str(config.get("provider_name", "unknown")) for config in enabled]
    logger.info(
        "event=external_memory_ingest_started tenant_id=%s event_type=memory_stored "
        "event_id=%s provider_count=%d providers=%s unit_count=1",
        tenant_id,
        result.get("memory_id", ""),
        len(enabled),
        ",".join(provider_names),
    )

    layer = payload.get("layer", MemoryLayer.AGENT.value)
    if hasattr(layer, "value"):
        layer = layer.value

    ingest_unit = MemoryIngestUnit(
        event_id=str(result.get("memory_id", "")),
        event_type="memory_stored",
        unit_type=str(layer),
        unit_content=payload["content"],
    )

    ingestion_service = _build_ingestion_event_service()
    ingest_results = await ingestion_service.send_ingest_all_enabled(
        tenant_id=tenant_id,
        user_id=payload["user_id"],
        agent_id=str(payload.get("agent_id", "")),
        conversation_id=str(payload.get("conversation_id", "")),
        event_type="memory_stored",
        event_id=str(result.get("memory_id", "")),
        units=[ingest_unit],
    )
    successful = sum(item.status in {"ok", "degraded"} for item in ingest_results)
    logger.info(
        "event=external_memory_ingest_completed tenant_id=%s event_type=memory_stored "
        "event_id=%s provider_count=%d success_count=%d failure_count=%d",
        tenant_id,
        result.get("memory_id", ""),
        len(enabled),
        successful,
        len(ingest_results) - successful,
    )


async def _backend_search_hook(
    payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Adapter for ``MemoryService.search_memory`` -> ``MemoryRetrievalService``."""
    if _resolve_tenant_embedding_model_info(payload["tenant_id"]) is None:
        return []
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

