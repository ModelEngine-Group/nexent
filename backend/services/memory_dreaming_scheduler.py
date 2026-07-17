"""Dreaming consolidation runner for the Memory Architecture (Phase 2).

Dreaming promotes agent short-term memories into user long-term memory. It
runs in three phases:

1. **Light Sleep** - aggregate ``memory_retrieval_hits_t`` rows into the
   per-memory ``light_hits`` counter and ``recall_count`` /
   ``recall_days`` / ``query_hashes`` columns.
2. **REM Sleep** - extract repeating concepts / patterns, write concept
   tags to ``memory_records_t``. The phase is implemented as a lightweight
   keyword-frequency pass; LLM-driven concept extraction can be wired in
   later without changing the public API.
3. **Deep Sleep** - select eligible agent memories and promote them to
   ``user`` long-term memory using the documented scoring formula
   (frequency / relevance / diversity / recency / consolidation /
   concept + phase boost).

Promotion thresholds and weights live in ``consts.const``. The phases are
exposed as standalone ``run_light_sleep`` / ``run_rem_sleep`` /
``run_deep_sleep`` functions plus the aggregate ``run_once`` so callers
can trigger a single pass per tenant on demand (e.g. from a future agent
timer). The module deliberately does **not** ship an internal scheduler,
background thread, or cron expression: agent-driven scheduling will be
added in a later phase, and we want to avoid having to coordinate cron,
lock watchdog and lifecycle here before the agent timer feature lands.
"""

from __future__ import annotations

import logging
import math
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set

from consts.const import (
    AGENT_SHORT_TERM_HALF_LIFE_DAYS,
    LIGHT_SLEEP_WINDOW_DAYS,
    MIN_PROMOTION_SCORE,
    MIN_RECALL_COUNT,
    MIN_UNIQUE_QUERIES,
    RECENCY_HALF_LIFE_DAYS,
)
from database import memory_record_db, memory_retrieval_hit_db
from services.memory_record_service import (
    MemoryRecordError,
    get_memory_record_service,
)


logger = logging.getLogger("memory_dreaming_scheduler")


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _frequency(recall_count: int, daily_count: int, grounded_count: int) -> float:
    """Log-scaled accumulation of recall signals."""
    signal = max(0, recall_count) + max(0, daily_count) + max(0, grounded_count)
    return _clamp01(math.log1p(signal) / math.log1p(10))


def _relevance(hit_count: int, total_score: float) -> float:
    """Average retrieval score across hits, clamped to [0, 1]."""
    if hit_count <= 0:
        return 0.0
    return _clamp01(total_score / max(1, hit_count))


def _diversity(unique_queries: int) -> float:
    """Smoothed saturation in [0, 1]."""
    return _clamp01(math.log1p(unique_queries) / math.log1p(5))


def _recency(last_recalled_at: Optional[datetime]) -> float:
    """Exponential decay based on ``RECENCY_HALF_LIFE_DAYS``."""
    if last_recalled_at is None:
        return 0.0
    delta_days = (datetime.utcnow() - last_recalled_at).total_seconds() / 86400.0
    if delta_days < 0:
        delta_days = 0
    half_life = max(1, RECENCY_HALF_LIFE_DAYS)
    return _clamp01(math.pow(0.5, delta_days / half_life))


def _consolidation(light_hits: int, rem_hits: int) -> float:
    """Boost when both Light and REM phases have seen the memory."""
    combined = max(0, light_hits) + max(0, rem_hits)
    return _clamp01(math.log1p(combined) / math.log1p(6))


def _concept(concept_tags: Sequence[str]) -> float:
    """Higher when concept tags have been attached."""
    if not concept_tags:
        return 0.0
    return _clamp01(math.log1p(len(concept_tags)) / math.log1p(8))


# Weights reflect ``openclaw_dreaming.md`` §深眠阶段评分体系.
_PROMOTION_WEIGHTS: Dict[str, float] = {
    "relevance": 0.30,
    "frequency": 0.24,
    "diversity": 0.15,
    "recency": 0.15,
    "consolidation": 0.10,
    "concept": 0.06,
}


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(weights.values()) or 1.0
    return {key: value / total for key, value in weights.items()}


def _phase_boost(light_hits: int, rem_hits: int) -> float:
    """PhaseBoost from the design doc; kept small to avoid runaway scores."""
    if light_hits <= 0 or rem_hits <= 0:
        return 0.0
    return _clamp01(min(0.05, light_hits * 0.01 + rem_hits * 0.01))


