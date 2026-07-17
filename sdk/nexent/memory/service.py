"""Memory service facade for the new Memory system.

This module provides a high-level facade for memory operations used by
agents and the backend.

Architecture constraints:

- The SDK layer **must not** depend on PostgreSQL, Elasticsearch or any
  other database/storage implementation.
- All persistence and vector retrieval for internal memory is delegated to
  the backend layer (see ``backend/services/vectordatabase_service.py``).
- This facade is therefore intentionally thin: it validates inputs against
  the access policy, computes idempotency keys, optionally generates
  embeddings via an injected embedding model, builds the protocol-level
  request/result models, and dispatches the actual I/O to a configurable
  backend hook (``backend_store`` / ``backend_search``).
- External memory providers (Mem0, A800, ...) still live entirely in the
  SDK and are unaffected by this constraint.

The service follows the policy defined in :pymod:`policy`:

- Agents can only write to agent short-term memory.
- Tenant/user long-term memory is managed manually or via Dreaming.
- Agent short-term memory is stored in both PG and Elasticsearch by the
  backend; the SDK never performs those writes itself.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..core.models.embedding_model import OpenAICompatibleEmbedding
from .embedding_model import EmbeddingModelInfo
from .models import (
    MemoryLayer,
    MemoryRecord,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryType,
    StoreMemoryResult,
)
from .policy import MemoryAccessPolicy, MemoryRetrievalPolicy


logger = logging.getLogger("memory_service")


# Type aliases for the backend hooks that the SDK delegates to.
BackendStoreHook = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
BackendSearchHook = Callable[[Dict[str, Any]], Awaitable[List[Dict[str, Any]]]]


class MemoryService:
    """High-level facade for memory operations.

    This service validates inputs and delegates persistence/retrieval to
    caller-supplied backend hooks. It deliberately does not import or use
    any PostgreSQL/Elasticsearch SDKs.

    A typical setup looks like:

    .. code-block:: python

        memory_service = MemoryService(
            embedding_model=embedding_model,
            embedding_model_info=embedding_model_info,
            backend_store=vectordatabase_service.persist_memory_record,
            backend_search=vectordatabase_service.search_memory_records,
        )

    The backend hooks are responsible for translating the SDK's protocol
    payloads into backend-specific calls (PG/ES CRUD, vector search,
    embedding storage, etc.). When ``backend_store`` / ``backend_search``
    are omitted the facade still produces a fully validated
    ``MemoryRecord`` and ``MemorySearchResult``, so it is safe to use in
    tests and in environments that only need the protocol layer.
    """

    def __init__(
        self,
        embedding_model: Optional[OpenAICompatibleEmbedding] = None,
        embedding_model_info: Optional[EmbeddingModelInfo] = None,
        backend_store: Optional[BackendStoreHook] = None,
        backend_search: Optional[BackendSearchHook] = None,
    ):
        """Initialize the memory service.

        Args:
            embedding_model: Optional embedding model instance used to
                generate embeddings for query/content.
            embedding_model_info: Optional embedding model info used to
                derive index naming metadata for the backend.
            backend_store: Optional async callable that persists a single
                memory record. Receives a dict payload and returns a dict
                with at least ``memory_id``.
            backend_search: Optional async callable that performs vector
                search. Receives a dict payload and returns a list of
                result dicts.
        """
        self.embedding_model = embedding_model
        self.embedding_model_info = embedding_model_info
        self.backend_store = backend_store
        self.backend_search = backend_search

    async def store_memory(
        self,
        content: str,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        conversation_id: Optional[str] = None,
        layer: MemoryLayer = MemoryLayer.AGENT,
        memory_type: MemoryType = MemoryType.SHORT_TERM,
        idempotency_key: Optional[str] = None,
        embedding: Optional[List[float]] = None,
    ) -> StoreMemoryResult:
        """Store a memory record.

        This method enforces the access policy to prevent agents from
        writing to layers they don't have permission for, then dispatches
        the actual write to the configured ``backend_store`` hook.

        Args:
            content: The memory content.
            tenant_id: Tenant identifier.
            user_id: User identifier.
            agent_id: Agent identifier.
            conversation_id: Optional conversation identifier.
            layer: Memory layer (default: agent).
            memory_type: Memory type (default: short_term).
            idempotency_key: Idempotency key for duplicate prevention.
            embedding: Optional pre-computed embedding vector.

        Returns:
            StoreMemoryResult with operation details.
        """
        if not MemoryAccessPolicy.can_agent_write(layer, memory_type):
            raise PermissionError(
                f"Agent cannot write to layer={layer}, type={memory_type}"
            )

        if idempotency_key is None:
            key_data = f"{tenant_id}:{user_id}:{agent_id}:{content}".encode()
            idempotency_key = hashlib.sha256(key_data).hexdigest()

        if embedding is None and self.embedding_model:
            try:
                embedding = self.embedding_model.get_embeddings(content)[0]
            except Exception as exc:  # noqa: BLE001 - logged and tolerated
                logger.warning("Failed to generate embedding: %s", exc)

        memory_record = MemoryRecord(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            layer=layer,
            memory_type=memory_type,
            content=content,
            idempotency_key=idempotency_key,
        )

        backend_payload = self._build_backend_store_payload(
            memory_record=memory_record,
            content=content,
            embedding=embedding,
        )

        if self.backend_store is not None:
            try:
                await self.backend_store(backend_payload)
            except Exception as exc:  # noqa: BLE001 - surfaced as warning
                logger.error("backend_store hook failed: %s", exc)
                raise

        return StoreMemoryResult(
            memory_id=memory_record.memory_id,
            event="ADD",
            content=content,
            layer=layer,
            memory_type=memory_type,
        )

    async def search_memory(
        self,
        query: str,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        conversation_id: Optional[str] = None,
        layers: Optional[List[MemoryLayer]] = None,
        top_k: int = 5,
        threshold: float = 0.65,
        embedding: Optional[List[float]] = None,
    ) -> List[MemorySearchResult]:
        """Search for memories matching the query.

        This method enforces the retrieval policy, optionally generates the
        query embedding via the injected embedding model, builds a
        ``MemorySearchRequest`` and dispatches the actual retrieval to the
        configured ``backend_search`` hook.

        Args:
            query: The search query.
            tenant_id: Tenant identifier.
            user_id: User identifier.
            agent_id: Agent identifier.
            conversation_id: Optional conversation filter.
            layers: Memory layers to search (default: all layers agent can read).
            top_k: Maximum number of results.
            threshold: Minimum similarity threshold.
            embedding: Optional pre-computed query embedding.

        Returns:
            List of search results.
        """
        if layers is None:
            layers = MemoryAccessPolicy.get_default_search_layers()

        top_k = MemoryRetrievalPolicy.validate_top_k(top_k)

        results: List[MemorySearchResult] = []

        # Full-context layers (tenant/user) are loaded by the backend
        # context service and exposed through the prompt template directly.
        # The agent short-term layer requires vector retrieval, which is
        # delegated to the backend search hook.
        if MemoryLayer.AGENT not in layers:
            return results

        if embedding is None and self.embedding_model:
            try:
                embedding = self.embedding_model.get_embeddings(query)[0]
            except Exception as exc:  # noqa: BLE001 - logged and tolerated
                logger.warning("Failed to generate query embedding: %s", exc)
                return results

        if embedding is None:
            # No embedding available; without it the backend cannot run a
            # vector search. Return an empty result list to keep the
            # contract stable.
            return results

        request = MemorySearchRequest(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            layers=[MemoryLayer.AGENT],
            query=query,
            top_k=top_k,
            threshold=threshold,
            embedding=embedding,
        )

        if self.backend_search is None:
            return results

        backend_payload = self._build_backend_search_payload(
            request=request,
            index_name=self._get_index_name(),
        )

        try:
            raw_results = await self.backend_search(backend_payload)
        except Exception as exc:  # noqa: BLE001 - logged and tolerated
            logger.error("backend_search hook failed: %s", exc)
            return []

        for item in raw_results:
            results.append(self._to_search_result(item, tenant_id=tenant_id))

        return results

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _get_index_name(self) -> Optional[str]:
        """Return the Elasticsearch index name for the configured model."""
        if not self.embedding_model_info:
            return None
        return self.embedding_model_info.get_index_name()

    @staticmethod
    def _build_backend_store_payload(
        memory_record: MemoryRecord,
        content: str,
        embedding: Optional[List[float]],
    ) -> Dict[str, Any]:
        """Translate the SDK record into a backend-friendly dict."""
        layer_value = memory_record.layer
        if hasattr(layer_value, "value"):
            layer_value = layer_value.value

        memory_type_value = memory_record.memory_type
        if hasattr(memory_type_value, "value"):
            memory_type_value = memory_type_value.value

        return {
            "memory_id": memory_record.memory_id,
            "tenant_id": memory_record.tenant_id,
            "user_id": memory_record.user_id,
            "agent_id": memory_record.agent_id,
            "conversation_id": memory_record.conversation_id,
            "layer": layer_value,
            "memory_type": memory_type_value,
            "content": content,
            "idempotency_key": memory_record.idempotency_key,
            "embedding": embedding,
        }

    @staticmethod
    def _build_backend_search_payload(
        request: MemorySearchRequest,
        index_name: Optional[str],
    ) -> Dict[str, Any]:
        """Translate the SDK search request into a backend-friendly dict."""
        payload = request.model_dump()
        payload["index_name"] = index_name
        return payload

    @staticmethod
    def _to_search_result(item: Dict[str, Any], tenant_id: str) -> MemorySearchResult:
        """Normalize a backend search hit into a ``MemorySearchResult``."""
        layer_value = item.get("layer", MemoryLayer.AGENT.value)
        try:
            layer = MemoryLayer(layer_value)
        except ValueError:
            layer = MemoryLayer.AGENT

        return MemorySearchResult(
            memory_id=item.get("memory_id", item.get("id", "")),
            content=item.get("content", ""),
            score=float(item.get("score", 0.0)),
            layer=layer,
            source=item.get("source", "internal"),
            is_external=bool(item.get("is_external", False)),
            metadata=item.get("metadata", {"tenant_id": tenant_id}),
        )


# Module-level convenience functions
_default_service: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    """Get or create the default memory service instance."""
    global _default_service
    if _default_service is None:
        _default_service = MemoryService()
    return _default_service


def reset_memory_service() -> None:
    """Reset the default memory service instance."""
    global _default_service
    _default_service = None
