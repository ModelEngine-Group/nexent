"""
ExternalKBAdapter — abstract base class + LocalKBAdapter + registry.

Architecture: each registered platform (local, dify, datamate, ...) is
implemented as an adapter class inheriting from ExternalKBAdapter ABC.
The registry maps platform strings to adapter classes so that
ExternalKnowledgeBaseService can instantiate the right one at runtime
from DB records (which carry platform + external_kb_config).

platform string → adapter class mapping is maintained by ExternalKBAdapterRegistry.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Type

logger = logging.getLogger("platform_adapters")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ExternalKBAdapterRegistry:
    """
    Maps platform string → adapter class.

    Call ``register(platform, cls)`` to add a new adapter.
    Call ``instantiate(platform, config)`` to get a live adapter instance.

    External KB providers register their adapter by calling:
        ExternalKBAdapterRegistry.register("my_platform", MyPlatformAdapter)
    """

    _registry: Dict[str, Type["ExternalKBAdapter"]] = {}

    @classmethod
    def register(cls, platform: str, adapter_cls: Type["ExternalKBAdapter"]) -> None:
        cls._registry[platform.lower()] = adapter_cls

    @classmethod
    def get(cls, platform: str) -> Optional[Type["ExternalKBAdapter"]]:
        return cls._registry.get(platform.lower())

    @classmethod
    def instantiate(cls, platform: str, config: Dict[str, Any]) -> "ExternalKBAdapter":
        """Build a live adapter instance for the given platform."""
        adapter_cls = cls.get(platform)
        if adapter_cls is None:
            raise ValueError(
                f"No adapter registered for platform '{platform}'. "
                f"Registered platforms: {list(cls._registry.keys())}"
            )
        return adapter_cls(config)

    @classmethod
    def registered_platforms(cls) -> List[str]:
        return list(cls._registry.keys())


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------

@dataclass
class AdapterCapabilities:
    create_knowledge_base: bool = False
    delete_knowledge_base: bool = False
    update_knowledge_base: bool = False
    upload_document: bool = False
    delete_document: bool = False
    list_documents: bool = False
    query_document_status: bool = False
    download_document: bool = False
    list_models: bool = False
    search_modes: List[str] = field(default_factory=list)
    supports_rerank: bool = False
    supports_multimodal: bool = False
    supports_batch_search: bool = False
    max_kb_ids_per_search: int = 10
    requires_embedding_model: bool = False
    supports_custom_embedding_model: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        d["search_modes"] = list(d["search_modes"])
        return d


@dataclass
class EmbeddingModelConfig:
    """Embedding model configuration for knowledge base adapters.
    
    Passes model metadata to adapter.create_knowledge_base() so
    external adapters can configure their own embedding models.
    """
    model_name: str = ""
    api_key: str = ""
    base_url: str = ""
    embedding_dim: int = 0
    model_type: str = "text"
    max_tokens: int = 0
    request_timeout: int = 30

    def to_dict(self) -> Dict[str, Any]:
        """V4 standard: __dict__ IS the standard format since field names are standard."""
        return self.__dict__


@dataclass
class KnowledgeBaseInfo:
    # V4 standard field name — see 外部知识库适配器标准接口设计方案.md §3.3.3.
    # Using `knowledge_base_id` (not `id`) matches what the HTTP response of
    # `GET /knowledge-bases/{knowledge_base_id}` specifies and what
    # `frontend/types/unifiedKB.ts` expects (`UnifiedKnowledgeBase.knowledge_base_id`).
    knowledge_base_id: str = ""
    name: str = ""
    description: str = ""
    embedding_model: str = ""
    document_count: int = 0
    chunk_count: int = 0
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """V4 standard: __dict__ IS the standard format since field names are standard."""
        return self.__dict__


@dataclass
class SearchRequest:
    query: str
    kb_ids: List[str] = field(default_factory=list)
    top_k: int = 5
    search_mode: str = "hybrid"
    score_threshold: float = 0.0
    rerank: bool = False
    embedding_model: str = ""
    filters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """
    Standard search result aligned to the external KB adapter spec §3.6.1.

    Only fields defined in the spec's ``records[].segment`` structure (plus
    ``score`` at the record level) are present. Platform-specific extras such
    as ``title`` / ``url`` / ``filename`` / ``score_details`` / ``metadata``
    have been removed — consumers should use the spec-defined ``document_name``
    for display, and call ``GET /documents/{id}/download-url`` lazily when a
    download URL is needed.
    """
    content: str = ""
    score: float = 0.0
    knowledge_base_id: str = ""
    knowledge_base_name: str = ""
    document_id: str = ""
    document_name: str = ""
    id: str = ""
    position: int = 0
    tokens: int = 0
    keywords: List[str] = field(default_factory=list)
    index_node_id: str = ""
    hit_count: int = 0
    enabled: bool = True
    image_url: str = ""
    table_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """V4 standard: __dict__ IS the standard format."""
        return self.__dict__


@dataclass
class SearchResponse:
    """
    Standard search response aligned to the external KB adapter spec §3.6.1.

    Outputs only ``query`` and the V4 nested ``records[].segment[]`` structure.
    ``total`` and ``query_time_ms`` have been removed — neither is part of the
    spec, and no upstream business logic consumes them.
    """
    results: List[SearchResult] = field(default_factory=list)
    query: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Output V4 standard nested records[].segment[] structure."""
        records = []
        for r in self.results:
            segment = {k: v for k, v in r.__dict__.items() if k != "score"}
            records.append({"segment": segment, "score": r.score})
        return {
            "records": records,
            "query": self.query,
        }