def compute_promotion_score(record: Dict[str, Any]) -> float:
    """Compute the composite score for a single memory record."""
    recall_count = int(record.get("recall_count") or 0)
    daily_count = int(record.get("daily_count") or 0)
    grounded_count = int(record.get("grounded_count") or 0)
    light_hits = int(record.get("light_hits") or 0)
    rem_hits = int(record.get("rem_hits") or 0)
    last_recalled_at = record.get("last_recalled_at")
    query_hashes = record.get("query_hashes") or []

    metrics = {
        "frequency": _frequency(recall_count, daily_count, grounded_count),
        "relevance": _relevance(recall_count, 1.0),
        "diversity": _diversity(len(query_hashes)),
        "recency": _recency(last_recalled_at),
        "consolidation": _consolidation(light_hits, rem_hits),
        "concept": _concept(record.get("concept_tags") or []),
    }
    weights = _normalize_weights(_PROMOTION_WEIGHTS)
    score = sum(metrics[key] * weights[key] for key in metrics)
    score += _phase_boost(light_hits, rem_hits)
    return _clamp01(score)


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------


def run_light_sleep(
    *,
    tenant_id: str,
    user_id: str,
    agent_id: Optional[str] = None,
    window_days: int = LIGHT_SLEEP_WINDOW_DAYS,
) -> int:
    """Aggregate recent hits into memory row counters.

    Returns the number of memory rows touched.
    """
    since = datetime.utcnow() - timedelta(days=max(1, window_days))
    stats = memory_retrieval_hit_db.aggregate_memory_stats(
        tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        since=since,
    )
    touched = 0
    for entry in stats:
        memory_id = entry["memory_id"]
        # Last hit day is the most recent value in the per-memory hit set.
        last_day = max(entry["days"]) if entry["days"] else None
        last_recalled_at = (
            datetime.fromisoformat(last_day) if last_day else None
        )
        memory_record_db.update_memory_record(
            memory_id,
            tenant_id,
            {
                "recall_count": entry["hit_count"],
                "grounded_count": entry["grounded_count"],
                "query_hashes": sorted(entry["query_hashes"]),
                "recall_days": sorted(entry["days"]),
                "last_recalled_at": last_recalled_at,
            },
        )
        memory_record_db.apply_dreaming_phase(
            memory_id, tenant_id, phase="light"
        )
        touched += 1
    return touched


_KEYWORD_STOPWORDS: Set[str] = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "of", "in", "on", "at", "by", "for", "with", "to", "from",
    "i", "you", "he", "she", "it", "we", "they",
    "的", "了", "是", "在", "和", "与", "及", "或", "我", "你", "他", "她", "它",
    "我们", "你们", "他们", "这", "那", "这个", "那个",
}


def _tokenize(text: str) -> List[str]:
    return [
        token.strip().lower()
        for token in text.replace("\n", " ").split()
        if token.strip() and token.strip().lower() not in _KEYWORD_STOPWORDS
    ]


def run_rem_sleep(
    *,
    tenant_id: str,
    user_id: str,
    agent_id: Optional[str] = None,
    max_keywords: int = 5,
) -> int:
    """Extract concept tags from frequently appearing tokens.

    Returns the number of memory rows whose ``concept_tags`` were updated.
    """
    rows = memory_record_db.list_memory_records(
        tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        layer="agent",
        memory_type="short_term",
        status="active",
        limit=500,
    )
    touched = 0
    for row in rows:
        tokens = _tokenize(row.get("content", ""))
        if not tokens:
            continue
        counter = Counter(tokens)
        top = [token for token, _ in counter.most_common(max_keywords)]
        if not top:
            continue
        existing = list(row.get("concept_tags") or [])
        merged = list(dict.fromkeys(existing + top))[:max_keywords]
        memory_record_db.update_memory_record(
            row["memory_id"],
            tenant_id,
            {"concept_tags": merged},
        )
        memory_record_db.apply_dreaming_phase(
            row["memory_id"], tenant_id, phase="rem"
        )
        touched += 1
    return touched


