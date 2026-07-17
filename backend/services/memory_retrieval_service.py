"""Memory retrieval orchestration (Phase 2).

This service combines the two retrieval paths required by the design:

- **Full-context layers** (``tenant``, ``user``) are loaded verbatim from
  PostgreSQL. They are not vector-searched because they always fit in the
  context window (admin-curated tenant memory and the user's personal
  long-term memory).
- **Agent short-term memory** is retrieved via kNN against Elasticsearch,
  with the isolation scope enforced both at the SQL and ES levels.

A successful search also appends one ``memory_retrieval_hits_t`` row per
hit so Dreaming can aggregate recall statistics in batch.
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from nexent.memory.embedding_model import EmbeddingModelInfo
from nexent.memory.models import MemoryLayer, MemorySearchRequest, MemorySearchResult
from nexent.memory.policy import MemoryRetrievalPolicy

from database import memory_record_db, memory_retrieval_hit_db
from services.memory_index_service import (
    MemoryIndexService,
    get_memory_index_service,
)
from services.memory_record_service import (
    MemoryRecordService,
    _compute_content_embedding,
    _resolve_tenant_embedding_model_info,
    get_memory_record_service,
)


logger = logging.getLogger("memory_retrieval_service")
logger.setLevel(logging.DEBUG)


def _hash_query(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _iso_day(timestamp: Optional[datetime] = None) -> str:
    return (timestamp or datetime.utcnow()).date().isoformat()


def _serialize_record_as_result(
    record: Dict[str, Any],
    score: float = 1.0,
    is_external: bool = False,
) -> MemorySearchResult:
    layer_value = record.get("layer")
    try:
        layer_enum = MemoryLayer(layer_value) if layer_value else MemoryLayer.USER
    except ValueError:
        layer_enum = MemoryLayer.USER
    return MemorySearchResult(
        memory_id=record.get("memory_id"),
        external_id=None,
        content=record.get("content", ""),
        score=float(score),
        layer=layer_enum,
        source="internal",
        is_external=is_external,
        metadata={
            "tenant_id": record.get("tenant_id"),
            "user_id": record.get("user_id"),
            "agent_id": record.get("agent_id"),
            "conversation_id": record.get("conversation_id"),
            "memory_type": record.get("memory_type"),
            "status": record.get("status"),
            "concept_tags": record.get("concept_tags") or [],
        },
    )


class MemoryRetrievalService:
    """Composite retrieval service (PG + ES) for internal memory."""

    def __init__(
        self,
        record_service: Optional[MemoryRecordService] = None,
        index_service: Optional[MemoryIndexService] = None,
    ):
        self.record_service = record_service or get_memory_record_service()
        self.index_service = index_service or get_memory_index_service()

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    async def search(
        self,
        request: MemorySearchRequest,
        *,
        embedding_model_info: Optional[EmbeddingModelInfo] = None,
        write_hits: bool = True,
    ) -> List[MemorySearchResult]:
        """Run a retrieval against the requested layers.

        ``layers`` controls which layers are queried. Layers not supported
        by the current backend (e.g. agent without ES) return empty.
        """
        top_k = MemoryRetrievalPolicy.validate_top_k(request.top_k)
        results: List[MemorySearchResult] = []

        layers = request.layers or [
            MemoryLayer.TENANT,
            MemoryLayer.USER,
            MemoryLayer.AGENT,
        ]

        for layer in layers:
            if MemoryRetrievalPolicy.uses_full_context(layer):
                results.extend(
                    self._full_context_search(request=request, layer=layer.value)
                )
            elif MemoryRetrievalPolicy.uses_vector_search(layer):
                results.extend(
                    self._vector_search(
                        request=request,
                        layer=layer.value,
                        top_k=top_k,
                        embedding_model_info=embedding_model_info,
                    )
                )
            else:
                logger.debug("search: unsupported layer %s", layer)

        if write_hits and results:
            self._record_hits(request=request, results=results)

        return results[:top_k]

    async def search_memories(
        self,
        tenant_id: str,
        user_id: str,
        query: str,
        *,
        agent_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        layers: Optional[List[str]] = None,
        top_k: int = 5,
        threshold: float = 0.65,
        write_hits: bool = True,
        hybrid: bool = False,
        weight_accurate: float = 0.3,
    ) -> List[MemorySearchResult]:
        """High-level memory search for the app layer.

        Accepts plain string layer names and resolves the tenant embedding
        model internally so callers do not need to handle that plumbing.

        When ``hybrid`` is true the agent short-term branch is delegated
        to ``ElasticSearchCore.hybrid_search`` so fuzzy (BM25) and
        semantic (kNN) scores are blended; ``weight_accurate`` controls
        the BM25 weight. Defaults preserve the legacy pure-kNN path.

        Returns a list of :class:`MemorySearchResult`.
        """
        # Parse and validate layer names.
        resolved_layers: List[MemoryLayer] = []
        defaults = ["agent"] if layers is None else layers
        for value in defaults:
            try:
                resolved_layers.append(MemoryLayer(value.strip().lower()))
            except ValueError:
                logger.debug("search_memories: skipping unknown layer=%s", value)

        # Resolve embedding model for the agent layer.
        embedding_model_info = _resolve_tenant_embedding_model_info(tenant_id)
        logger.debug(
            "[SEARCH] tenant_id=%s embedding_model=%s hybrid=%s",
            tenant_id,
            embedding_model_info.model_name if embedding_model_info else None,
            hybrid,
        )

        # Compute query embedding when a model is available.
        embedding: Optional[List[float]] = None
        if query and embedding_model_info:
            embedding = _compute_content_embedding(query, embedding_model_info)
            logger.debug(
                "[SEARCH] query_embedding computed=%s dimension=%s",
                embedding is not None,
                len(embedding) if embedding else None,
            )

        request = MemorySearchRequest(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            layers=resolved_layers,
            query=query,
            top_k=top_k,
            threshold=threshold,
            embedding=embedding,
            hybrid=hybrid,
            weight_accurate=weight_accurate,
        )

        return await self.search(
            request, embedding_model_info=embedding_model_info, write_hits=write_hits
        )

    # ------------------------------------------------------------------ #
    # Layer-specific strategies                                           #
    # ------------------------------------------------------------------ #

    def _full_context_search(
        self,
        *,
        request: MemorySearchRequest,
        layer: str,
    ) -> List[MemorySearchResult]:
        rows = self.record_service.list_memories(
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            layer=layer,
            memory_type="long_term",
            status="active",
            limit=1000,
        )
        return [_serialize_record_as_result(row, score=1.0) for row in rows]

    def _vector_search(
        self,
        *,
        request: MemorySearchRequest,
        layer: str,
        top_k: int,
        embedding_model_info: Optional[EmbeddingModelInfo],
    ) -> List[MemorySearchResult]:
        embedding = request.embedding
        logger.debug("[VECTOR_SEARCH] layer=%s embedding=%s embedding_model_info=%s hybrid=%s",
                    layer, embedding is not None, embedding_model_info is not None,
                    getattr(request, "hybrid", False))
        if embedding is None or not embedding_model_info:
            logger.debug("[VECTOR_SEARCH] early_return: embedding or model_info is None")
            return []

        index_name = embedding_model_info.get_index_name()
        logger.debug("[VECTOR_SEARCH] index_name=%s", index_name)
        if not index_name:
            logger.debug("[VECTOR_SEARCH] early_return: no index_name")
            return []

        # The hybrid branch in ``search_similar`` needs an actual
        # ``OpenAICompatibleEmbedding`` instance so it can re-vectorise
        # ``query_text`` via ``hybrid_search``. Build it lazily so that the
        # default (hybrid=False) path doesn't pay this cost.
        embedding_client = None
        if getattr(request, "hybrid", False):
            try:
                from nexent.memory.embedding_model import get_embedding_client
                embedding_client = get_embedding_client(
                    model_name=embedding_model_info.model_name,
                    dimension=embedding_model_info.dimension,
                    base_url=embedding_model_info.base_url,
                    api_key=embedding_model_info.api_key,
                    model_repo=embedding_model_info.model_repo,
                    ssl_verify=embedding_model_info.ssl_verify,
                )
            except Exception:
                logger.exception(
                    "[VECTOR_SEARCH] failed to build embedding client for hybrid; "
                    "search_similar will fall back to kNN.",
                )

        raw_hits = self.index_service.search_similar(
            index_name=index_name,
            embedding=list(embedding),
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            agent_id=request.agent_id,
            conversation_id=request.conversation_id,
            top_k=top_k,
            hybrid=getattr(request, "hybrid", False),
            query_text=request.query if getattr(request, "hybrid", False) else None,
            weight_accurate=getattr(request, "weight_accurate", 0.3),
            embedding_model=embedding_client,
        )

        logger.debug("[VECTOR_SEARCH] raw_hits_count=%d", len(raw_hits))
        if not raw_hits:
            return []

        # Apply threshold filter; fall back to policy default if None.
        threshold = (
            request.threshold
            if request.threshold is not None
            else MemoryRetrievalPolicy.DEFAULT_THRESHOLD
        )
        logger.debug("[VECTOR_SEARCH] threshold=%s", threshold)

        results: List[MemorySearchResult] = []
        memory_ids: List[int] = []
        for hit in raw_hits:
            logger.debug("[VECTOR_SEARCH] processing hit: score=%s threshold=%s", hit["score"], threshold)
            if hit["score"] < threshold:
                continue
            try:
                memory_id_int = int(hit["memory_id"])
            except (TypeError, ValueError):
                logger.warning(
                    "vector_search: ignoring non-integer memory_id from ES: %r",
                    hit.get("memory_id"),
                )
                continue
            memory_ids.append(memory_id_int)
            try:
                layer_enum = MemoryLayer(hit.get("layer") or layer)
            except ValueError:
                layer_enum = MemoryLayer.AGENT
            results.append(
                MemorySearchResult(
                    memory_id=memory_id_int,
                    external_id=None,
                    content=hit.get("content", ""),
                    score=float(hit.get("score", 0.0)),
                    layer=layer_enum,
                    source="internal",
                    is_external=False,
                    metadata=hit.get("metadata", {}),
                )
            )
        logger.debug("[VECTOR_SEARCH] results_after_threshold=%d", len(results))

        # Backfill the PG row so callers can fetch full record details.
        if memory_ids:
            rows = memory_record_db.get_memory_records_by_ids(
                memory_ids, request.tenant_id
            )
            logger.debug("[VECTOR_SEARCH] pg_records_fetched=%d", len(rows))
            by_id = {row["memory_id"]: row for row in rows}
            enriched: List[MemorySearchResult] = []
            for result in results:
                try:
                    key = int(result.memory_id) if result.memory_id else None
                except (TypeError, ValueError):
                    key = None
                row = by_id.get(key) if key is not None else None
                if row is None:
                    enriched.append(result)
                    continue
                result.metadata = {
                    **result.metadata,
                    "memory_type": row.get("memory_type"),
                    "status": row.get("status"),
                    "concept_tags": row.get("concept_tags") or [],
                }
                enriched.append(result)
            return enriched

        return results

    # ------------------------------------------------------------------ #
    # Hit logging                                                        #
    # ------------------------------------------------------------------ #

    def _record_hits(
        self,
        *,
        request: MemorySearchRequest,
        results: List[MemorySearchResult],
    ) -> None:
        now = datetime.utcnow()
        day = _iso_day(now)
        query_hash = _hash_query(request.query)

        rows: List[Dict[str, Any]] = []
        for result in results:
            if not result.memory_id:
                continue
            try:
                memory_id_int = int(result.memory_id)
            except (TypeError, ValueError):
                logger.warning(
                    "record_hits: skipping non-integer memory_id %r",
                    result.memory_id,
                )
                continue
            rows.append(
                {
                    "tenant_id": request.tenant_id,
                    "user_id": request.user_id,
                    "agent_id": request.agent_id,
                    "conversation_id": request.conversation_id,
                    "memory_id": memory_id_int,
                    "query_text": request.query,
                    "query_hash": query_hash,
                    "retrieval_score": result.score,
                    "source": "nexent",
                    "occurred_at": now,
                    "day": day,
                    "grounded": False,
                }
            )

        if rows:
            try:
                memory_retrieval_hit_db.insert_retrieval_hits(rows)
            except Exception:
                logger.exception(
                    "search: failed to record retrieval hits for tenant=%s",
                    request.tenant_id,
                )


# ---------------------------------------------------------------------------
# Module-level accessors
# ---------------------------------------------------------------------------


_default_service: Optional[MemoryRetrievalService] = None


def get_memory_retrieval_service() -> MemoryRetrievalService:
    """Return the process-wide retrieval service."""
    global _default_service
    if _default_service is None:
        _default_service = MemoryRetrievalService()
    return _default_service


def reset_memory_retrieval_service() -> None:
    """Reset the cached service (used by tests)."""
    global _default_service
    _default_service = None