class ExternalKBAdapter(ABC):
    """
    Abstract base class for external KB platform adapters.

    ``config`` is the JSON stored in ``external_kb_adapter_t.external_kb_config``:
        {"url": "...", "api_key": "...", "extra": {...}}

    Lifecycle: instantiate → use → close()
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._url = config.get("url", "").rstrip("/")
        self._api_key = config.get("api_key", "")
        self._extra: Dict[str, Any] = config.get("extra", {})

    @property
    @abstractmethod
    def platform(self) -> str:
        """Platform identifier, e.g. 'local', 'dify', 'datamate'."""
        ...

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        ...

    @abstractmethod
    def get_capabilities(self) -> AdapterCapabilities:
        ...

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Convenience property — delegates to the abstract get_capabilities().

        Allows dispatcher code to write ``impl.capabilities.create_knowledge_base``
        without having to call the method each time.
        """
        return self.get_capabilities()

    @abstractmethod
    def list_knowledge_bases(
        self, keyword: Optional[str] = None, page: int = 1, page_size: int = 50
    ) -> Tuple[int, List["KnowledgeBaseInfo"]]:
        """List knowledge bases with total count for pagination.

        Returns:
            A tuple of (total_count, page_items) where total_count is the total
            number of KBs matching the query (before pagination) and page_items
            is the sliced list for the current page.
        """
        ...

    @abstractmethod
    def get_knowledge_base(self, kb_id: str) -> KnowledgeBaseInfo:
        ...

    @abstractmethod
    def search(self, request: SearchRequest) -> SearchResponse:
        ...

    def create_knowledge_base(self, name: str, description: str = "", embedding_model: str = "", metadata: Dict[str, Any] = None) -> KnowledgeBaseInfo:
        raise NotImplementedError(f"{self.platform} does not support create_knowledge_base")

    def update_knowledge_base(self, kb_id: str, name: str = "", description: str = "") -> KnowledgeBaseInfo:
        raise NotImplementedError(f"{self.platform} does not support update_knowledge_base")

    def delete_knowledge_base(self, kb_id: str) -> None:
        raise NotImplementedError(f"{self.platform} does not support delete_knowledge_base")

    def list_documents(self, kb_id: str, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        raise NotImplementedError(f"{self.platform} does not support list_documents")

    def upload_documents(self, kb_id: str, file_paths: List[str] = None, upload_files: List[Any] = None, chunking_strategy: str = "basic") -> Dict[str, Any]:
        raise NotImplementedError(f"{self.platform} does not support upload_documents")

    def delete_document(self, kb_id: str, doc_id: str) -> bool:
        raise NotImplementedError(f"{self.platform} does not support delete_document")

    def get_document_status(self, kb_id: str, doc_id: str) -> Dict[str, Any]:
        raise NotImplementedError(f"{self.platform} does not support get_document_status")

    def get_document_download_url(self, kb_id: str, doc_id: str) -> Dict[str, Any]:
        raise NotImplementedError(f"{self.platform} does not support get_document_download_url")

    def close(self) -> None:
        pass

    def __enter__(self) -> "ExternalKBAdapter":
        return self

    def __exit__(self, *args) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Status mapping helpers — legacy internal status → V4 standard
# ---------------------------------------------------------------------------

_DOC_STATUS_MAP = {
    # Legacy internal statuses
    "success": "completed",
    "done": "completed",
    "waiting": "indexing",
    "pending": "indexing",
    "processing": "indexing",
    "fail": "failed",
    "error": "failed",
    # V4 standard statuses pass through unchanged
    "indexing": "indexing",
    "completed": "completed",
    "failed": "failed",
    "paused": "paused",
}


def _resolve_index_name(kb_id: str, tenant_id: str) -> Optional[str]:
    """Resolve a KB ID (numeric knowledge_id) to its ES index_name via PG.

    Returns the index_name if found, None otherwise.
    """
    try:
        from database.knowledge_db import get_knowledge_record
        record = get_knowledge_record({
            "knowledge_id": int(kb_id),
            "tenant_id": tenant_id,
        })
        if record:
            return record.get("index_name")
    except (ValueError, Exception):
        pass
    return None


def _decode_doc_id(doc_id: str) -> Optional[str]:
    """Decode a base64-encoded document ID back to its source URI."""
    import base64
    try:
        return base64.b64decode(doc_id).decode("utf-8")
    except Exception:
        return None


def _encode_doc_id(source_uri: str) -> str:
    """Encode a source URI (file path) into a base64 document ID."""
    import base64
    return base64.b64encode(source_uri.encode("utf-8")).decode("utf-8")


def _normalize_doc_status(status: Any) -> str:
    """Map an internal document status to V4 standard (indexing/completed/failed/paused)."""
    return _DOC_STATUS_MAP.get(str(status or "").lower(), "indexing")


def _format_es_create_time(value: Any) -> str:
    """Format an ES ``create_time`` value into an ISO 8601 string.

    ES may return ``create_time`` in a number of shapes depending on what the
    indexer stored: ISO string, Unix epoch in seconds (``int``/``float``),
    Unix epoch in milliseconds (common ES timestamp format), a ``datetime``
    object (when already parsed), or ``None``. A naive ``str(value)`` on a
    Unix epoch produces a raw digit string the frontend parses as millisecond
    epoch → displays "1970". Detect numeric values and convert explicitly.

    Returns an ISO 8601 string or ``""`` when the value is absent or invalid.
    """
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        ts = float(value)
        # Heuristic: values > 1e12 are almost certainly milliseconds (year > 2001)
        # Values in seconds for years 2001-2400 are in range [1e9, 1.4e10].
        if ts > 1e12:
            ts = ts / 1000.0
        try:
            import datetime as _dt
            return _dt.datetime.fromtimestamp(ts).isoformat()
        except (ValueError, OSError, OverflowError):
            return ""
    # If it's already a string or datetime, pass through via str().
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return ""
    return str(value)


# ---------------------------------------------------------------------------
# LocalKBAdapter — nexent's own Elasticsearch-based knowledge base
# ---------------------------------------------------------------------------

# V4 standard search_mode → LocalKBAdapter canonical method name.
# V4 uses "*_search" suffixes ("hybrid_search", "semantic_search", "keyword_search").
# Local VectorDatabaseCore uses bare names ("hybrid", "semantic", "accurate" for keyword).
# Direct canonical names are also accepted for backward compatibility.
_V4_TO_CANONICAL = {
    "hybrid_search": "hybrid",
    "semantic_search": "semantic",
    "keyword_search": "accurate",
    "hybrid": "hybrid",
    "semantic": "semantic",
    "accurate": "accurate",
    "keyword": "accurate",
}


class LocalKBAdapter(ExternalKBAdapter):
    """
    In-process adapter for nexent's local Elasticsearch KB.

    Config (stored in external_kb_config):
        {
            "es_host": "...",      # optional, falls back to env
            "es_api_key": "...",  # optional
            "es_verify_certs": false,
        }

    This adapter uses VectorDatabaseCore internally to:
        - list_knowledge_bases  → get_user_indices + count_documents
        - get_knowledge_base   → check_index_exists + get_documents_detail
        - search               → hybrid_search / semantic_search / accurate_search
    """

    @property
    def platform(self) -> str:
        return "local"

    def __init__(self, config: Dict[str, Any], **kwargs):
        super().__init__(config)
        self.vdb_core = kwargs.get("vdb_core")
        self.embedding_model = kwargs.get("embedding_model")
        self._tenant_id = config.get("tenant_id", "")

    def _get_vdb_core(self):
        if self.vdb_core:
            return self.vdb_core

        es_host_from_config = self._extra.get("es_host") or self._url
        es_api_key = self._extra.get("es_api_key") or self._api_key
        verify_certs = self._extra.get("es_verify_certs", False)

        # LocalKBAdapter has an empty external_kb_config (no URL/key).
        # Fall back to the system-wide ES client built from consts.const,
        # which is already wired up and tested by the rest of the platform.
        if not es_host_from_config:
            try:
                from services.vectordatabase_service import get_vector_db_core
                self.vdb_core = get_vector_db_core()
                return self.vdb_core
            except Exception as exc:
                logger.debug("System VDB core unavailable, cannot build ES client: %s", exc)
                raise RuntimeError(
                    "LocalKBAdapter has no ES URL configured via external_kb_config, "
                    "and the system-wide VDB core could not be loaded."
                ) from exc

        from ...vector_database.elasticsearch_core import ElasticSearchCore
        self.vdb_core = ElasticSearchCore(
            host=es_host_from_config,
            api_key=es_api_key,
            verify_certs=verify_certs,
        )
        return self.vdb_core

    def _coerce_to_index_name(self, kb_id: str) -> str:
        """Resolve a ``kb_id`` to the real ES ``index_name`` used by this adapter.

        The local adapter's KB identifiers flowing over the unified API are
        numeric ``knowledge_record_t.knowledge_id`` values (e.g. ``"15"``).
        The actual Elasticsearch index is named with a UUID suffix
        (``"15-992b7c6bac0f485ca7c1c16c36efe3b5"``) and is looked up from
        the ``knowledge_record_t`` row via the module-level
        ``_resolve_index_name`` helper.

        This is a LocalKBAdapter-internal concern. Other adapter
        implementations (Dify, AIDP, ...) use their own native KB identifiers
        and do not need — and MUST NOT reuse — this mapping. Resolution is
        therefore kept strictly inside the local adapter's method bodies
        rather than in the shared service layer.

        When resolution fails (PG unavailable, kb_id not numeric, or tenant
        mismatch), logs at ERROR level so the data bug is visible but still
        returns ``kb_id`` itself — the downstream ES call will fail with a
        clear "no such index" error, which is more useful than silently
        returning the wrong data.
        """
        index_name = _resolve_index_name(str(kb_id), self._tenant_id)
        if index_name:
            return index_name
        logger.error(
            "LocalKBAdapter: cannot resolve kb_id=%r to ES index_name for "
            "tenant=%r; using raw kb_id (downstream ES call will likely "
            "fail with 'no such index')",
            kb_id, self._tenant_id,
        )
        return str(kb_id)

    def health_check(self) -> Dict[str, Any]:
        try:
            core = self._get_vdb_core()
            core.client.cluster.health()
            return {"status": "ok", "platform": self.platform, "version": "1.0.0", "external_kb_reachable": True}
        except Exception as e:
            return {"status": "error", "platform": self.platform, "version": "1.0.0", "external_kb_reachable": False, "message": str(e)}

    def get_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            create_knowledge_base=True,
            delete_knowledge_base=True,
            update_knowledge_base=True,
            upload_document=True,
            delete_document=True,
            list_documents=True,
            query_document_status=True,
            download_document=True,
            list_models=False,
            search_modes=["hybrid", "semantic", "accurate"],
            supports_rerank=True,
            supports_multimodal=True,
            supports_batch_search=False,
            max_kb_ids_per_search=100,
            requires_embedding_model=False,  # LocalKBAdapter resolves embeddings internally
            supports_custom_embedding_model=False,
        )

    def list_knowledge_bases(
        self, keyword: Optional[str] = None, page: int = 1, page_size: int = 50
    ) -> List[KnowledgeBaseInfo]:
        # Prefer PG-backed list when available (includes human-readable names)
        try:
            from database.knowledge_db import get_knowledge_info_by_tenant_id
            rows = get_knowledge_info_by_tenant_id(self._tenant_id)
            results: List[KnowledgeBaseInfo] = []

            # Build a cache of ES-derived counts keyed by index_name.
            # knowledge_record_t has no document_count/chunk_count columns, so
            # we compute them per-KB by aggregating ES chunks via
            # get_documents_detail. This also surfaces legacy (pre-V4) data
            # that lives only in ES and is not backfilled into
            # kb_document_record_t.
            es_stats_cache: Dict[str, Dict[str, int]] = {}
            try:
                core = self._get_vdb_core()
            except Exception as exc:
                logger.debug("Cannot build ES core for KB list stats: %s", exc)
                core = None

            def _es_stats(row: Dict[str, Any]) -> Dict[str, int]:
                if core is None:
                    return {"document_count": 0, "chunk_count": 0}
                index_name = row.get("index_name") or ""
                if not index_name:
                    return {"document_count": 0, "chunk_count": 0}
                if index_name in es_stats_cache:
                    return es_stats_cache[index_name]
                try:
                    files = core.get_documents_detail(index_name)
                    doc_count = len(files)
                    chunk_count = sum(f.get("chunk_count", 0) or 0 for f in files)
                except Exception as exc:
                    logger.debug(
                        "ES stats unavailable for index %s: %s", index_name, exc
                    )
                    doc_count = chunk_count = 0
                stats = {"document_count": doc_count, "chunk_count": chunk_count}
                es_stats_cache[index_name] = stats
                return stats

            for row in rows:
                name = row.get("knowledge_name") or row.get("knowledge_id", "")
                kb_name = str(name).lower()
                kw = (keyword or "").lower()
                if kw and kw not in kb_name:
                    continue

                # Use ES-derived counts as the authoritative source. Fall back
                # to any PG-provided value only if ES returned 0 (e.g. the
                # index was just created and ES hasn't populated yet).
                es_counts = _es_stats(row)
                document_count = (
                    es_counts["document_count"]
                    or row.get("document_count", 0)
                    or 0
                )
                chunk_count = (
                    es_counts["chunk_count"]
                    or row.get("chunk_count", 0)
                    or 0
                )

                results.append(KnowledgeBaseInfo(
                    knowledge_base_id=str(row.get("knowledge_id")),
                    name=str(name),
                    description=row.get("knowledge_describe", ""),
                    document_count=document_count,
                    chunk_count=chunk_count,
                    embedding_model=row.get("embedding_model_name", ""),
                    status="active",
                    created_at=_format_es_create_time(row.get("create_time")),
                    updated_at=_format_es_create_time(row.get("update_time")),
                    metadata={
                        "index_name": row.get("index_name", ""),
                    },
                ))
            total = len(results)
            start = (page - 1) * page_size
            return (total, results[start:start + page_size])
        except Exception:
            logger.debug("PG unavailable; falling back to ES list_knowledge_bases")

        # ES-only fallback (no PG)
        core = self._get_vdb_core()
        index_names = core.get_user_indices()
        results: List[KnowledgeBaseInfo] = []

        for idx_name in index_names:
            if keyword and keyword.lower() not in idx_name.lower():
                continue
            doc_count = core.count_documents(idx_name)
            try:
                detail = core.get_documents_detail(idx_name)
                file_count = len(detail) if detail else 0
            except Exception:
                file_count = 0

            results.append(KnowledgeBaseInfo(
                knowledge_base_id=idx_name,
                name=idx_name,
                description="",
                document_count=file_count,
                chunk_count=doc_count,
                embedding_model="",
                status="active",
                created_at="",
                updated_at="",
                metadata={"index_name": idx_name},
            ))

        total = len(results)
        start = (page - 1) * page_size
        return (total, results[start:start + page_size])

    def get_knowledge_base(self, kb_id: str) -> KnowledgeBaseInfo:
        # Try PG-first (human-readable name)
        try:
            from database.knowledge_db import get_knowledge_record
            kb_record = get_knowledge_record({
                "knowledge_id": int(kb_id),
                "tenant_id": self._tenant_id,
            })
            if kb_record:
                return KnowledgeBaseInfo(
                    knowledge_base_id=kb_id,
                    name=kb_record.get("knowledge_name", ""),
                    description=kb_record.get("knowledge_describe", ""),
                    document_count=kb_record.get("document_count", 0) or 0,
                    chunk_count=kb_record.get("chunk_count", 0) or 0,
                    embedding_model=kb_record.get("embedding_model_name", ""),
                    status="active",
                    created_at=_format_es_create_time(kb_record.get("create_time")),
                    updated_at=_format_es_create_time(kb_record.get("update_time")),
                    metadata={
                        "index_name": kb_record.get("index_name", ""),
                        "is_multimodal": bool(kb_record.get("is_multimodal", False)),
                    },
                )
        except Exception:
            logger.debug("PG lookup failed for kb_id=%s; using ES fallback", kb_id)

        # ES fallback: resolve numeric kb_id to the real ES index_name.
        # The unified API receives ``kb_id`` as a numeric ``knowledge_id``
        # string (e.g. "15"); ES indices are ``"{knowledge_id}-{uuid}"``.
        # Without this resolution the ES lookup would always return False.
        core = self._get_vdb_core()
        index_name = self._coerce_to_index_name(kb_id)
        exists = core.check_index_exists(index_name)
        if not exists:
            raise ValueError(f"Index '{index_name}' does not exist (kb_id={kb_id!r})")
        doc_count = core.count_documents(index_name)
        try:
            detail = core.get_documents_detail(index_name)
            file_count = len(detail) if detail else 0
        except Exception:
            file_count = 0
        return KnowledgeBaseInfo(
            knowledge_base_id=kb_id,
            name=index_name,
            description="",
            document_count=file_count,
            chunk_count=doc_count,
            status="active",
            created_at="",
            updated_at="",
            metadata={"index_name": index_name},
        )

    def search(self, request: SearchRequest) -> SearchResponse:
        core = self._get_vdb_core()

        # Map V4 standard search_mode → local VectorDatabaseCore canonical method.
        # V4 standard: "hybrid_search" / "semantic_search" / "keyword_search"
        # Local canonical: "hybrid" / "semantic" / "accurate"
        mode = _V4_TO_CANONICAL.get(request.search_mode, request.search_mode or "hybrid")
        # The unified API receives numeric ``knowledge_id`` values (e.g. "15").
        # ES indices are named with the UUID suffix (e.g. "15-992b7c6bac...").
        # Resolve each ``kb_id`` to its real ``index_name`` before handing the
        # list to the vector store. When the caller omits ``kb_ids`` we fall
        # back to every index owned by the current tenant.
        if request.kb_ids:
            index_names = [self._coerce_to_index_name(kb_id) for kb_id in request.kb_ids]
        else:
            index_names = core.get_user_indices()
        if not index_names:
            return SearchResponse(results=[], query=request.query)

        effective_top_k = request.top_k * 2 if request.rerank else request.top_k

        # Resolve embedding model internally if not provided
        embedding_model = self.embedding_model
        if embedding_model is None and mode in ("hybrid", "semantic"):
            # Try to resolve from the first index_name
            index_name = index_names[0]
            try:
                # Import here to avoid circular dependency (SDK should not import backend)
                # Use late import pattern
                from services.vectordatabase_service import get_embedding_model_by_index_name
                embedding_model, model_id, metadata = get_embedding_model_by_index_name(
                    tenant_id=self._tenant_id,
                    index_name=index_name,
                )
                if embedding_model is None:
                    logger.warning(
                        "Failed to resolve embedding model for index '%s': %s",
                        index_name, metadata.get("message", "unknown error")
                    )
            except ImportError as e:
                logger.error("Cannot import get_embedding_model_by_index_name: %s", e)
            except Exception as e:
                logger.warning("Error resolving embedding model for index '%s': %s", index_name, e)

        try:
            if mode == "hybrid":
                raw = core.hybrid_search(
                    index_names=index_names,
                    query_text=request.query,
                    embedding_model=embedding_model,
                    top_k=effective_top_k,
                )
            elif mode == "semantic":
                raw = core.semantic_search(
                    index_names=index_names,
                    query_text=request.query,
                    embedding_model=embedding_model,
                    top_k=effective_top_k,
                )
            elif mode == "accurate":
                raw = core.accurate_search(
                    index_names=index_names,
                    query_text=request.query,
                    top_k=effective_top_k,
                )
            else:
                raw = core.hybrid_search(
                    index_names=index_names,
                    query_text=request.query,
                    embedding_model=embedding_model,
                    top_k=effective_top_k,
                )
        except Exception as e:
            logger.warning("LocalKBAdapter search failed: %s", e)
            raw = []

        results: List[SearchResult] = []
        for item in raw:
            doc = item.get("document", {})
            index_name = item.get("index", "")
            results.append(SearchResult(
                content=doc.get("content", ""),
                score=float(item.get("score", 0.0)),
                knowledge_base_id=index_name,
                knowledge_base_name=index_name,
                document_id=doc.get("id", ""),
                document_name=doc.get("filename", ""),
                id=doc.get("id", ""),
                tokens=0,
            ))

        return SearchResponse(
            results=results[:request.top_k],
            query=request.query,
        )

    def create_knowledge_base(self, name: str, description: str = "", embedding_model: str = "", metadata: Dict[str, Any] = None) -> KnowledgeBaseInfo:
        """
        Create a new knowledge base via the full backend pipeline.

        This bridges to ElasticSearchService.create_knowledge_base which:
          1. Resolves an embedding model (tenant default or user-specified)
          2. Creates a PG ``knowledge_record_t`` row (yields knowledge_id)
          3. Creates the ES index with generated index_name

        Args:
            name: Human-readable knowledge base name.
            description: Optional description text.
            embedding_model: Optional embedding model name override.
            metadata: Optional extra config; ``is_multimodal`` is read from here.
        """
        from services.vectordatabase_service import ElasticSearchService, get_vector_db_core
        vdb_core = get_vector_db_core()
        is_multimodal = bool((metadata or {}).get("is_multimodal", False))

        result = ElasticSearchService.create_knowledge_base(
            knowledge_name=name,
            embedding_dim=None,
            vdb_core=vdb_core,
            user_id=self.config.get("user_id", ""),
            tenant_id=self._tenant_id,
            embedding_model_name=embedding_model or None,
            is_multimodal=is_multimodal if is_multimodal else None,
        )

        if not result or result.get("status") != "success":
            err = (result or {}).get("message", "unknown error")
            raise RuntimeError(f"Failed to create KB '{name}': {err}")

        # Optionally update description (matches knowledge_standard_app flow)
        index_name = result.get("id")
        if description and index_name:
            try:
                from services.vectordatabase_service import ElasticSearchService
                ElasticSearchService.update_knowledge_base(
                    index_name=index_name,
                    knowledge_name=name,
                    tenant_id=self._tenant_id,
                    user_id=self.config.get("user_id", ""),
                )
            except Exception as exc:
                logger.warning("Description update skipped for KB %s: %s", name, exc)

        kb_id = str(result.get("knowledge_id") or "")
        resolved_embedding_model = result.get("embedding_model_name", "") or embedding_model
        create_time_val = result.get("create_time") or result.get("update_time")
        return KnowledgeBaseInfo(
            knowledge_base_id=kb_id,
            name=name,
            description=description,
            embedding_model=resolved_embedding_model,
            status="active",
            created_at=_format_es_create_time(create_time_val),
            updated_at=_format_es_create_time(create_time_val),
            metadata={"index_name": index_name},
        )

    def update_knowledge_base(self, kb_id: str, name: str = "", description: str = "") -> KnowledgeBaseInfo:
        """Update knowledge base metadata (name, description, permissions)."""
        from services.vectordatabase_service import ElasticSearchService

        index_name = self._coerce_to_index_name(kb_id)

        if name:
            ElasticSearchService.update_knowledge_base(
                index_name=index_name,
                knowledge_name=name,
                tenant_id=self._tenant_id,
                user_id=self.config.get("user_id", ""),
            )

        if description:
            try:
                # Persist description through the PG knowledge_record_t path
                # update_knowledge_base on ES only handles name; description is
                # best-effort at the app layer (see _safe_update_description).
                from database.knowledge_db import update_knowledge_record
                update_knowledge_record({
                    "index_name": index_name,
                    "knowledge_name": name or kb_id,
                    "knowledge_describe": description,
                })
            except Exception as exc:
                logger.warning("Description update skipped for KB %s: %s", kb_id, exc)

        return self.get_knowledge_base(kb_id)

    def delete_knowledge_base(self, kb_id: str) -> None:
        """
        Delete a knowledge base via the full cleanup pipeline.

        Bridges to ElasticSearchService.full_delete_knowledge_base which removes:
          1. All MinIO objects referenced by the index
          2. The ES index itself
          3. PG ``knowledge_record_t`` + ``kb_document_record_t`` rows

        When ``kb_id`` is numeric, resolves ``index_name`` from PG first.
        When it is a raw index name, calls the pipeline directly.
        """
        import asyncio
        from services.vectordatabase_service import ElasticSearchService, get_vector_db_core

        index_name = self._coerce_to_index_name(kb_id)
        vdb_core = get_vector_db_core()
        user_id = self.config.get("user_id", "")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule on a new thread to avoid nested-loop deadlock
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        ElasticSearchService.full_delete_knowledge_base(
                            index_name=index_name,
                            vdb_core=vdb_core,
                            user_id=user_id,
                        ),
                    )
                    future.result()
            else:
                loop.run_until_complete(
                    ElasticSearchService.full_delete_knowledge_base(
                        index_name=index_name,
                        vdb_core=vdb_core,
                        user_id=user_id,
                    )
                )
        except RuntimeError:
            # No loop available at all - run in a fresh one
            asyncio.run(
                ElasticSearchService.full_delete_knowledge_base(
                    index_name=index_name,
                    vdb_core=vdb_core,
                    user_id=user_id,
                )
            )

    def get_document_download_url(self, kb_id: str, doc_id: str) -> Dict[str, Any]:
        """Generate a presigned MinIO download URL for a document."""
        import asyncio
        from services.file_management_service import get_file_url_impl

        # Resolve source_uri from doc_id
        source_uri: Optional[str] = None
        filename = ""
        try:
            from database import document_db
            pg_doc = document_db.get_document_record_by_uuid(doc_id)
            if pg_doc:
                source_uri = pg_doc["source_uri"]
                filename = pg_doc.get("filename", "")
        except Exception:
            pass

        if not source_uri:
            source_uri = _decode_doc_id(doc_id)

        if not source_uri:
            raise ValueError(f"Cannot resolve document source for id '{doc_id}'")

        expires = 300  # seconds
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        get_file_url_impl(object_name=source_uri, expires=expires),
                    )
                    url_info = future.result()
            else:
                url_info = loop.run_until_complete(
                    get_file_url_impl(object_name=source_uri, expires=expires)
                )
        except RuntimeError:
            url_info = asyncio.run(
                get_file_url_impl(object_name=source_uri, expires=expires)
            )

        import datetime
        expires_at = (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(seconds=expires)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "download_url": url_info.get("url") or url_info.get("file_url"),
            "expires_at": expires_at,
            "expires_in": expires,
            "filename": filename or source_uri.split("/")[-1],
        }

    def list_documents(self, kb_id: str, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """List documents using PG as source-of-truth, falling back to ES list_files.

        Two sources of truth may contain document info:
          * PG: ``kb_document_record_t`` — authoritative for new (post-V4) uploads.
          * ES: chunk-level aggregation via ``get_documents_detail`` — legacy data lives
            here for KBs uploaded before ``kb_document_record_t`` was introduced.

        Strategy: use PG when it returns any rows. When PG returns 0 rows (the table is
        empty for pre-V4 data), fall through to ES using the resolved ``index_name``.
        """
        # PG-primary path
        try:
            from database import document_db

            pg_result = document_db.list_document_records(
                knowledge_id=int(kb_id),
                page=page,
                page_size=page_size,
            )
            records = pg_result.get("records", [])
            total = pg_result.get("total", 0)

            if total > 0:
                items = []
                for doc in records:
                    filename = doc.get("filename", "")
                    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
                    create_time = doc.get("create_time")
                    created_at_str = create_time.isoformat() if create_time else ""
                    items.append({
                        "id": doc.get("document_uuid", ""),
                        "name": filename,
                        "status": _normalize_doc_status(doc.get("status", "waiting")),
                        "chunk_count": doc.get("chunk_count", 0) or 0,
                        "size": doc.get("file_size", 0) or 0,
                        "created_at": created_at_str,
                        "updated_at": "",
                        "knowledge_base_id": kb_id,
                        "type": ext,
                        "token_count": 0,
                        "error_message": doc.get("error_message"),
                    })
                return {
                    "list": items,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "has_more": (page * page_size) < total,
                }
        except Exception as exc:
            logger.debug("PG list_documents failed for kb %s: %s; falling back to ES", kb_id, exc)

        # PG returned 0 rows (unbackfilled table for pre-V4 data) or raised —
        # fall through to ES. Resolve numeric kb_id to the real index_name
        # (e.g. "4" -> "4-6b47...") because ES indices are named by index_name.
        index_name = self._coerce_to_index_name(kb_id)

        core = self._get_vdb_core()
        try:
            file_records = core.get_documents_detail(index_name)
        except Exception as exc:
            logger.warning("ES get_documents_detail failed for %s: %s", index_name, exc)
            # Index may not exist (empty KB) — return empty, not error.
            return {
                "list": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "has_more": False,
            }

        start = (page - 1) * page_size
        end = start + page_size
        paged = file_records[start:end]

        items = []
        for file_rec in paged:
            path_or_url = file_rec.get("path_or_url", "")
            filename = file_rec.get("filename", "") or (
                path_or_url.rsplit("/", 1)[-1] if path_or_url else ""
            )
            ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
            created_at_str = _format_es_create_time(file_rec.get("create_time"))
            items.append({
                "id": _encode_doc_id(path_or_url),
                "name": filename,
                "status": "completed",  # ES only has chunks for indexed docs
                "chunk_count": file_rec.get("chunk_count", 0) or 0,
                "size": file_rec.get("file_size", 0) or 0,
                "created_at": created_at_str,
                "updated_at": "",
                "knowledge_base_id": kb_id,
                "type": ext,
                "token_count": 0,
                "error_message": None,
            })

        total = len(file_records)
        return {
            "list": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": end < total,
        }

    def delete_document(self, kb_id: str, doc_id: str) -> bool:
        """Delete a document: ES chunks + PG soft-delete."""
        import asyncio
        from services.vectordatabase_service import ElasticSearchService, get_vector_db_core

        # Resolve internal index_name from kb_id
        index_name = self._coerce_to_index_name(kb_id)

        # Resolve source_uri from doc_id
        source_uri: Optional[str] = None
        try:
            from database import document_db
            pg_doc = document_db.get_document_record_by_uuid(doc_id)
            if pg_doc:
                source_uri = pg_doc["source_uri"]
        except Exception:
            pass

        if not source_uri:
            source_uri = _decode_doc_id(doc_id)

        if not source_uri:
            logger.warning("Cannot resolve source_uri for doc_id=%s; skipping ES delete", doc_id)
            return False

        # Delete from ES
        vdb_core = get_vector_db_core()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        ElasticSearchService.delete_document_by_scope(
                            index_name=index_name,
                            path_or_url=source_uri,
                            scope="full",
                            vdb_core=vdb_core,
                        ),
                    )
                    es_result = future.result()
            else:
                es_result = loop.run_until_complete(
                    ElasticSearchService.delete_document_by_scope(
                        index_name=index_name,
                        path_or_url=source_uri,
                        scope="full",
                        vdb_core=vdb_core,
                    )
                )
        except RuntimeError:
            es_result = asyncio.run(
                ElasticSearchService.delete_document_by_scope(
                    index_name=index_name,
                    path_or_url=source_uri,
                    scope="full",
                    vdb_core=vdb_core,
                )
            )

        # Soft-delete PG row (best-effort)
        try:
            from database import document_db
            document_db.soft_delete_document_record(int(kb_id), source_uri, self.config.get("user_id", ""))
        except Exception as exc:
            logger.warning("document_db soft-delete skipped for %s: %s", doc_id, exc)

        return (es_result.get("deleted_es_count", 0) if isinstance(es_result, dict) else 0) > 0

    def get_document_status(self, kb_id: str, doc_id: str) -> Dict[str, Any]:
        """Query document indexing status: PG primary, ES fallback."""
        # PG primary
        try:
            from database import document_db
            pg_doc = document_db.get_document_record_by_uuid(doc_id)
            if pg_doc:
                filename = pg_doc.get("filename", "")
                ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
                create_time = pg_doc.get("create_time")
                created_at_str = create_time.isoformat() if create_time else ""
                chunk_count = pg_doc.get("chunk_count", 0) or 0
                file_size = pg_doc.get("file_size", 0) or 0
                status = pg_doc.get("status", "indexing")
                progress = 100 if status == "completed" else (0 if status == "waiting" else 50)
                progress_msg_map = {
                    "completed": "Completed",
                    "indexing": "Indexing in progress...",
                    "failed": "Failed",
                    "paused": "Paused",
                    "waiting": "Waiting...",
                }
                return {
                    "id": doc_id,
                    "name": filename,
                    "status": status,
                    "knowledge_base_id": kb_id,
                    "size": file_size,
                    "type": ext,
                    "chunk_count": chunk_count,
                    "token_count": 0,
                    "progress": progress,
                    "progress_msg": progress_msg_map.get(status, "Unknown"),
                    "created_at": created_at_str,
                    "updated_at": "",
                    "error": pg_doc.get("error_message") if status == "failed" else None,
                }
        except Exception:
            pass

        # ES fallback: decode doc_id → match against list_files
        source_uri = _decode_doc_id(doc_id)
        if source_uri:
            try:
                index_name = self._coerce_to_index_name(kb_id)
                import asyncio
                from services.vectordatabase_service import ElasticSearchService, get_vector_db_core
                vdb_core = get_vector_db_core()

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                            future = pool.submit(
                                asyncio.run,
                                ElasticSearchService.list_files(
                                    index_name=index_name, include_chunks=False, vdb_core=vdb_core
                                ),
                            )
                            files_result = future.result()
                    else:
                        files_result = loop.run_until_complete(
                            ElasticSearchService.list_files(
                                index_name=index_name, include_chunks=False, vdb_core=vdb_core
                            )
                        )
                except RuntimeError:
                    files_result = asyncio.run(
                        ElasticSearchService.list_files(
                            index_name=index_name, include_chunks=False, vdb_core=vdb_core
                        )
                    )

                for f in files_result.get("files", []) or []:
                    if f.get("path_or_url") == source_uri:
                        filename = f.get("file", "")
                        ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
                        status = _normalize_doc_status(f.get("status", "waiting"))
                        chunk_count = f.get("chunk_count", 0) or 0
                        progress = 100 if status == "completed" else (0 if status == "waiting" else 50)
                        progress_msg_map = {
                            "completed": "Completed",
                            "indexing": "Indexing in progress...",
                            "failed": "Failed",
                            "paused": "Paused",
                            "waiting": "Waiting...",
                        }
                        return {
                            "id": doc_id,
                            "name": filename,
                            "status": status,
                            "knowledge_base_id": kb_id,
                            "size": f.get("file_size", 0) or 0,
                            "type": ext,
                            "chunk_count": chunk_count,
                            "token_count": 0,
                            "progress": progress,
                            "progress_msg": progress_msg_map.get(status, "Unknown"),
                            "created_at": "",
                            "updated_at": "",
                            "error": f.get("error_reason") if status == "failed" else None,
                        }
            except Exception as exc:
                logger.debug("ES fallback failed for doc status %s: %s", doc_id, exc)

        raise ValueError(f"Document not found: {doc_id}")

    def upload_documents(
        self,
        kb_id: str,
        file_paths: List[str] = None,
        upload_files: List[Any] = None,
        chunking_strategy: str = "basic",
    ) -> Dict[str, Any]:
        """
        Upload one or more files and trigger indexing.

        Bridges to full backend pipeline:
          1. ``upload_files_impl`` writes files to MinIO
          2. ``trigger_data_process`` enqueues indexing jobs
          3. PG ``kb_document_record_t`` rows are created (status=indexing)

        Args:
            kb_id: Knowledge base ID.
            file_paths: List of file paths (legacy path, for backward compat).
            upload_files: List of UploadFile objects (standard multipart path).
            chunking_strategy: Chunking strategy name passed through to the
                backend data-process pipeline — used as-is, not hardcoded.

        Returns:
            Dict with keys: documents (list), errors (list), process_tasks.
        """
        import asyncio
        from services.file_management_service import upload_files_impl
        from utils.file_management_utils import trigger_data_process
        from consts.model import ProcessParams
        from utils.auth_utils import generate_session_jwt

        # Resolve internal index_name
        index_name = self._coerce_to_index_name(kb_id)

        # Accept either UploadFile objects or raw files list
        files = upload_files or file_paths or []
        if not files:
            return {"documents": [], "errors": ["No files provided"]}

        user_id = self.config.get("user_id", "")

        # Upload to MinIO
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        upload_files_impl(
                            destination="minio",
                            file=files,
                            folder=None,
                            index_name=index_name,
                            user_id=user_id,
                            uploader_tenant_id=self._tenant_id,
                        ),
                    )
                    errors, uploaded_paths, uploaded_names = future.result()
            else:
                errors, uploaded_paths, uploaded_names = loop.run_until_complete(
                    upload_files_impl(
                        destination="minio",
                        file=files,
                        folder=None,
                        index_name=index_name,
                        user_id=user_id,
                        uploader_tenant_id=self._tenant_id,
                    )
                )
        except RuntimeError:
            errors, uploaded_paths, uploaded_names = asyncio.run(
                upload_files_impl(
                    destination="minio",
                    file=files,
                    folder=None,
                    index_name=index_name,
                    user_id=user_id,
                    uploader_tenant_id=self._tenant_id,
                )
            )

        if not uploaded_paths:
            return {"documents": [], "errors": errors or ["No files uploaded"]}

        # Trigger data-process pipeline
        internal_jwt = generate_session_jwt(user_id)
        process_params = ProcessParams(
            chunking_strategy=chunking_strategy,
            source_type="minio",
            index_name=index_name,
            authorization=internal_jwt,
        )
        try:
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        trigger_data_process(
                            files=[
                                {"path_or_url": p, "filename": n}
                                for p, n in zip(uploaded_paths, uploaded_names)
                            ],
                            process_params=process_params,
                        ),
                    )
                    process_result = future.result()
            else:
                process_result = loop.run_until_complete(
                    trigger_data_process(
                        files=[
                            {"path_or_url": p, "filename": n}
                            for p, n in zip(uploaded_paths, uploaded_names)
                        ],
                        process_params=process_params,
                    )
                )
        except Exception as exc:
            process_result = {"error": str(exc)}

        # Write PG document rows (best-effort)
        documents = []
        try:
            from database import document_db
            for path, name in zip(uploaded_paths, uploaded_names):
                doc_row = document_db.create_document_record(
                    knowledge_id=int(kb_id),
                    tenant_id=self._tenant_id,
                    source_uri=path,
                    filename=name,
                    file_size=0,
                    user_id=user_id,
                )
                documents.append({
                    "id": doc_row["document_uuid"],
                    "name": name,
                    "source_uri": path,
                })
        except Exception as exc:
            logger.warning("document_db write skipped for kb %s: %s", kb_id, exc)
            documents = [
                {"id": _encode_doc_id(p), "name": n}
                for p, n in zip(uploaded_paths, uploaded_names)
            ]

        return {
            "document_ids": [d["id"] for d in documents],
            "failed_files": [
                {"name": name, "error": err}
                for name, err in (zip(uploaded_names, errors) if errors else [])
            ],
        }


# Register the local adapter
ExternalKBAdapterRegistry.register("local", LocalKBAdapter)
