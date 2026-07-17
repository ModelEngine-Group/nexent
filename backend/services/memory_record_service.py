"""Business logic for internal memory records (Phase 2).

Layer rules:

- ``tenant`` and ``user`` long-term memories are written to PostgreSQL only.
- ``agent`` short-term memory is written to PostgreSQL first, then mirrored
  into Elasticsearch by :pymod:`services.memory_index_service`. If the
  Elasticsearch side fails, the PG row is kept and the failure is logged so
  that a future backfill job can retry.

Idempotency: every write is keyed by ``(tenant_id, idempotency_key)`` so
replays do not create duplicates. The same key for a different tenant is a
distinct memory.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from database import memory_record_db
from nexent.memory.embedding_model import (
    EmbeddingModelInfo,
    get_embedding_client,
)
from nexent.memory.models import MemoryLayer, MemoryType
from nexent.memory.policy import MemoryAccessPolicy, MemoryStoragePolicy

from .memory_index_service import MemoryIndexService, get_memory_index_service


logger = logging.getLogger("memory_record_service")
logger.setLevel(logging.DEBUG)


def _generate_idempotency_key() -> str:
    """Return a fresh idempotency key (uuid4 string)."""
    import uuid

    return str(uuid.uuid4())


class MemoryRecordError(Exception):
    """Raised when an internal memory operation cannot be completed."""


# ---------------------------------------------------------------------------
# Public helpers (used by app and other services)
# ---------------------------------------------------------------------------


def _validate_layer_name(layer: Optional[str]) -> str:
    """Validate that ``layer`` is one of the supported memory layers.

    Raises ``MemoryRecordError`` if the value is ``None`` or not in the
    allowed set. Returns the normalised (lowercase, stripped) layer string.
    """
    if layer is None:
        raise MemoryRecordError("Layer cannot be None")
    normalised = layer.strip().lower()
    if normalised not in {"tenant", "user", "agent"}:
        raise MemoryRecordError(f"Unsupported layer: {layer}")
    return normalised


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _resolve_memory_type(layer: str, memory_type: Optional[str]) -> str:
    """Return the canonical memory_type string for a layer.

    Tenant and user layers default to ``long_term``; agent defaults to
    ``short_term``. The caller can override either explicitly.
    """
    if memory_type:
        return memory_type
    if layer == MemoryLayer.AGENT.value:
        return MemoryType.SHORT_TERM.value
    return MemoryType.LONG_TERM.value


def _ensure_index_name(
    record: Dict[str, Any],
    embedding_model_info: Optional[EmbeddingModelInfo],
) -> Optional[str]:
    """Resolve and stamp the ES index name for an agent short-term record."""
    if record.get("layer") != MemoryLayer.AGENT.value:
        record.pop("es_index_name", None)
        return None
    index_name = record.get("es_index_name")
    if not index_name and embedding_model_info is not None:
        index_name = embedding_model_info.get_index_name()
    if index_name:
        record["es_index_name"] = index_name
    return index_name


def _resolve_tenant_embedding_model_info(
    tenant_id: str,
) -> Optional[EmbeddingModelInfo]:
    """Return the first available tenant embedding model, or ``None``."""
    logger.debug("[EMBEDDING_MODEL_LOOKUP] tenant_id=%s", tenant_id)
    
    try:
        from database import model_management_db
    except ImportError:  # pragma: no cover - defensive
        logger.warning("[EMBEDDING_MODEL_LOOKUP] model_management_db import failed")
        return None

    try:
        records = model_management_db.get_model_records(
            {"model_type": "embedding"}, tenant_id
        )
        logger.debug("[EMBEDDING_MODEL_LOOKUP] found %d model records", len(records))
        for rec in records:
            logger.debug("[EMBEDDING_MODEL_LOOKUP] record: model_name=%s connect_status=%s base_url=%s dimension=%s",
                        rec.get("model_name"), rec.get("connect_status"), 
                        rec.get("base_url"), rec.get("max_tokens"))
    except Exception:
        logger.exception(
            "Failed to load tenant embedding model for tenant=%s", tenant_id
        )
        return None

    for record in records:
        if record.get("connect_status", "").lower() == "available":
            model_name = record.get("model_name")
            model_repo = record.get("model_repo")
            base_url = record.get("base_url")
            api_key = record.get("api_key")
            dimension = record.get("max_tokens")
            logger.debug("[EMBEDDING_MODEL_LOOKUP] checking available model: model_name=%s model_repo=%s base_url=%s dimension=%s",
                        model_name, model_repo, base_url, dimension)
            if not all([model_name, base_url, api_key, dimension]):
                logger.warning("[EMBEDDING_MODEL_LOOKUP] skipping model due to missing fields: name=%s base_url=%s api_key=%s dimension=%s",
                              model_name, base_url, "***" if api_key else None, dimension)
                continue
            result = EmbeddingModelInfo(
                model_name=model_name,
                model_repo=model_repo,
                dimension=int(dimension),
                base_url=base_url,
                api_key=api_key,
                ssl_verify=bool(record.get("ssl_verify", True)),
            )
            logger.debug("[EMBEDDING_MODEL_LOOKUP] resolved to: %s", result)
            return result

    logger.warning("[EMBEDDING_MODEL_LOOKUP] no available embedding model found for tenant=%s", tenant_id)
    return None


def _compute_content_embedding(
    content: str,
    embedding_model_info: EmbeddingModelInfo,
) -> Optional[List[float]]:
    """Compute an embedding for ``content`` using the resolved model."""
    try:
        instance = get_embedding_client(
            model_name=embedding_model_info.model_name,
            dimension=embedding_model_info.dimension,
            base_url=embedding_model_info.base_url,
            api_key=embedding_model_info.api_key,
            model_repo=embedding_model_info.model_repo,
            ssl_verify=embedding_model_info.ssl_verify,
        )
        embeddings = instance.get_embeddings(
            content, timeout=30, retries=2, retry_timeout_step=5.0
        )
        if not embeddings:
            return None
        vector = embeddings[0]
        if not isinstance(vector, list):
            return None
        return [float(value) for value in vector]
    except Exception:
        logger.exception(
            "Failed to compute embedding for memory content using model=%s",
            embedding_model_info.model_name,
        )
        return None


def _validate_layer_policy(layer: str, memory_type: str, actor: str) -> None:
    """Apply the access policy based on who is performing the write."""
    layer_enum = MemoryLayer(layer)
    type_enum = MemoryType(memory_type)

    if actor == "agent":
        if not MemoryAccessPolicy.can_agent_write(layer_enum, type_enum):
            raise MemoryRecordError(
                f"Agent cannot write to layer={layer}, type={memory_type}"
            )
    elif actor == "dreaming":
        if not MemoryAccessPolicy.can_dreaming_write(layer_enum, type_enum):
            raise MemoryRecordError(
                f"Dreaming cannot write to layer={layer}, type={memory_type}"
            )
    elif actor in {"system", "user", "admin"}:
        # System / manual management may write to any layer.
        return
    else:
        raise MemoryRecordError(f"Unknown memory actor: {actor}")


class MemoryRecordService:
    """High-level operations for ``memory_records_t``.

    The service is intentionally stateless apart from the injected index
    service. Constructing multiple instances is safe and encouraged in tests.
    """

    def __init__(self, index_service: Optional[MemoryIndexService] = None):
        self.index_service = index_service or get_memory_index_service()

    # ------------------------------------------------------------------ #
    # Writes                                                             #
    # ------------------------------------------------------------------ #

    def create_memory(
        self,
        *,
        tenant_id: str,
        user_id: str,
        content: str,
        layer: str = MemoryLayer.AGENT.value,
        memory_type: Optional[str] = None,
        agent_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        concept_tags: Optional[Sequence[str]] = None,
        idempotency_key: Optional[str] = None,
        embedding: Optional[List[float]] = None,
        embedding_model_info: Optional[EmbeddingModelInfo] = None,
        created_by: Optional[str] = None,
        actor: str = "agent",
    ) -> Dict[str, Any]:
        """Create (or upsert) a memory record.

        Returns a dict with ``memory_id``, ``layer``, ``memory_type``,
        ``event`` (``ADD`` / ``UPDATE``), and ``indexed`` (bool).
        """
        resolved_type = _resolve_memory_type(layer, memory_type)
        _validate_layer_policy(layer, resolved_type, actor)

        record: Dict[str, Any] = {
            # ``memory_id`` is intentionally omitted - PostgreSQL ``serial4``
            # assigns the primary key on insert.
            "tenant_id": tenant_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "conversation_id": conversation_id,
            "layer": layer,
            "memory_type": resolved_type,
            "content": content,
            "concept_tags": list(concept_tags or []),
            "idempotency_key": idempotency_key or _generate_idempotency_key(),
            "created_by": created_by,
            "updated_by": created_by,
            "status": "active",
            "delete_flag": "N",
        }

        index_name = _ensure_index_name(record, embedding_model_info)

        if (
            layer == MemoryLayer.AGENT.value
            and not index_name
            and not embedding_model_info
        ):
            resolved_model_info = _resolve_tenant_embedding_model_info(tenant_id)
            if resolved_model_info is not None:
                embedding_model_info = resolved_model_info
                index_name = _ensure_index_name(record, embedding_model_info)

        if not embedding and embedding_model_info is not None:
            embedding = _compute_content_embedding(content, embedding_model_info)

        existing = memory_record_db.find_by_idempotency(
            tenant_id=tenant_id,
            idempotency_key=record["idempotency_key"],
        )
        if existing is not None:
            memory_id = memory_record_db.upsert_memory_record_by_idempotency(
                {
                    # Existing primary key preserved implicitly via
                    # ``(tenant_id, idempotency_key)`` lookup; do not re-pass
                    # ``memory_id`` so the database never tries to remap it.
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "layer": layer,
                    "memory_type": resolved_type,
                    "content": content,
                    "concept_tags": list(concept_tags or []),
                    "idempotency_key": record["idempotency_key"],
                    "es_index_name": index_name,
                    "updated_by": created_by,
                }
            )
            indexed = False
            if index_name and memory_id:
                indexed = self.index_service.index_record(
                    record={
                        "memory_id": memory_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "agent_id": agent_id,
                        "conversation_id": conversation_id,
                        "content": content,
                        "layer": layer,
                        "memory_type": resolved_type,
                        "status": "active",
                        "idempotency_key": record["idempotency_key"],
                        "created_by": created_by,
                    },
                    embedding=embedding,
                    embedding_model_info=embedding_model_info,
                )
            return {
                "memory_id": memory_id,
                "layer": layer,
                "memory_type": resolved_type,
                "event": "UPDATE",
                "indexed": indexed,
            }

        memory_id = memory_record_db.insert_memory_record(record)
        if not memory_id:
            raise MemoryRecordError("Failed to persist memory record")

        indexed = False
        if index_name:
            indexed = self.index_service.index_record(
                record={
                    "memory_id": memory_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "content": content,
                    "layer": layer,
                    "memory_type": resolved_type,
                    "status": "active",
                    "idempotency_key": record["idempotency_key"],
                    "created_by": created_by,
                },
                embedding=embedding,
                embedding_model_info=embedding_model_info,
            )

        return {
            "memory_id": memory_id,
            "layer": layer,
            "memory_type": resolved_type,
            "event": "ADD",
            "indexed": indexed,
        }

    def update_memory(
        self,
        memory_id: int,
        tenant_id: str,
        update_data: Dict[str, Any],
        *,
        actor: str = "system",
    ) -> bool:
        """Update an existing memory record.

        If ``content`` is changed on an agent-layer record, the ES mirror is
        re-indexed with a freshly computed embedding vector so that the
        semantic-search index stays in sync.
        """
        if "layer" in update_data and "memory_type" in update_data:
            _validate_layer_policy(
                update_data["layer"], update_data["memory_type"], actor
            )

        record = memory_record_db.get_memory_record(memory_id, tenant_id)
        if record is None:
            return False

        ok = memory_record_db.update_memory_record(
            memory_id, tenant_id, update_data
        )
        if not ok:
            return False

        content_changed = "content" in update_data
        layer = update_data.get("layer") or record.get("layer")
        if content_changed and layer == MemoryLayer.AGENT.value:
            new_content = update_data["content"]
            embedding_model_info = _resolve_tenant_embedding_model_info(tenant_id)
            embedding = None
            if embedding_model_info is not None:
                embedding = _compute_content_embedding(new_content, embedding_model_info)
            self.index_service.index_record(
                record={
                    "memory_id": memory_id,
                    "tenant_id": tenant_id,
                    "user_id": record.get("user_id"),
                    "agent_id": record.get("agent_id"),
                    "conversation_id": record.get("conversation_id"),
                    "content": new_content,
                    "layer": record.get("layer"),
                    "memory_type": record.get("memory_type"),
                    "status": record.get("status"),
                    "idempotency_key": record.get("idempotency_key"),
                    "created_by": record.get("created_by"),
                },
                embedding=embedding,
                embedding_model_info=embedding_model_info,
            )

        return True

    def soft_delete_memory(
        self,
        memory_id: int,
        tenant_id: str,
        *,
        updated_by: Optional[str] = None,
        cascade_index: bool = True,
    ) -> bool:
        """Soft-delete a record. The ES mirror is removed best-effort."""
        record = memory_record_db.get_memory_record(memory_id, tenant_id)
        if record is None:
            return False
        ok = memory_record_db.soft_delete_memory_record(
            memory_id, tenant_id, updated_by=updated_by
        )
        if ok and cascade_index:
            index_name = record.get("es_index_name")
            if index_name:
                self.index_service.delete_record(memory_id, index_name)
        return ok

    # ------------------------------------------------------------------ #
    # Reads                                                              #
    # ------------------------------------------------------------------ #

    def get_memory(
        self, memory_id: int, tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        return memory_record_db.get_memory_record(memory_id, tenant_id)

    def get_memory_for_user(
        self,
        memory_id: int,
        tenant_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch a memory record with cross-user visibility enforced.

        Tenant-layer records are always visible within the tenant. User-layer
        records are scoped to the owning user. A ``None`` is returned if the
        record does not exist or is not accessible to the caller.
        """
        record = memory_record_db.get_memory_record(memory_id, tenant_id)
        if record is None:
            return None
        if record.get("user_id") and record["user_id"] != user_id:
            if record.get("layer") not in {"tenant"}:
                return None
        return record

    def list_memories(
        self,
        tenant_id: str,
        *,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        layer: Optional[str] = None,
        memory_type: Optional[str] = None,
        status: Optional[str] = "active",
        limit: int = 100,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> List[Dict[str, Any]]:
        return memory_record_db.list_memory_records(
            tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            layer=layer,
            memory_type=memory_type,
            status=status,
            limit=limit,
            offset=offset,
            include_deleted=include_deleted,
        )

    def list_full_context_memories(
        self,
        tenant_id: str,
        *,
        user_id: Optional[str] = None,
        layers: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return all active memories for the full-context layers.

        Tenant/user memories are always loaded in full per the retrieval
        policy. ``layers`` defaults to ``("tenant", "user")``.
        """
        if layers is None:
            layers = (
                MemoryLayer.TENANT.value,
                MemoryLayer.USER.value,
            )
        rows: List[Dict[str, Any]] = []
        for layer in layers:
            if not MemoryStoragePolicy.uses_full_context_for_layer(layer):
                # Skip layers that require vector search; callers that want
                # them should use ``MemoryRetrievalService`` instead.
                continue
            rows.extend(
                self.list_memories(
                    tenant_id,
                    user_id=user_id,
                    layer=layer,
                    memory_type=MemoryType.LONG_TERM.value,
                    limit=1000,
                )
            )
        return rows


# ---------------------------------------------------------------------------
# Module-level accessors
# ---------------------------------------------------------------------------


_default_service: Optional[MemoryRecordService] = None


def get_memory_record_service() -> MemoryRecordService:
    """Return the process-wide ``MemoryRecordService``."""
    global _default_service
    if _default_service is None:
        _default_service = MemoryRecordService()
    return _default_service


def reset_memory_record_service() -> None:
    """Reset the cached service (used by tests)."""
    global _default_service
    _default_service = None