def run_deep_sleep(
    *,
    tenant_id: str,
    user_id: str,
    agent_id: Optional[str] = None,
    min_score: float = MIN_PROMOTION_SCORE,
    min_recall_count: int = MIN_RECALL_COUNT,
    min_unique_queries: int = MIN_UNIQUE_QUERIES,
) -> List[Dict[str, Any]]:
    """Promote agent memories that pass the promotion thresholds.

    Returns the list of promotion results (``memory_id``, ``score``, ``event``).
    """
    eligible = memory_record_db.list_memories_for_dreaming(
        tenant_id,
        user_id=user_id,
        layer="agent",
        min_recall_count=min_recall_count,
        window_days=LIGHT_SLEEP_WINDOW_DAYS,
    )
    promoted: List[Dict[str, Any]] = []
    service = get_memory_record_service()
    for row in eligible:
        query_hashes = row.get("query_hashes") or []
        if len(set(query_hashes)) < min_unique_queries:
            continue
        score = compute_promotion_score(row)
        if score < min_score:
            continue
        try:
            service.create_memory(
                tenant_id=tenant_id,
                user_id=user_id,
                content=row.get("content", ""),
                layer="user",
                memory_type="long_term",
                agent_id=row.get("agent_id"),
                conversation_id=row.get("conversation_id"),
                concept_tags=row.get("concept_tags") or [],
                idempotency_key=f"dreaming:{row['memory_id']}",
                created_by="dreaming",
                actor="dreaming",
            )
        except MemoryRecordError as exc:
            logger.warning(
                "dreaming promotion skipped for %s: %s", row["memory_id"], exc
            )
            continue
        memory_record_db.apply_dreaming_phase(
            row["memory_id"], tenant_id, phase="rem"
        )
        promoted.append(
            {
                "memory_id": row["memory_id"],
                "score": score,
                "event": "PROMOTE",
            }
        )
    return promoted


# ---------------------------------------------------------------------------
# Manual entry points
# ---------------------------------------------------------------------------


def run_once(*, timeout_seconds: int = 1800) -> Dict[str, Any]:
    """Execute one full Dreaming cycle across known tenants.

    This function is the single manual entry point: callers (e.g. an agent
    timer introduced later) invoke ``run_once`` whenever they want a fresh
    pass. Phase 2 does not ship a scheduler; the function is intentionally
    synchronous and idempotent so it can be re-invoked safely.

    Args:
        timeout_seconds: Soft cap on wall-clock runtime per call. Iteration
            stops once the deadline is reached; partial state is returned.

    Returns:
        Summary dict with tenant count, light/rem rows touched, and the
        list of promotion events.
    """
    started = time.time()
    deadline = started + max(60, timeout_seconds)

    # ``list_distinct_tenants`` is intentionally conservative: we only run
    # dreaming over tenants that have actually touched memory recently.
    tenants = list_distinct_tenants()
    summary: Dict[str, Any] = {
        "tenants": len(tenants),
        "light_rows": 0,
        "rem_rows": 0,
        "promotions": [],
    }

    for tenant_id, user_id in tenants:
        if time.time() >= deadline:
            logger.warning("Dreaming run hit timeout; aborting remaining tenants")
            break
        try:
            light = run_light_sleep(tenant_id=tenant_id, user_id=user_id)
            rem = run_rem_sleep(tenant_id=tenant_id, user_id=user_id)
            deep = run_deep_sleep(tenant_id=tenant_id, user_id=user_id)
            summary["light_rows"] += light
            summary["rem_rows"] += rem
            summary["promotions"].extend(deep)
        except Exception:
            logger.exception(
                "Dreaming iteration failed for tenant=%s user=%s",
                tenant_id,
                user_id,
            )

    summary["elapsed_seconds"] = time.time() - started
    return summary


def list_distinct_tenants() -> List[Any]:
    """Return ``(tenant_id, user_id)`` tuples with recent memory activity.

    Implementation: distinct pairs from ``memory_retrieval_hits_t``. When
    no hits exist (fresh deployments) this returns ``[]`` and Dreaming
    becomes a no-op, which is the intended behavior.
    """
    try:
        from database.client import get_db_session
        from database.db_models import MemoryRetrievalHit
        from sqlalchemy import distinct

        with get_db_session() as session:
            rows = (
                session.query(
                    distinct(MemoryRetrievalHit.tenant_id),
                    distinct(MemoryRetrievalHit.user_id),
                )
                .filter(
                    MemoryRetrievalHit.tenant_id.isnot(None),
                    MemoryRetrievalHit.user_id.isnot(None),
                )
                .all()
            )
        return [(t, u) for t, u in rows if t and u]
    except Exception:
        logger.exception("list_distinct_tenants failed")
        return []