"""Database access helpers for the authoritative ``memory_records_t`` table.

The functions in this module translate the SDK-level
``MemoryRecord`` payload into SQLAlchemy inserts/updates against
``memory_records_t``. They are intentionally thin: policy enforcement and
index/embedding orchestration live in ``services/memory_record_service``.

Layer rules:
- ``tenant`` and ``user`` long-term memory are stored exclusively in PG.
- ``agent`` short-term memory is stored in PG and mirrored into Elasticsearch
  by ``services/memory_index_service``.

All write operations are soft-delete aware (``delete_flag='N'``).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import and_

from .client import filter_property, get_db_session
from .db_models import MemoryRecord


logger = logging.getLogger("memory_record_db")


# ---------------------------------------------------------------------------
# Inserts / updates
# ---------------------------------------------------------------------------


def generate_memory_id() -> None:
    """No-op placeholder kept for API compatibility.

    ``memory_id`` is allocated by the PostgreSQL ``serial4`` column on insert.
    Callers that previously passed a generated uuid must omit ``memory_id`` so
    the database can assign the primary key. The function is preserved so that
    upstream services / tests continue to compile, but it always returns
    ``None`` and never produces a value to seed into the payload.
    """
    return None


def insert_memory_record(record: Dict[str, Any]) -> Optional[int]:
    """Insert a new memory record.

    Args:
        record: Payload describing the memory. Required keys: ``tenant_id``,
            ``user_id``, ``layer``, ``content``, ``idempotency_key``.
            ``memory_id`` must be omitted - the database assigns the serial
            primary key on insert.

    Returns:
        The persisted memory id (int) assigned by the database, or ``None``
        on failure.
    """
    payload = dict(record)
    payload.pop("memory_id", None)
    payload.setdefault("status", "active")
    payload.setdefault("delete_flag", "N")

    with get_db_session() as session:
        try:
            payload = filter_property(payload, MemoryRecord)
            row = MemoryRecord(**payload)
            session.add(row)
            session.commit()
            return row.memory_id
        except Exception:
            session.rollback()
            logger.exception("insert_memory_record failed")
            return None


def upsert_memory_record_by_idempotency(record: Dict[str, Any]) -> Optional[int]:
    """Insert a memory record, or update it when the idempotency key exists.

    Idempotency is scoped by ``(tenant_id, idempotency_key)`` - the same key
    from a different tenant is treated as a distinct memory. If a matching
    row exists, ``content`` and ``concept_tags`` are refreshed and
    ``update_time`` is bumped; ``memory_id`` is preserved.

    Args:
        record: Same shape as ``insert_memory_record``. ``memory_id`` is
            ignored on insert - the database allocates the serial id.

    Returns:
        The persisted memory id (int, existing or new), or ``None`` on failure.
    """
    tenant_id = record.get("tenant_id")
    idempotency_key = record.get("idempotency_key")
    if not tenant_id or not idempotency_key:
        raise ValueError(
            "upsert_memory_record_by_idempotency requires tenant_id and idempotency_key"
        )

    with get_db_session() as session:
        try:
            existing = (
                session.query(MemoryRecord)
                .filter(
                    MemoryRecord.tenant_id == tenant_id,
                    MemoryRecord.idempotency_key == idempotency_key,
                    MemoryRecord.delete_flag == "N",
                )
                .first()
            )
            if existing is not None:
                update_payload = filter_property(
                    {
                        "content": record.get("content", existing.content),
                        "concept_tags": record.get("concept_tags"),
                        "status": record.get("status", existing.status),
                        "updated_by": record.get("updated_by"),
                        "memory_type": record.get("memory_type", existing.memory_type),
                        "es_index_name": record.get("es_index_name", existing.es_index_name),
                    },
                    MemoryRecord,
                )
                for key, value in update_payload.items():
                    setattr(existing, key, value)
                session.commit()
                return existing.memory_id

            payload = filter_property(record, MemoryRecord)
            payload.pop("memory_id", None)
            payload.setdefault("status", "active")
            payload.setdefault("delete_flag", "N")
            row = MemoryRecord(**payload)
            session.add(row)
            session.commit()
            return row.memory_id
        except Exception:
            session.rollback()
            logger.exception("upsert_memory_record_by_idempotency failed")
            return None


def update_memory_record(
    memory_id: int,
    tenant_id: str,
    update_data: Dict[str, Any],
) -> bool:
    """Update fields of an active memory record.

    Args:
        memory_id: Primary key of the record (integer).
        tenant_id: Tenant isolation key (defence-in-depth on top of PK).
        update_data: Columns to update.

    Returns:
        True on success, False on failure.
    """
    with get_db_session() as session:
        try:
            payload = filter_property(update_data, MemoryRecord)
            rows = (
                session.query(MemoryRecord)
                .filter(
                    MemoryRecord.memory_id == memory_id,
                    MemoryRecord.tenant_id == tenant_id,
                    MemoryRecord.delete_flag == "N",
                )
                .update(payload)
            )
            session.commit()
            return bool(rows)
        except Exception:
            session.rollback()
            logger.exception("update_memory_record failed")
            return False


def soft_delete_memory_record(
    memory_id: int,
    tenant_id: str,
    updated_by: Optional[str] = None,
) -> bool:
    """Soft-delete a single record by id."""
    with get_db_session() as session:
        try:
            rows = (
                session.query(MemoryRecord)
                .filter(
                    MemoryRecord.memory_id == memory_id,
                    MemoryRecord.tenant_id == tenant_id,
                    MemoryRecord.delete_flag == "N",
                )
                .update(
                    {
                        "delete_flag": "Y",
                        "status": "archived",
                        "updated_by": updated_by,
                    }
                )
            )
            session.commit()
            return bool(rows)
        except Exception:
            session.rollback()
            logger.exception("soft_delete_memory_record failed")
            return False


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_memory_record(
    memory_id: int,
    tenant_id: str,
    *,
    include_deleted: bool = False,
) -> Optional[Dict[str, Any]]:
    """Fetch a single memory record by id."""
    with get_db_session() as session:
        try:
            query = session.query(MemoryRecord).filter(
                MemoryRecord.memory_id == memory_id,
                MemoryRecord.tenant_id == tenant_id,
            )
            if not include_deleted:
                query = query.filter(MemoryRecord.delete_flag == "N")
            record = query.first()
            if record is None:
                return None
            return _record_to_dict(record)
        except Exception:
            session.rollback()
            logger.exception("get_memory_record failed")
            return None


def list_memory_records(
    tenant_id: str,
    *,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    layer: Optional[str] = None,
    memory_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    include_deleted: bool = False,
) -> List[Dict[str, Any]]:
    """List memory records with the standard isolation filters.

    Args:
        tenant_id: Tenant isolation key (required).
        user_id: Optional user filter.
        agent_id: Optional agent filter (implies agent layer).
        conversation_id: Optional conversation filter.
        layer: Optional layer filter (``tenant``/``user``/``agent``).
        memory_type: Optional memory type filter.
        status: Optional status filter; defaults to ``active``.
        limit: Maximum number of rows to return.
        offset: Pagination offset.
        include_deleted: When ``True``, soft-deleted rows are included.

    Returns:
        A list of records serialized as plain dicts.
    """
    # Normalize empty-string filters to ``None`` so that empty query params
    # (e.g. ``?status=``) do not translate into ``WHERE status = ''`` filters
    # that match no rows.
    if user_id == "":
        user_id = None
    if agent_id == "":
        agent_id = None
    if conversation_id == "":
        conversation_id = None
    if layer == "":
        layer = None
    if memory_type == "":
        memory_type = None
    if status == "":
        status = None

    with get_db_session() as session:
        try:
            query = session.query(MemoryRecord).filter(
                MemoryRecord.tenant_id == tenant_id,
            )
            if user_id is not None:
                query = query.filter(MemoryRecord.user_id == user_id)
            if agent_id is not None:
                query = query.filter(MemoryRecord.agent_id == agent_id)
            if conversation_id is not None:
                query = query.filter(
                    MemoryRecord.conversation_id == conversation_id
                )
            if layer is not None:
                query = query.filter(MemoryRecord.layer == layer)
            if memory_type is not None:
                query = query.filter(MemoryRecord.memory_type == memory_type)
            if status is not None:
                query = query.filter(MemoryRecord.status == status)
            elif not include_deleted:
                query = query.filter(MemoryRecord.status == "active")
            if not include_deleted:
                query = query.filter(MemoryRecord.delete_flag == "N")

            query = query.order_by(MemoryRecord.update_time.desc())
            query = query.limit(limit).offset(offset)
            return [_record_to_dict(row) for row in query.all()]
        except Exception:
            session.rollback()
            logger.exception("list_memory_records failed")
            return []


def list_active_memory_ids_by_layer(
    tenant_id: str,
    layer: str,
    *,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> List[int]:
    """Return memory ids for the given layer (used by Dreaming pre-load)."""
    with get_db_session() as session:
        try:
            query = session.query(MemoryRecord.memory_id).filter(
                MemoryRecord.tenant_id == tenant_id,
                MemoryRecord.layer == layer,
                MemoryRecord.delete_flag == "N",
                MemoryRecord.status == "active",
            )
            if user_id is not None:
                query = query.filter(MemoryRecord.user_id == user_id)
            if agent_id is not None:
                query = query.filter(MemoryRecord.agent_id == agent_id)
            return [row[0] for row in query.all()]
        except Exception:
            session.rollback()
            logger.exception("list_active_memory_ids_by_layer failed")
            return []


def get_memory_records_by_ids(
    memory_ids: Sequence[int],
    tenant_id: str,
) -> List[Dict[str, Any]]:
    """Bulk-fetch memory records by id (used by Dreaming aggregation)."""
    if not memory_ids:
        return []
    with get_db_session() as session:
        try:
            rows = (
                session.query(MemoryRecord)
                .filter(
                    MemoryRecord.tenant_id == tenant_id,
                    MemoryRecord.memory_id.in_(list(memory_ids)),
                )
                .all()
            )
            return [_record_to_dict(row) for row in rows]
        except Exception:
            session.rollback()
            logger.exception("get_memory_records_by_ids failed")
            return []


def find_by_idempotency(
    tenant_id: str,
    idempotency_key: str,
) -> Optional[Dict[str, Any]]:
    """Return the existing record for a (tenant, idempotency_key) pair, if any."""
    with get_db_session() as session:
        try:
            row = (
                session.query(MemoryRecord)
                .filter(
                    MemoryRecord.tenant_id == tenant_id,
                    MemoryRecord.idempotency_key == idempotency_key,
                    MemoryRecord.delete_flag == "N",
                )
                .first()
            )
            return _record_to_dict(row) if row is not None else None
        except Exception:
            session.rollback()
            logger.exception("find_by_idempotency failed")
            return None


# ---------------------------------------------------------------------------
# Dreaming aggregation helpers
# ---------------------------------------------------------------------------


def increment_recall_stats(
    memory_id: int,
    tenant_id: str,
    *,
    query_hash: Optional[str] = None,
    day: Optional[str] = None,
    grounded: bool = False,
) -> bool:
    """Bump recall counters on a memory row in a single transaction.

    Used by Dreaming aggregation after it batches hit rows. The function
    keeps ``query_hashes`` and ``recall_days`` deduplicated.
    """
    with get_db_session() as session:
        try:
            row = (
                session.query(MemoryRecord)
                .filter(
                    MemoryRecord.memory_id == memory_id,
                    MemoryRecord.tenant_id == tenant_id,
                    MemoryRecord.delete_flag == "N",
                )
                .first()
            )
            if row is None:
                return False

            row.recall_count = (row.recall_count or 0) + 1
            row.daily_count = (row.daily_count or 0) + 1
            if grounded:
                row.grounded_count = (row.grounded_count or 0) + 1
            row.last_recalled_at = _utcnow()

            existing_hashes: List[str] = list(row.query_hashes or [])
            if query_hash and query_hash not in existing_hashes:
                existing_hashes.append(query_hash)
            row.query_hashes = existing_hashes

            existing_days: List[str] = list(row.recall_days or [])
            if day and day not in existing_days:
                existing_days.append(day)
            row.recall_days = existing_days

            session.commit()
            return True
        except Exception:
            session.rollback()
            logger.exception("increment_recall_stats failed")
            return False


def apply_dreaming_phase(
    memory_id: int,
    tenant_id: str,
    *,
    phase: str,
) -> bool:
    """Apply Light Sleep or REM Sleep phase counters."""
    with get_db_session() as session:
        try:
            row = (
                session.query(MemoryRecord)
                .filter(
                    MemoryRecord.memory_id == memory_id,
                    MemoryRecord.tenant_id == tenant_id,
                    MemoryRecord.delete_flag == "N",
                )
                .first()
            )
            if row is None:
                return False
            now = _utcnow()
            if phase == "light":
                row.light_hits = (row.light_hits or 0) + 1
                row.last_light_at = now
            elif phase == "rem":
                row.rem_hits = (row.rem_hits or 0) + 1
                row.last_rem_at = now
            else:
                raise ValueError(f"Unknown dreaming phase: {phase}")
            session.commit()
            return True
        except Exception:
            session.rollback()
            logger.exception("apply_dreaming_phase failed")
            return False


def list_memories_for_dreaming(
    tenant_id: str,
    *,
    user_id: str,
    layer: str = "agent",
    min_recall_count: int = 0,
    window_days: int = 7,
) -> List[Dict[str, Any]]:
    """Return agent memories eligible for Dreaming promotion.

    Filters: same tenant/user, target layer (default agent), status active,
    recall_count >= min_recall_count, and the row has been recalled within
    the last ``window_days`` days.
    """
    with get_db_session() as session:
        try:
            query = session.query(MemoryRecord).filter(
                and_(
                    MemoryRecord.tenant_id == tenant_id,
                    MemoryRecord.user_id == user_id,
                    MemoryRecord.layer == layer,
                    MemoryRecord.status == "active",
                    MemoryRecord.delete_flag == "N",
                    MemoryRecord.recall_count >= min_recall_count,
                )
            )
            rows = query.all()
            cutoff = _utcnow().timestamp() - window_days * 86400
            eligible: List[Dict[str, Any]] = []
            for row in rows:
                last = row.last_recalled_at
                if last is None:
                    continue
                if last.timestamp() < cutoff:
                    continue
                eligible.append(_record_to_dict(row))
            return eligible
        except Exception:
            session.rollback()
            logger.exception("list_memories_for_dreaming failed")
            return []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _record_to_dict(record: MemoryRecord) -> Dict[str, Any]:
    """Serialize a ``MemoryRecord`` ORM row into a JSON-friendly dict."""
    return {
        "memory_id": record.memory_id,
        "tenant_id": record.tenant_id,
        "user_id": record.user_id,
        "agent_id": record.agent_id,
        "conversation_id": record.conversation_id,
        "layer": record.layer,
        "memory_type": record.memory_type,
        "status": record.status,
        "content": record.content,
        "concept_tags": list(record.concept_tags or []),
        "es_index_name": record.es_index_name,
        "create_time": _isoformat_or_none(record.create_time),
        "update_time": _isoformat_or_none(record.update_time),
        "created_by": record.created_by,
        "updated_by": record.updated_by,
        "delete_flag": record.delete_flag,
        "idempotency_key": record.idempotency_key,
        "recall_count": record.recall_count or 0,
        "daily_count": record.daily_count or 0,
        "grounded_count": record.grounded_count or 0,
        "last_recalled_at": _isoformat_or_none(record.last_recalled_at),
        "query_hashes": list(record.query_hashes or []),
        "recall_days": list(record.recall_days or []),
        "light_hits": record.light_hits or 0,
        "rem_hits": record.rem_hits or 0,
        "last_light_at": _isoformat_or_none(record.last_light_at),
        "last_rem_at": _isoformat_or_none(record.last_rem_at),
    }


def _isoformat_or_none(value):
    """Return ``value.isoformat()`` for datetimes, otherwise ``None``/passthrough."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _utcnow():
    from datetime import datetime

    return datetime.utcnow()