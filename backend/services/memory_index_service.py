"""Elasticsearch index management for agent short-term memory.

This service owns the ES side of the memory pipeline:

- create / ensure the per-tenant index (one index per embedding model)
- index/update/delete chunk documents mirroring ``memory_records_t``
- run kNN searches and return normalized hit dicts

The corresponding PostgreSQL row is always written first by
``services.memory_record_service``. ``MemoryIndexService`` only deals with
the vector side and never modifies PG state directly.

Failure modes:
- If ES is unavailable, ``memory_record_service`` keeps the PG row but skips
  the mirror; the row stays usable for full-text reads and ``es_index_name``
  remains set so a later retry can backfill it.
- Per-document failures during writes do not abort the batch; the function
  returns a summary so the caller can decide what to do.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional

from nexent.memory.embedding_model import EmbeddingModelInfo
from nexent.memory.models import MemoryLayer
from nexent.vector_database.base import VectorDatabaseCore

from services.vectordatabase_service import get_vector_db_core
from consts.const import VectorDatabaseType


logger = logging.getLogger("memory_index_service")
logger.setLevel(logging.DEBUG)


def _memory_chunk_payload(
    record: Dict[str, Any],
    embedding: List[float],
    index_name: str,
) -> Dict[str, Any]:
    """Translate a memory record into the chunk document shape used by ES.

    ``memory_id`` is an integer on the PG side; Elasticsearch ``_id`` is
    always a string, so the integer is stringified before being used as
    document id / path.
    """
    memory_id = str(record["memory_id"])
    layer = record.get("layer", "")
    is_agent_layer = layer == MemoryLayer.AGENT.value
    chunk = {
        "id": memory_id,
        "title": f"Short-term Memory {memory_id}" if is_agent_layer else f"Long-term user memory {memory_id}",
        "author": record.get("created_by"),
        "date": record.get("update_time"),
        "content": record.get("content", ""),
        "embedding_model_name": index_name,
        "embedding": embedding,
        "create_time": record.get("create_time"),
        "metadata": {
            "memory_id": memory_id,
            "tenant_id": record.get("tenant_id"),
            "user_id": record.get("user_id"),
            "agent_id": record.get("agent_id"),
            "conversation_id": record.get("conversation_id"),
            "layer": layer,
            "memory_type": record.get("memory_type"),
            "status": record.get("status"),
            "idempotency_key": record.get("idempotency_key"),
        },
    }

    return chunk


class MemoryIndexService:
    """Elasticsearch-backed index for agent short-term memory."""

    def __init__(self, vdb_core: Optional[VectorDatabaseCore] = None):
        self._vdb_core = vdb_core

    @property
    def vdb_core(self) -> VectorDatabaseCore:
        if self._vdb_core is None:
            self._vdb_core = get_vector_db_core(VectorDatabaseType.ELASTICSEARCH)
        return self._vdb_core

    # ------------------------------------------------------------------ #
    # Index lifecycle                                                    #
    # ------------------------------------------------------------------ #

    def ensure_index(self, index_name: str, embedding_dim: Optional[int] = None) -> bool:
        """Create the memory index if it does not exist."""
        try:
            return self.vdb_core.create_index(index_name, embedding_dim=embedding_dim)
        except Exception:
            logger.exception("ensure_index failed for %s", index_name)
            return False

    def drop_index(self, index_name: str) -> bool:
        """Delete an entire memory index (used by tenant purge)."""
        try:
            return self.vdb_core.delete_index(index_name)
        except Exception:
            logger.exception("drop_index failed for %s", index_name)
            return False

    # ------------------------------------------------------------------ #
    # Document CRUD                                                      #
    # ------------------------------------------------------------------ #

    def index_record(
        self,
        record: Dict[str, Any],
        embedding: Optional[List[float]],
        embedding_model_info: Optional[EmbeddingModelInfo] = None,
    ) -> bool:
        """Upsert a single memory record into its target index.

        Args:
            record: Serialized memory record (must include ``memory_id``,
                ``tenant_id``, ``user_id``, ``content``, etc.).
            embedding: Embedding vector; required for vector search.
            embedding_model_info: Used to resolve the index name when
                ``record["es_index_name"]`` is missing.

        Returns:
            True if the document was indexed (or already existed), False on
            transport failure.
        """
        index_name = record.get("es_index_name")
        if not index_name and embedding_model_info is not None:
            index_name = embedding_model_info.get_index_name()
        if not index_name:
            logger.warning("index_record: no index name resolved for memory_id=%s",
                           record.get("memory_id"))
            return False

        embedding_dim = (
            embedding_model_info.dimension if embedding_model_info else None
        )
        self.ensure_index(index_name, embedding_dim=embedding_dim)

        try:
            self.vdb_core.create_chunk(
                index_name=index_name,
                chunk=_memory_chunk_payload(record, embedding, index_name),
            )
            return True
        except Exception:
            logger.exception(
                "index_record: failed to index memory_id=%s into %s",
                record.get("memory_id"),
                index_name,
            )
            return False

    def delete_record(self, memory_id: int, index_name: str) -> bool:
        """Remove a single memory document from ES."""
        try:
            return bool(self.vdb_core.delete_chunk(index_name, str(memory_id)))
        except Exception:
            logger.exception("delete_record failed for %s", memory_id)
            return False

    # ------------------------------------------------------------------ #
    # Search                                                             #
    # ------------------------------------------------------------------ #

    def search_similar(
        self,
        *,
        index_name: str,
        embedding: List[float],
        tenant_id: str,
        user_id: str,
        agent_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        top_k: int = 5,
        hybrid: bool = False,
        query_text: Optional[str] = None,
        weight_accurate: float = 0.3,
        embedding_model: Any = None,
    ) -> List[Dict[str, Any]]:
        """Run a memory search scoped to the agent's isolation boundary.

        Args:
            index_name: ES index carrying the tenant's per-embedding-model
                memory chunks.
            embedding: Pre-computed query embedding (used by the pure kNN
                branch).
            tenant_id / user_id / agent_id / conversation_id: isolation keys
                compiled into an ES ``bool.filter`` so callers never see
                another tenant's or another conversation's memories.
            top_k: Maximum number of hits to return.
            hybrid: When ``True``, delegate to
                :py:meth:`ElasticSearchCore.hybrid_search` so fuzzy
                (BM25) and semantic (kNN) scores are blended. Requires
                both ``query_text`` and ``embedding_model`` to be supplied.
                When ``False`` (the default), behaviour is bit-for-bit
                identical to the previous release: a single kNN query.
            query_text: Raw user query, required when ``hybrid=True`` so the
                fuzzy branch has something to score against.
            weight_accurate: Weight of the fuzzy (BM25) branch in the hybrid
                combination; ignored unless ``hybrid=True``.
            embedding_model: Embedding model instance (carries the HTTP client
                + dimension metadata) used by ``hybrid_search`` to re-vectorise
                ``query_text``. Ignored unless ``hybrid=True``.

        Returns:
            A list of normalized result dicts ready to be passed to
            ``MemoryService._to_search_result``.

        Notes:
            Elasticsearch dynamically maps string ``metadata.*`` fields to
            ``text`` (analyzed). UUID-like values get tokenized by the
            standard analyzer, so a bare ``term`` filter on
            ``metadata.tenant_id`` would never match. We therefore query
            the auto-generated ``.keyword`` sub-field for exact equality.
        """
        logger.debug(
            "[ES_SEARCH] index=%s tenant_id=%s user_id=%s agent_id=%s top_k=%s "
            "embedding_len=%d hybrid=%s weight_accurate=%s",
            index_name, tenant_id, user_id, agent_id, top_k, len(embedding),
            hybrid, weight_accurate,
        )

        if not index_name or not embedding:
            return []

        isolation_filter = self._build_isolation_filter(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
        )

        if hybrid:
            if not query_text or embedding_model is None:
                logger.warning(
                    "[ES_SEARCH] hybrid requested without query_text or "
                    "embedding_model; falling back to kNN path.",
                )
            else:
                return self._hybrid_search_similar(
                    index_name=index_name,
                    query_text=query_text,
                    embedding=embedding,
                    embedding_model=embedding_model,
                    isolation_filter=isolation_filter,
                    top_k=top_k,
                    weight_accurate=weight_accurate,
                )

        return self._knn_search_similar(
            index_name=index_name,
            embedding=embedding,
            isolation_filter=isolation_filter,
            top_k=top_k,
        )

    # ------------------------------------------------------------------ #
    # Search helpers (split for readability and unit testing)            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_isolation_filter(
        *,
        tenant_id: str,
        user_id: str,
        agent_id: Optional[str],
        conversation_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Assemble the ES ``filter`` clause that enforces memory isolation."""
        must_filters: List[Dict[str, Any]] = [
            {"term": {"metadata.tenant_id.keyword": tenant_id}},
            {"term": {"metadata.user_id.keyword": user_id}},
        ]
        if agent_id is not None:
            must_filters.append({"term": {"metadata.agent_id.keyword": agent_id}})
        if conversation_id is not None:
            must_filters.append(
                {"term": {"metadata.conversation_id.keyword": conversation_id}}
            )
        must_filters.append({"term": {"metadata.layer.keyword": "agent"}})
        return must_filters

    def _knn_search_similar(
        self,
        *,
        index_name: str,
        embedding: List[float],
        isolation_filter: List[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Pure kNN branch (unchanged from the previous release)."""
        query = {
            "knn": {
                "field": "embedding",
                "query_vector": list(embedding),
                "k": max(1, int(top_k)),
                "num_candidates": max(50, int(top_k) * 10),
                "filter": {"bool": {"must": isolation_filter}},
            },
            "size": max(1, int(top_k)),
        }
        logger.debug("[ES_QUERY] knn_query=%s", json.dumps(query, indent=2))

        try:
            response = self.vdb_core.search(index_name=index_name, query=query)
            response_body = response.body if hasattr(response, "body") else response
            logger.debug(
                "[ES_RESPONSE] response_type=%s hits=%s score_min=%s",
                type(response).__name__,
                (response_body or {}).get("hits", {}).get("total", {}).get("value"),
                _safe_score_preview(response_body),
            )
        except Exception:
            logger.exception("search_similar failed for %s", index_name)
            return []

        hits = (response_body or {}).get("hits", {}).get("hits", []) or []
        logger.debug("[ES_HITS] hit_count=%d", len(hits))

        return [_hit_to_memory_result(hit) for hit in hits]

    def _hybrid_search_similar(
        self,
        *,
        index_name: str,
        query_text: str,
        embedding: List[float],
        embedding_model: Any,
        isolation_filter: List[Dict[str, Any]],
        top_k: int,
        weight_accurate: float,
    ) -> List[Dict[str, Any]]:
        """Hybrid (BM25 + kNN) branch with the same isolation filter.

        Reuses ``ElasticSearchCore.hybrid_search``; we only widen the
        filter so the existing knowledge-base business logic is unaffected
        (the existing ``search_hybrid`` in ``vectordatabase_service`` never
        passes this ``filter`` arg).
        """
        from nexent.vector_database.elasticsearch_core import ElasticSearchCore

        vdb_core = self.vdb_core
        # DataMate / mock backends don't accept ``filter``; fall back to
        # the kNN path for them rather than risk a type error.
        if not isinstance(vdb_core, ElasticSearchCore):
            logger.warning(
                "[ES_SEARCH] hybrid requested on non-ES backend %s; "
                "falling back to kNN.",
                type(vdb_core).__name__,
            )
            return self._knn_search_similar(
                index_name=index_name,
                embedding=embedding,
                isolation_filter=isolation_filter,
                top_k=top_k,
            )

        logger.debug(
            "[ES_HYBRID] weight_accurate=%s filter_terms=%d query_text=%r",
            weight_accurate, len(isolation_filter), query_text,
        )

        try:
            raw = vdb_core.hybrid_search(
                index_names=[index_name],
                query_text=query_text,
                embedding_model=embedding_model,
                top_k=max(1, int(top_k)),
                weight_accurate=weight_accurate,
                filter={"bool": {"must": isolation_filter}},
            )
        except TypeError:
            # Defensive fallback if an older implementation missing the
            # ``filter`` kwarg is wired in. Mirrors the legacy behaviour
            # without the isolation filter, which is unsafe but matches
            # the original SDK contract.
            logger.warning(
                "[ES_HYBRID] hybrid_search rejected ``filter`` kwarg; "
                "retrying without isolation filter.",
            )
            raw = vdb_core.hybrid_search(
                index_names=[index_name],
                query_text=query_text,
                embedding_model=embedding_model,
                top_k=max(1, int(top_k)),
                weight_accurate=weight_accurate,
            )
        except Exception:
            logger.exception("hybrid_search failed for %s", index_name)
            return []

        results: List[Dict[str, Any]] = []
        for item in raw or []:
            document = item.get("document") or {}
            metadata = document.get("metadata") or {}
            hit_id = item.get("index", index_name) + ":" + str(
                document.get("id") or metadata.get("memory_id") or ""
            )
            logger.debug(
                "[ES_HYBRID_HIT] doc_id=%s combined_score=%s",
                hit_id,
                item.get("score"),
            )
            results.append({
                "memory_id": document.get("id") or metadata.get("memory_id"),
                "content": document.get("content", ""),
                "score": float(item.get("score") or 0.0),
                "layer": metadata.get("layer", "agent"),
                "memory_type": metadata.get("memory_type", "short_term"),
                "source": "internal",
                "is_external": False,
                "metadata": metadata,
                "score_details": item.get("scores", {}),
            })
        logger.debug("[ES_HYBRID] combined_hit_count=%d", len(results))
        return results


def _safe_score_preview(response_body: Any) -> Any:
    """Return a compact score summary for the ES response log line."""
    try:
        hits = (response_body or {}).get("hits", {}).get("hits", []) or []
        if not hits:
            return None
        scores = [h.get("_score") for h in hits if h.get("_score") is not None]
        if not scores:
            return None
        return {"min": min(scores), "max": max(scores)}
    except Exception:
        return None


def _hit_to_memory_result(hit: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a raw ES hit into the normalized memory result shape."""
    source = hit.get("_source") or {}
    metadata = source.get("metadata") or {}
    logger.debug("[ES_HIT] id=%s memory_id=%s score=%s layer=%s",
                 hit.get("_id"),
                 metadata.get("memory_id"),
                 hit.get("_score"),
                 metadata.get("layer"))
    return {
        "memory_id": hit.get("_id") or source.get("id"),
        "content": source.get("content", ""),
        "score": float(hit.get("_score") or 0.0),
        "layer": metadata.get("layer", "agent"),
        "memory_type": metadata.get("memory_type", "short_term"),
        "source": "internal",
        "is_external": False,
        "metadata": metadata,
    }


# Singleton-style accessor matching the rest of the service modules.
_default_service: Optional[MemoryIndexService] = None


def get_memory_index_service() -> MemoryIndexService:
    """Return a process-wide MemoryIndexService."""
    global _default_service
    if _default_service is None:
        _default_service = MemoryIndexService()
    return _default_service


def reset_memory_index_service() -> None:
    """Reset the cached service (used by tests)."""
    global _default_service
    _default_service = None