"""Backend orchestration for the SDK Dreaming algorithm."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from consts.const import (
    LIGHT_SLEEP_WINDOW_DAYS,
    MIN_PROMOTION_SCORE,
    MIN_RECALL_COUNT,
    MIN_UNIQUE_QUERIES,
    RECENCY_HALF_LIFE_DAYS,
)
from database import memory_dreaming_db, memory_record_db, memory_retrieval_hit_db
from nexent.memory.dreaming import (
    DreamingThresholds,
    build_candidate,
    select_candidates,
)
from services.memory_record_service import get_memory_record_service

logger = logging.getLogger("memory_dreaming_service")


class DreamingRunError(RuntimeError):
    pass


class MemoryDreamingService:
    def __init__(self, record_service: Any = None):
        self.record_service = record_service or get_memory_record_service()

    def _run_light(
        self, tenant_id: str, user_id: str, agent_id: str, window_days: int
    ) -> Dict[int, Dict[str, Any]]:
        stats = memory_retrieval_hit_db.aggregate_dreaming_stats(
            tenant_id,
            user_id,
            agent_id,
            since=datetime.utcnow() - timedelta(days=max(1, window_days)),
        )
        by_id = {int(item["memory_id"]): item for item in stats}
        for item in stats:
            memory_record_db.update_memory_record(
                item["memory_id"],
                tenant_id,
                {
                    "recall_count": item["hit_count"],
                    "daily_count": len(item["days"]),
                    "grounded_count": item["grounded_count"],
                    "last_recalled_at": item["last_recalled_at"],
                    "query_hashes": sorted(item["query_hashes"]),
                    "recall_days": sorted(item["days"]),
                },
            )
            memory_record_db.apply_dreaming_phase(
                item["memory_id"], tenant_id, phase="light"
            )
        return by_id

    def _run_rem(
        self,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        stats: Dict[int, Dict[str, Any]],
    ) -> List[Any]:
        records = memory_record_db.list_memory_records(
            tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            layer="agent",
            memory_type="short_term",
            status="active",
            limit=1000,
        )
        candidates = []
        for record in records:
            evidence = stats.get(int(record["memory_id"]), {})
            candidate = build_candidate(
                record, float(evidence.get("total_retrieval_score") or 0)
            )
            candidate.already_promoted = (
                memory_record_db.find_by_idempotency(
                    tenant_id, f"dreaming:{candidate.memory_id}"
                )
                is not None
            )
            memory_record_db.update_memory_record(
                candidate.memory_id,
                tenant_id,
                {"concept_tags": candidate.concept_tags},
            )
            if not candidate.noise:
                memory_record_db.apply_dreaming_phase(
                    candidate.memory_id, tenant_id, phase="rem"
                )
                candidate.rem_hits += 1
                candidate.last_rem_at = datetime.utcnow()
            candidates.append(candidate)
        return candidates

    def _promote(self, decisions: List[Any]) -> List[Dict[str, Any]]:
        results = []
        for decision in decisions:
            candidate = decision.candidate
            if decision.promote:
                created = self.record_service.create_memory(
                    tenant_id=candidate.tenant_id,
                    user_id=candidate.user_id,
                    agent_id=candidate.agent_id,
                    content=candidate.content,
                    layer="user",
                    memory_type="long_term",
                    concept_tags=candidate.concept_tags,
                    idempotency_key=f"dreaming:{candidate.memory_id}",
                    created_by="dreaming",
                    actor="dreaming",
                )
                event = created.get("event", "ADD")
            else:
                event = "DEFER"
            results.append(
                {
                    "memory_id": candidate.memory_id,
                    "score": decision.score,
                    "event": event,
                    "reason": decision.reason,
                    "archive_suggested": decision.archive_suggested,
                }
            )
        return results

    def run(
        self,
        *,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        window_days: int = LIGHT_SLEEP_WINDOW_DAYS,
        min_score: float = MIN_PROMOTION_SCORE,
        min_recall_count: int = MIN_RECALL_COUNT,
        min_unique_queries: int = MIN_UNIQUE_QUERIES,
    ) -> Dict[str, Any]:
        if not tenant_id or not user_id or not agent_id:
            raise DreamingRunError("tenant_id, user_id and agent_id are required")
        run_id = memory_dreaming_db.create_audit(tenant_id, user_id, agent_id)
        with memory_dreaming_db.try_scope_lock(
            tenant_id, user_id, agent_id
        ) as acquired:
            if not acquired:
                result = {
                    "run_id": run_id,
                    "status": "skipped",
                    "reason": "lock_busy",
                }
                memory_dreaming_db.finish_audit(
                    run_id, status="skipped", result_json=result
                )
                return result
            try:
                stats = self._run_light(tenant_id, user_id, agent_id, window_days)
                memory_dreaming_db.update_audit(
                    run_id,
                    {"current_phase": "rem", "light_count": len(stats)},
                )
                candidates = self._run_rem(tenant_id, user_id, agent_id, stats)
                memory_dreaming_db.update_audit(
                    run_id,
                    {"current_phase": "deep", "rem_count": len(candidates)},
                )
                decisions = select_candidates(
                    candidates,
                    thresholds=DreamingThresholds(
                        min_score=min_score,
                        min_recall_count=min_recall_count,
                        min_unique_queries=min_unique_queries,
                    ),
                    recency_half_life_days=RECENCY_HALF_LIFE_DAYS,
                )
                results = self._promote(decisions)
                promoted_count = sum(
                    item["event"] in {"ADD", "UPDATE"} for item in results
                )
                result = {
                    "run_id": run_id,
                    "status": "completed",
                    "light_count": len(stats),
                    "rem_count": len(candidates),
                    "promoted_count": promoted_count,
                    "deferred_count": len(results) - promoted_count,
                    "decisions": results,
                }
                memory_dreaming_db.finish_audit(
                    run_id,
                    status="completed",
                    light_count=len(stats),
                    rem_count=len(candidates),
                    promoted_count=promoted_count,
                    deferred_count=len(results) - promoted_count,
                    result_json=result,
                )
                return result
            except Exception as exc:
                logger.exception(
                    "Dreaming failed for tenant=%s user=%s agent=%s run=%s",
                    tenant_id,
                    user_id,
                    agent_id,
                    run_id,
                )
                error = f"{type(exc).__name__}: Dreaming phase failed"
                memory_dreaming_db.finish_audit(run_id, status="failed", error=error)
                raise DreamingRunError(error) from exc

    def list_audits(
        self,
        tenant_id: str,
        user_id: str,
        *,
        agent_id: Optional[str] = None,
        run_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        return memory_dreaming_db.list_audits(
            tenant_id,
            user_id,
            agent_id=agent_id,
            run_id=run_id,
            limit=limit,
        )


_service: Optional[MemoryDreamingService] = None


def get_memory_dreaming_service() -> MemoryDreamingService:
    global _service
    if _service is None:
        _service = MemoryDreamingService()
    return _service
