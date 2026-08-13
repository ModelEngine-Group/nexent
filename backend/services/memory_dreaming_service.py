"""Backend orchestration for the SDK Dreaming algorithm."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from consts.const import (
    DREAMING_SUMMARIZATION_BACKOFF_BASE_SECONDS,
    DREAMING_SUMMARIZATION_MAX_ATTEMPTS,
    DREAMING_LONG_TERM_MAX_CHARS,
    DREAMING_MAX_AGE_DAYS,
    DREAMING_SOURCE_LIMIT,
    LIGHT_SLEEP_WINDOW_DAYS,
    MIN_PROMOTION_SCORE,
    MIN_RECALL_COUNT,
    MIN_UNIQUE_QUERIES,
    RECENCY_HALF_LIFE_DAYS,
)
from database import memory_dreaming_db, memory_long_term_db, memory_record_db, memory_retrieval_hit_db
from nexent.memory.dreaming import (
    DreamingMemoryUnit,
    DreamingThresholds,
    build_dreaming_version,
    build_candidate,
    select_candidates,
    units_from_decisions,
)
from services.memory_record_service import get_memory_record_service

logger = logging.getLogger("memory_dreaming_service")
USER_DREAMING_SCOPE = "__user__"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DreamingRunError(RuntimeError):
    pass


class DreamingConflictError(RuntimeError):
    pass


class MemoryDreamingService:
    def __init__(self, record_service: Any = None, summarizer: Any = None):
        self.record_service = record_service or get_memory_record_service()
        self.summarizer = summarizer

    def _run_light(
        self, tenant_id: str, user_id: str, agent_id: str, window_days: int
    ) -> Dict[int, Dict[str, Any]]:
        stats = memory_retrieval_hit_db.aggregate_dreaming_stats(
            tenant_id,
            user_id,
            None if agent_id == USER_DREAMING_SCOPE else agent_id,
            since=_utcnow() - timedelta(days=max(1, window_days)),
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
            agent_id=None if agent_id == USER_DREAMING_SCOPE else agent_id,
            layer="agent",
            memory_type="short_term",
            status="active",
            limit=None,
        )
        cutoff = _utcnow() - timedelta(days=DREAMING_MAX_AGE_DAYS)
        candidates = []
        for record in records:
            created_at = record.get("create_time")
            if created_at:
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at)
                if created_at.replace(tzinfo=None) < cutoff:
                    continue
            evidence = stats.get(int(record["memory_id"]), {})
            candidate = build_candidate(
                record, float(evidence.get("total_retrieval_score") or 0)
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
                candidate.last_rem_at = _utcnow()
            candidates.append(candidate)
        return candidates

    def _build_version(
        self,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        run_id: int,
        decisions: List[Any],
        config_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        active = memory_long_term_db.get_active(tenant_id, "user", user_id)
        parent_units = []
        if active and active.get("content", "").strip():
            parent_units.append(DreamingMemoryUnit(
                unit_id=f"long-term-version:{active['version_id']}",
                content=active["content"], evidence_ids=active.get("evidence_ids") or [],
                strong_constraint=active.get("source") == "manual",
            ))
        parent_unit_ids = {unit.unit_id for unit in parent_units}
        parent_evidence_ids = {
            evidence_id for unit in parent_units for evidence_id in unit.evidence_ids
        }
        effective_source_limit = (
            (config_snapshot or {}).get("source_limit") or DREAMING_SOURCE_LIMIT
        )
        effective_long_term_max_chars = (
            (config_snapshot or {}).get("long_term_max_chars") or DREAMING_LONG_TERM_MAX_CHARS
        )
        effective_summarization_max_attempts = (
            (config_snapshot or {}).get("summarization_max_attempts")
            or DREAMING_SUMMARIZATION_MAX_ATTEMPTS
        )
        new_units = units_from_decisions(
            decisions,
            source_limit=effective_source_limit,
            excluded_evidence_ids=parent_evidence_ids,
        )
        new_units = [
            unit
            for unit in new_units
            if unit.unit_id not in parent_unit_ids
            and not set(unit.evidence_ids).issubset(parent_evidence_ids)
        ]
        if not new_units:
            return None
        result = build_dreaming_version(
            parent_units=parent_units,
            new_units=new_units,
            max_chars=effective_long_term_max_chars,
            summarizer=self.summarizer or self._tenant_summarizer(tenant_id, user_id),
            prior_source=(active or {}).get("source", "none"),
            max_attempts=effective_summarization_max_attempts,
            run_id=run_id,
            agent_id=agent_id,
            backoff_base_seconds=DREAMING_SUMMARIZATION_BACKOFF_BASE_SECONDS,
        )
        version = memory_long_term_db.create_and_activate(
            tenant_id=tenant_id,
            scope="user",
            subject_id=user_id,
            content=result.published_content,
            source="dreaming",
            actor_user_id=user_id,
            expected_active_version_id=(active or {}).get("version_id"),
            dreaming_run_id=run_id,
            raw_dreaming_input=result.raw_content,
            generation_audit={
                "status": result.summarization_status,
                "attempts": result.summarization_attempts,
                "attempt_audit": result.summarization_audit,
            },
            evidence_ids=sorted(
                {
                    evidence_id
                    for unit in [*parent_units, *new_units]
                    for evidence_id in unit.evidence_ids
                }
            ),
            fallback_details={
                "used": result.summarization_status == "mechanical_fallback",
                "mechanical_truncation": result.mechanical_truncation,
            },
            omission_details={"evidence_ids": result.omitted_evidence_ids},
        )
        if version is None:
            raise DreamingConflictError("active version changed during Dreaming")
        return version

    @staticmethod
    def _tenant_summarizer(tenant_id: str, user_id: str):
        instance = None

        def summarize(request):
            nonlocal instance
            if instance is None:
                from services.memory_dreaming_compressor import TenantDreamingSummarizer

                instance = TenantDreamingSummarizer(tenant_id, user_id)
            return instance(request)

        return summarize

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
        run_id: Optional[int] = None,
        trigger_source: str = "manual",
    ) -> Dict[str, Any]:
        if not tenant_id or not user_id or not agent_id:
            raise DreamingRunError("tenant_id, user_id and agent_id are required")
        if run_id is None:
            if trigger_source == "manual":
                run_id = memory_dreaming_db.create_audit(tenant_id, user_id, agent_id)
            else:
                run_id = memory_dreaming_db.create_audit(
                    tenant_id,
                    user_id,
                    agent_id,
                    trigger_source=trigger_source,
                )
        else:
            memory_dreaming_db.update_audit(
                run_id, {"status": "running", "current_phase": "light"}
            )
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
                user_thresholds = memory_dreaming_db.get_thresholds(
                    tenant_id, user_id, agent_id
                )
                effective_min_score = min_score
                effective_min_recall = min_recall_count
                effective_min_queries = min_unique_queries
                effective_source_limit = DREAMING_SOURCE_LIMIT
                effective_long_term_max_chars = DREAMING_LONG_TERM_MAX_CHARS
                effective_summarization_max_attempts = DREAMING_SUMMARIZATION_MAX_ATTEMPTS
                if user_thresholds:
                    if user_thresholds.get("min_score") is not None:
                        effective_min_score = user_thresholds["min_score"]
                    if user_thresholds.get("min_recall_count") is not None:
                        effective_min_recall = user_thresholds["min_recall_count"]
                    if user_thresholds.get("min_unique_queries") is not None:
                        effective_min_queries = user_thresholds["min_unique_queries"]
                    if user_thresholds.get("source_limit") is not None:
                        effective_source_limit = user_thresholds["source_limit"]
                    if user_thresholds.get("long_term_max_chars") is not None:
                        effective_long_term_max_chars = user_thresholds["long_term_max_chars"]
                    if user_thresholds.get("summarization_max_attempts") is not None:
                        effective_summarization_max_attempts = user_thresholds["summarization_max_attempts"]

                decisions = select_candidates(
                    candidates,
                    thresholds=DreamingThresholds(
                        min_score=effective_min_score,
                        min_recall_count=effective_min_recall,
                        min_unique_queries=effective_min_queries,
                    ),
                    recency_half_life_days=RECENCY_HALF_LIFE_DAYS,
                )
                memory_dreaming_db.update_audit(
                    run_id, {"current_phase": "summarization"}
                )
                config_snapshot = {
                    "window_days": window_days,
                    "min_score": effective_min_score,
                    "min_recall_count": effective_min_recall,
                    "min_unique_queries": effective_min_queries,
                    "source_limit": effective_source_limit,
                    "long_term_max_chars": effective_long_term_max_chars,
                    "summarization_max_attempts": effective_summarization_max_attempts,
                }
                # The model client owns request timeouts. Running the builder inline lets
                # its retry/fallback contract handle timeout exceptions and prevents an
                # uncancellable executor thread from outliving a completed audit.
                version = self._build_version(
                    tenant_id,
                    user_id,
                    agent_id,
                    run_id,
                    decisions,
                    config_snapshot,
                )
                results = [
                    {
                        "memory_id": decision.candidate.memory_id,
                        "score": decision.score,
                        "noise": decision.candidate.noise,
                        "signal_count": decision.metrics.signal_count,
                        "context_diversity": decision.metrics.context_diversity,
                        "evidence_ids": [str(decision.candidate.memory_id)],
                        "event": "SELECT" if decision.promote else "DEFER",
                        "reason": decision.reason,
                        "archive_suggested": decision.archive_suggested,
                    }
                    for decision in decisions
                ]
                promoted_count = sum(decision.promote for decision in decisions)
                result = {
                    "run_id": run_id,
                    "status": "completed",
                    "light_count": len(stats),
                    "rem_count": len(candidates),
                    "promoted_count": promoted_count,
                    "deferred_count": len(results) - promoted_count,
                    "decisions": results,
                    "version": version,
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
