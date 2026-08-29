"""Memory context builder for agent prompt injection.

Tenant/user long-term memory is always loaded in full (no vector search).
Agent short-term memory uses vector retrieval.  When Phase 4 is enabled
(pipeline_enabled=True), the raw retrieval results are additionally
processed through the SDK's RetrievalPipeline which applies:

    normalize -> score fusion -> temporal decay -> MMR -> token budget selection

The resulting MemorySearchContext is what gets serialized into the prompt.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from nexent.memory.embedding_model import EmbeddingModelInfo
from nexent.memory.models import (
    ExternalMemoryItem,
    MemoryLayer,
    MemorySearchContext,
    MemorySearchRequest,
    PipelineConfig,
)
from nexent.memory.retrieval.pipeline import RetrievalPipeline
from nexent.memory.policy import MemoryRetrievalPolicy

from consts.const import (
    AGENT_SHORT_TERM_HALF_LIFE_DAYS,
    EXTERNAL_MEMORY_SEARCH_ENABLED,
    MMR_CANDIDATE_TOP_K,
    MMR_DUPLICATE_THRESHOLD,
    MMR_FINAL_TOP_K,
    MMR_LAMBDA,
    MEMORY_TOKEN_BUDGET,
    W_AGENT_SHORT_TERM,
    W_EXTERNAL,
)

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
    """Resolve the embedding model and compute the query embedding when needed."""
    if embedding is not None:
        return embedding_model_info, embedding
    if not query:
        return embedding_model_info, None
    resolved = embedding_model_info or _resolve_tenant_embedding_model_info(tenant_id)
    if resolved is None:
        return None, None
    computed = _compute_content_embedding(query, resolved)
    if computed is None:
        logger.warning("query_embedding computation failed for tenant=%s", tenant_id)
    return resolved, computed


def _build_pipeline_config() -> PipelineConfig:
    """Build a PipelineConfig from the env vars in const.py."""
    return PipelineConfig(
        mmr_lambda=MMR_LAMBDA,
        mmr_candidate_top_k=MMR_CANDIDATE_TOP_K,
        mmr_final_top_k=MMR_FINAL_TOP_K,
        mmr_duplicate_threshold=MMR_DUPLICATE_THRESHOLD,
        half_life_days=AGENT_SHORT_TERM_HALF_LIFE_DAYS,
        w_agent_short_term=W_AGENT_SHORT_TERM,
        w_external=W_EXTERNAL,
        token_budget=MEMORY_TOKEN_BUDGET,
    )


class MemoryContextService:
    """Compose the memory block injected into agent prompts."""

    def __init__(
        self,
        retrieval_service: Optional[MemoryRetrievalService] = None,
        pipeline_enabled: bool = True,
        external_search_hook: Optional[Callable] = None,
    ):
        """Initialize the context service.

        Args:
            retrieval_service: Optional injected retrieval service.
            pipeline_enabled: When True (default), the Phase 4 retrieval
                pipeline is applied to agent short-term + external results.
                Set to False to preserve the Phase 2 behaviour.
            external_search_hook: Optional async callable for Phase 3
                transparent proxy.  Signature:
                ``async (query, tenant_id, user_id, agent_id, conversation_id)
                -> List[ExternalMemoryItem]``.
                When set and ``EXTERNAL_MEMORY_SEARCH_ENABLED`` is True,
                ``build_context`` auto-queries external providers if
                ``external_results`` was not explicitly passed.
        """
        self.retrieval_service = retrieval_service or get_memory_retrieval_service()
        self.pipeline_enabled = pipeline_enabled
        self._external_search_hook = external_search_hook
        self._pipeline: Optional[RetrievalPipeline] = None

    @property
    def pipeline(self) -> RetrievalPipeline:
        """Lazily-built retrieval pipeline instance."""
        if self._pipeline is None:
            cfg = _build_pipeline_config()
            self._pipeline = RetrievalPipeline(cfg)
        return self._pipeline

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
        external_results: Optional[List[ExternalMemoryItem]] = None,
        created_at_for_id: Optional[Dict[int, Any]] = None,
    ) -> MemorySearchContext:
        """Return a populated MemorySearchContext for the agent.

        Full-context layers (tenant/user) are always loaded verbatim.
        Agent short-term memory is retrieved via vector search and, when
        pipeline_enabled is True, passed through the Phase 4 pipeline.

        Args:
            tenant_id: Tenant identifier.
            user_id: User identifier.
            agent_id: Optional agent identifier.
            conversation_id: Optional conversation identifier.
            query: Optional search query for vector retrieval.
            top_k: Maximum number of agent short-term results to return.
            threshold: Minimum similarity threshold for vector search.
            embedding: Optional pre-computed query embedding vector.
            embedding_model_info: Optional pre-resolved embedding model info.
            layers: Optional list of layer names to search.
            external_results: Optional external provider hits from Phase 3.
            created_at_for_id: Optional mapping of memory_id -> create_time.
        """
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
        logger.info(
            "event=memory_context_internal_search_completed tenant_id=%s "
            "result_count=%d external_prefetched=%s",
            tenant_id,
            len(results),
            external_results is not None,
        )

        if (
            external_results is None
            and EXTERNAL_MEMORY_SEARCH_ENABLED
            and self._external_search_hook is not None
        ):
            try:
                external_results = await self._external_search_hook(
                    query=query or "",
                    tenant_id=tenant_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                )
                logger.info(
                    "event=memory_context_external_search_completed tenant_id=%s "
                    "result_count=%d",
                    tenant_id,
                    len(external_results or []),
                )
            except Exception:
                logger.warning(
                    "external_search_hook failed for tenant=%s",
                    tenant_id,
                    exc_info=True,
                )

        if self.pipeline_enabled and (results or external_results):
            pipeline_result = self.pipeline.run(
                internal_results=results,
                query=query or "",
                external_results=external_results,
                created_at_for_id=created_at_for_id,
            )
            context = pipeline_result.into_memory_search_context()
            logger.info(
                "event=memory_context_pipeline_completed tenant_id=%s internal_count=%d "
                "external_count=%d final_count=%d",
                tenant_id,
                len(results),
                len(external_results or []),
                len(getattr(pipeline_result, "final_memory_records", [])),
            )
        else:
            context = MemorySearchContext()
            for result in results:
                if result.layer == MemoryLayer.TENANT:
                    context.tenant_long_term.append(result)
                elif result.layer == MemoryLayer.USER:
                    context.user_long_term.append(result)
                elif result.layer == MemoryLayer.AGENT:
                    context.agent_short_term.append(result)
                else:
                    context.external.append(result)
            context.external.extend(external_results or [])

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
