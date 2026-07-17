"""Memory context builder for agent prompt injection.

Tenant/user long-term memory is always loaded in full (no vector search).
Agent short-term memory uses vector retrieval. The combined
``MemorySearchContext`` is what gets serialized into the prompt.

When the caller has not already resolved an ``EmbeddingModelInfo`` or computed
the query embedding, this service performs those steps internally so the app
layer can stay thin.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from nexent.memory.embedding_model import EmbeddingModelInfo
from nexent.memory.models import (
    MemoryLayer,
    MemorySearchContext,
    MemorySearchRequest,
    MemorySearchResult,
)
from nexent.memory.policy import MemoryRetrievalPolicy

from .memory_record_service import (
    _compute_content_embedding,
    _resolve_tenant_embedding_model_info,
)
from .memory_retrieval_service import (
    MemoryRetrievalService,
    get_memory_retrieval_service,
)


logger = logging.getLogger("memory_context_service")


def _prepare_search_embedding(
    *,
    query: Optional[str],
    embedding: Optional[List[float]],
    embedding_model_info: Optional[EmbeddingModelInfo],
    tenant_id: str,
) -> tuple[Optional[EmbeddingModelInfo], Optional[List[float]]]:
    """Resolve the embedding model and compute the query embedding when needed.

    Returns ``(model_info, embedding)``. If the caller already supplied both,
    they are returned unchanged. Otherwise, the tenant embedding model is
    resolved and the query is embedded so vector search can run.
    """
    if embedding is not None:
        # Caller pre-computed the vector; nothing to do.
        return embedding_model_info, embedding

    if not query:
        # No query and no embedding -> nothing to compute.
        return embedding_model_info, None

    resolved = embedding_model_info or _resolve_tenant_embedding_model_info(tenant_id)
    if resolved is None:
        return None, None

    computed = _compute_content_embedding(query, resolved)
    if computed is None:
        logger.warning(
            "query_embedding computation failed for tenant=%s", tenant_id
        )
    return resolved, computed


class MemoryContextService:
    """Compose the memory block injected into agent prompts."""

    def __init__(self, retrieval_service: Optional[MemoryRetrievalService] = None):
        self.retrieval_service = retrieval_service or get_memory_retrieval_service()

    async def build_context(
        self,
        *,
        tenant_id: str,
        user_id: str,
        agent_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        query: Optional[str] = None,
        top_k: int = 5,
        threshold: float = 0.65,
        embedding: Optional[List[float]] = None,
        embedding_model_info: Optional[EmbeddingModelInfo] = None,
        layers: Optional[List[str]] = None,
    ) -> MemorySearchContext:
        """Return a populated :class:`MemorySearchContext` for the agent.

        Full-context layers (tenant/user) are always loaded regardless of
        ``query``. Agent short-term memory requires a ``query`` (or a
        pre-computed ``embedding``). When neither is supplied, this service
        resolves the tenant's embedding model and computes the query embedding
        so vector search can still run.

        ``layers`` accepts plain string names (e.g. ``["tenant", "agent"]``);
        the app layer passes these directly without parsing.
        """
        # Parse string layer names into enums; fall back to defaults.
        if layers:
            target_layers: List[MemoryLayer] = []
            for value in layers:
                try:
                    target_layers.append(MemoryLayer(value.strip().lower()))
                except ValueError:
                    logger.warning("build_context: skipping unknown layer=%s", value)
            target_layers = target_layers or list(
                MemoryRetrievalPolicy.FULL_CONTEXT_LAYERS
                | MemoryRetrievalPolicy.VECTOR_SEARCH_LAYERS
            )
        else:
            target_layers = list(
                MemoryRetrievalPolicy.FULL_CONTEXT_LAYERS
                | MemoryRetrievalPolicy.VECTOR_SEARCH_LAYERS
            )

        resolved_model_info, resolved_embedding = _prepare_search_embedding(
            query=query,
            embedding=embedding,
            embedding_model_info=embedding_model_info,
            tenant_id=tenant_id,
        )

        request = MemorySearchRequest(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            layers=target_layers,
            query=query or "",
            top_k=top_k,
            threshold=threshold,
            embedding=resolved_embedding,
        )

        results = await self.retrieval_service.search(
            request,
            embedding_model_info=resolved_model_info,
            write_hits=bool(query),
        )

        context = MemorySearchContext()
        for result in results:
            if result.layer == MemoryLayer.TENANT:
                context.tenant_long_term.append(result)
            elif result.layer == MemoryLayer.USER:
                context.user_long_term.append(result)
            elif result.layer == MemoryLayer.AGENT:
                context.agent_short_term.append(result)
            elif result.is_external:
                context.external.append(result)
            else:
                # Unknown layer; fall back to external bucket to avoid
                # silently dropping content.
                context.external.append(result)
        return context


_default_service: Optional[MemoryContextService] = None


def get_memory_context_service() -> MemoryContextService:
    """Return the process-wide context service."""
    global _default_service
    if _default_service is None:
        _default_service = MemoryContextService()
    return _default_service


def reset_memory_context_service() -> None:
    """Reset the cached service (used by tests)."""
    global _default_service
    _default_service = None