"""Database access helpers for ``memory_retrieval_hits_t``.

These helpers are intentionally append-only: every row represents a single
recall observed by the ``search_memory`` flow. Dreaming aggregates them
into ``memory_records_t`` statistics in batch.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import Integer, func

from .client import filter_property, get_db_session
from .db_models import MemoryRetrievalHit


logger = logging.getLogger("memory_retrieval_hit_db")


def insert_retrieval_hits(hits: Iterable[Dict[str, Any]]) -> int:
    """Append a batch of retrieval hit rows.

    Each hit dict must include at least ``memory_id`` (nullable on miss
    rows), ``tenant_id``, ``user_id``, ``agent_id`` (all nullable for miss
    rows), and ``occurred_at`` (defaults to current timestamp when omitted).
    Unknown columns are dropped via ``filter_property``.

    Returns:
        Number of rows inserted.
    """
    rows: List[MemoryRetrievalHit] = []
    for hit in hits:
        payload = dict(hit)
        payload.setdefault("source", "nexent")
        payload.setdefault("grounded", False)
        if "occurred_at" not in payload or payload["occurred_at"] is None:
            payload["occurred_at"] = datetime.utcnow()
        payload.setdefault("day", payload["occurred_at"].date().isoformat())
        payload = filter_property(payload, MemoryRetrievalHit)
        rows.append(MemoryRetrievalHit(**payload))

    if not rows:
        return 0

    with get_db_session() as session:
        try:
            session.add_all(rows)
            session.commit()
            return len(rows)
        except Exception:
            session.rollback()
            logger.exception("insert_retrieval_hits failed")
            return 0


def count_hits_since(
    tenant_id: str,
    *,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    since: Optional[datetime] = None,
) -> int:
    """Count hits matching the given isolation scope."""
    with get_db_session() as session:
        try:
            query = session.query(func.count(MemoryRetrievalHit.hit_id)).filter(
                MemoryRetrievalHit.tenant_id == tenant_id,
            )
            if user_id is not None:
                query = query.filter(MemoryRetrievalHit.user_id == user_id)
            if agent_id is not None:
                query = query.filter(MemoryRetrievalHit.agent_id == agent_id)
            if since is not None:
                query = query.filter(
                    MemoryRetrievalHit.occurred_at >= since
                )
            return int(query.scalar() or 0)
        except Exception:
            session.rollback()
            logger.exception("count_hits_since failed")
            return 0


def list_hits_for_memory(
    memory_id: int,
    *,
    since: Optional[datetime] = None,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """Return hit rows for a single memory, ordered chronologically."""
    with get_db_session() as session:
        try:
            query = session.query(MemoryRetrievalHit).filter(
                MemoryRetrievalHit.memory_id == memory_id,
            )
            if since is not None:
                query = query.filter(MemoryRetrievalHit.occurred_at >= since)
            query = query.order_by(MemoryRetrievalHit.occurred_at.asc()).limit(limit)
            return [_hit_to_dict(row) for row in query.all()]
        except Exception:
            session.rollback()
            logger.exception("list_hits_for_memory failed")
            return []


def list_hits_for_user(
    tenant_id: str,
    user_id: str,
    *,
    since: Optional[datetime] = None,
    limit: int = 5000,
) -> List[Dict[str, Any]]:
    """Return hit rows for a user (used by Dreaming aggregation)."""
    with get_db_session() as session:
        try:
            query = session.query(MemoryRetrievalHit).filter(
                MemoryRetrievalHit.tenant_id == tenant_id,
                MemoryRetrievalHit.user_id == user_id,
            )
            if since is not None:
                query = query.filter(MemoryRetrievalHit.occurred_at >= since)
            query = query.order_by(MemoryRetrievalHit.occurred_at.asc()).limit(limit)
            return [_hit_to_dict(row) for row in query.all()]
        except Exception:
            session.rollback()
            logger.exception("list_hits_for_user failed")
            return []


def aggregate_memory_stats(
    tenant_id: str,
    *,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    since: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Aggregate recall statistics grouped by memory_id.

    Returns rows shaped like:
        ``{"memory_id": int, "hit_count": int, "grounded_count": int,
        "days": set[str], "query_hashes": set[str]}``
    """
    with get_db_session() as session:
        try:
            query = session.query(
                MemoryRetrievalHit.memory_id,
                func.count(MemoryRetrievalHit.hit_id).label("hit_count"),
                func.sum(
                    func.cast(MemoryRetrievalHit.grounded, Integer)
                ).label("grounded_count"),
            ).filter(MemoryRetrievalHit.tenant_id == tenant_id)
            if user_id is not None:
                query = query.filter(MemoryRetrievalHit.user_id == user_id)
            if agent_id is not None:
                query = query.filter(MemoryRetrievalHit.agent_id == agent_id)
            if since is not None:
                query = query.filter(MemoryRetrievalHit.occurred_at >= since)
            query = query.group_by(MemoryRetrievalHit.memory_id)
            raw_rows = query.all()
        except Exception:
            session.rollback()
            logger.exception("aggregate_memory_stats failed")
            return []

    out: List[Dict[str, Any]] = []
    for memory_id, hit_count, grounded_count in raw_rows:
        if memory_id is None:
            continue
        hits = list_hits_for_memory(memory_id, since=since, limit=10000)
        out.append(
            {
                "memory_id": memory_id,
                "hit_count": int(hit_count or 0),
                "grounded_count": int(grounded_count or 0),
                "days": {hit["day"] for hit in hits if hit.get("day")},
                "query_hashes": {
                    hit["query_hash"]
                    for hit in hits
                    if hit.get("query_hash")
                },
            }
        )
    return out


def delete_hits_before(cutoff: datetime) -> int:
    """Delete hit rows older than ``cutoff`` (housekeeping)."""
    with get_db_session() as session:
        try:
            rows = (
                session.query(MemoryRetrievalHit)
                .filter(MemoryRetrievalHit.occurred_at < cutoff)
                .delete(synchronize_session=False)
            )
            session.commit()
            return int(rows or 0)
        except Exception:
            session.rollback()
            logger.exception("delete_hits_before failed")
            return 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _hit_to_dict(row: MemoryRetrievalHit) -> Dict[str, Any]:
    return {
        "hit_id": row.hit_id,
        "tenant_id": row.tenant_id,
        "user_id": row.user_id,
        "agent_id": row.agent_id,
        "conversation_id": row.conversation_id,
        "memory_id": row.memory_id,
        "query_text": row.query_text,
        "query_hash": row.query_hash,
        "retrieval_score": float(row.retrieval_score) if row.retrieval_score is not None else None,
        "source": row.source,
        "occurred_at": row.occurred_at,
        "day": row.day,
        "grounded": bool(row.grounded),
    }