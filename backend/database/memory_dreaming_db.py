"""Persistence, scheduling, and PostgreSQL locking for Dreaming runs."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import func, text

from .client import get_db_session
from .db_models import (
    MemoryDreamingAudit,
    MemoryDreamingDecision,
    MemoryDreamingSchedule,
    MemoryLongTermVersion,
)
from nexent.scheduler import ScheduleMode, ScheduleRuleType
from services.agent_automation.models import ScheduleTrigger
from services.agent_automation.schedule_engine import compute_next_fire_at


def advisory_lock_key(tenant_id: str, user_id: str, agent_id: str) -> int:
    digest = hashlib.sha256(
        f"{tenant_id}:{user_id}:{agent_id}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@contextmanager
def try_scope_lock(tenant_id: str, user_id: str, agent_id: str) -> Iterator[bool]:
    """Hold a transaction-scoped advisory lock for the context lifetime."""
    with get_db_session() as session:
        acquired = bool(
            session.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                {"lock_key": advisory_lock_key(tenant_id, user_id, agent_id)},
            ).scalar()
        )
        try:
            yield acquired
            session.commit()
        except Exception:
            session.rollback()
            raise


def create_audit(
    tenant_id: str,
    user_id: str,
    agent_id: str,
    *,
    trigger_source: str = "manual",
    status: str = "running",
) -> int:
    with get_db_session() as session:
        row = MemoryDreamingAudit(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            trigger_source=trigger_source,
            status=status,
            current_phase=None if status == "queued" else "light",
        )
        session.add(row)
        session.commit()
        return int(row.run_id)


def _schedule_to_dict(row: MemoryDreamingSchedule) -> Dict[str, Any]:
    return {
        "schedule_id": row.schedule_id,
        "agent_id": row.agent_id,
        "enabled": row.enabled,
        "rule_type": row.rule_type,
        "timezone": row.timezone,
        "start_at": row.start_at.isoformat() if row.start_at else None,
        "cron_expr": row.cron_expr,
        "interval_seconds": row.interval_seconds,
        "next_fire_at": (
            row.next_fire_at.replace(tzinfo=timezone.utc).isoformat()
            if row.next_fire_at
            else None
        ),
        "last_fire_at": (
            row.last_fire_at.replace(tzinfo=timezone.utc).isoformat()
            if row.last_fire_at
            else None
        ),
        "fire_count": row.fire_count,
        "min_score": row.min_score,
        "min_recall_count": row.min_recall_count,
        "min_unique_queries": row.min_unique_queries,
        "source_limit": row.source_limit,
        "long_term_max_chars": row.long_term_max_chars,
        "summarization_max_attempts": row.summarization_max_attempts,
    }


def get_schedule(
    tenant_id: str, user_id: str, agent_id: str
) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        row = (
            session.query(MemoryDreamingSchedule)
            .filter(
                MemoryDreamingSchedule.tenant_id == tenant_id,
                MemoryDreamingSchedule.user_id == user_id,
                MemoryDreamingSchedule.agent_id == agent_id,
                MemoryDreamingSchedule.delete_flag == "N",
            )
            .first()
        )
        return _schedule_to_dict(row) if row else None


def upsert_schedule(
    tenant_id: str,
    user_id: str,
    agent_id: str,
    *,
    enabled: bool,
    rule_type: str,
    timezone_name: str,
    start_at: datetime,
    cron_expr: Optional[str],
    interval_seconds: Optional[int],
    next_fire_at: Optional[datetime],
    actor_user_id: str,
    min_score: Optional[float] = None,
    min_recall_count: Optional[int] = None,
    min_unique_queries: Optional[int] = None,
    source_limit: Optional[int] = None,
    long_term_max_chars: Optional[int] = None,
    summarization_max_attempts: Optional[int] = None,
) -> Dict[str, Any]:
    with get_db_session() as session:
        row = (
            session.query(MemoryDreamingSchedule)
            .filter(
                MemoryDreamingSchedule.tenant_id == tenant_id,
                MemoryDreamingSchedule.user_id == user_id,
                MemoryDreamingSchedule.agent_id == agent_id,
            )
            .with_for_update()
            .first()
        )
        if row is not None and row.delete_flag == "Y":
            session.delete(row)
            session.flush()
            row = None
        if row is None:
            row = MemoryDreamingSchedule(
                tenant_id=tenant_id,
                user_id=user_id,
                agent_id=agent_id,
                created_by=actor_user_id,
            )
            session.add(row)
        row.enabled = enabled
        row.rule_type = rule_type
        row.timezone = timezone_name
        row.start_at = start_at
        row.cron_expr = cron_expr
        row.interval_seconds = interval_seconds
        row.next_fire_at = next_fire_at if enabled else None
        row.min_score = min_score
        row.min_recall_count = min_recall_count
        row.min_unique_queries = min_unique_queries
        row.source_limit = source_limit
        row.long_term_max_chars = long_term_max_chars
        row.summarization_max_attempts = summarization_max_attempts
        row.updated_by = actor_user_id
        session.flush()
        return _schedule_to_dict(row)


def get_thresholds(
    tenant_id: str, user_id: str, agent_id: str
) -> Optional[Dict[str, Any]]:
    """Return per-user threshold overrides, or None if not configured."""
    with get_db_session() as session:
        row = (
            session.query(
                MemoryDreamingSchedule.min_score,
                MemoryDreamingSchedule.min_recall_count,
                MemoryDreamingSchedule.min_unique_queries,
                MemoryDreamingSchedule.source_limit,
                MemoryDreamingSchedule.long_term_max_chars,
                MemoryDreamingSchedule.summarization_max_attempts,
            )
            .filter(
                MemoryDreamingSchedule.tenant_id == tenant_id,
                MemoryDreamingSchedule.user_id == user_id,
                MemoryDreamingSchedule.agent_id == agent_id,
                MemoryDreamingSchedule.delete_flag == "N",
            )
            .first()
        )
        if row is None:
            return None
        result = {
            "min_score": row.min_score,
            "min_recall_count": row.min_recall_count,
            "min_unique_queries": row.min_unique_queries,
            "source_limit": row.source_limit,
            "long_term_max_chars": row.long_term_max_chars,
            "summarization_max_attempts": row.summarization_max_attempts,
        }
        # Return None if ALL thresholds are unset
        if all(v is None for v in result.values()):
            return None
        return result


def _next_schedule_fire(row: MemoryDreamingSchedule, after: datetime) -> Optional[datetime]:
    spec = ScheduleTrigger(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType(row.rule_type),
        timezone=row.timezone,
        start_at=row.start_at,
        cron_expr=row.cron_expr,
        interval_seconds=row.interval_seconds,
    )
    value = compute_next_fire_at(
        spec, after.replace(tzinfo=timezone.utc), row.fire_count + 1
    )
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value else None


def materialize_due_schedules(limit: int = 10) -> int:
    """Atomically enqueue due schedules and advance them exactly once."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    created = 0
    with get_db_session() as session:
        rows = (
            session.query(MemoryDreamingSchedule)
            .filter(
                MemoryDreamingSchedule.enabled.is_(True),
                MemoryDreamingSchedule.next_fire_at <= now,
                MemoryDreamingSchedule.delete_flag == "N",
            )
            .order_by(MemoryDreamingSchedule.next_fire_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
            .all()
        )
        for row in rows:
            scheduled_fire_at = row.next_fire_at
            active = (
                session.query(MemoryDreamingAudit.run_id)
                .filter(
                    MemoryDreamingAudit.tenant_id == row.tenant_id,
                    MemoryDreamingAudit.user_id == row.user_id,
                    MemoryDreamingAudit.agent_id == row.agent_id,
                    MemoryDreamingAudit.status.in_(("queued", "running")),
                    MemoryDreamingAudit.delete_flag == "N",
                )
                .first()
            )
            if active is None:
                session.add(
                    MemoryDreamingAudit(
                        tenant_id=row.tenant_id,
                        user_id=row.user_id,
                        agent_id=row.agent_id,
                        trigger_source="schedule",
                        status="queued",
                    )
                )
                created += 1
            row.last_fire_at = scheduled_fire_at
            row.fire_count += 1
            row.next_fire_at = _next_schedule_fire(row, now)
    return created



def update_audit(run_id: int, values: Dict[str, Any]) -> bool:
    allowed = {
        "status",
        "current_phase",
        "finished_at",
        "light_count",
        "rem_count",
        "promoted_count",
        "deferred_count",
        "published_version_id",
        "reason",
        "error",
    }
    with get_db_session() as session:
        decisions = values.get("decisions")
        row = (
            session.query(MemoryDreamingAudit)
            .filter(MemoryDreamingAudit.run_id == run_id)
            .first()
        )
        if row is None:
            return False
        if decisions is not None:
            session.query(MemoryDreamingDecision).filter(
                MemoryDreamingDecision.run_id == run_id
            ).delete(synchronize_session=False)
            session.add_all(
                MemoryDreamingDecision(
                    run_id=run_id,
                    decision_order=decision_order,
                    memory_id=decision["memory_id"],
                    score=decision["score"],
                    noise=decision.get("noise", False),
                    signal_count=decision.get("signal_count", 0),
                    context_diversity=decision.get("context_diversity", 0),
                    evidence_ids=decision.get("evidence_ids", []),
                    event=decision["event"],
                    reason=decision["reason"],
                    archive_suggested=decision.get("archive_suggested", False),
                )
                for decision_order, decision in enumerate(decisions)
            )
        for key, value in values.items():
            if key in allowed:
                setattr(row, key, value)
        session.commit()
        return True


def finish_audit(run_id: int, *, status: str, **values: Any) -> bool:
    payload = {
        **values,
        "status": status,
        "finished_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }
    if status != "failed":
        payload["current_phase"] = None
    return update_audit(run_id, payload)


def _utc_isoformat(value: Optional[datetime]) -> Optional[str]:
    """Serialize UTC values stored in timestamp-without-time-zone columns unambiguously."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def list_audits(
    tenant_id: str,
    user_id: str,
    *,
    agent_id: Optional[str] = None,
    run_id: Optional[int] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        query = session.query(MemoryDreamingAudit).filter(
            MemoryDreamingAudit.tenant_id == tenant_id,
            MemoryDreamingAudit.user_id == user_id,
            MemoryDreamingAudit.delete_flag == "N",
        )
        if agent_id is not None:
            query = query.filter(MemoryDreamingAudit.agent_id == agent_id)
        if run_id is not None:
            query = query.filter(MemoryDreamingAudit.run_id == run_id)
        rows = query.order_by(MemoryDreamingAudit.run_id.desc()).limit(limit).all()
        run_ids = [row.run_id for row in rows]
        decision_rows = []
        if run_ids:
            decision_rows = (
                session.query(MemoryDreamingDecision)
                .filter(MemoryDreamingDecision.run_id.in_(run_ids))
                .order_by(
                    MemoryDreamingDecision.run_id,
                    MemoryDreamingDecision.decision_order,
                )
                .all()
            )
        decisions_by_run: Dict[int, List[Dict[str, Any]]] = {
            run_id: [] for run_id in run_ids
        }
        for decision in decision_rows:
            decisions_by_run[decision.run_id].append(
                {
                    "memory_id": decision.memory_id,
                    "score": decision.score,
                    "noise": decision.noise,
                    "signal_count": decision.signal_count,
                    "context_diversity": decision.context_diversity,
                    "evidence_ids": decision.evidence_ids,
                    "event": decision.event,
                    "reason": decision.reason,
                    "archive_suggested": decision.archive_suggested,
                }
            )
        return [
            {
                "run_id": row.run_id,
                "tenant_id": row.tenant_id,
                "user_id": row.user_id,
                "agent_id": row.agent_id,
                "trigger_source": row.trigger_source,
                "status": row.status,
                "current_phase": row.current_phase,
                "started_at": _utc_isoformat(row.started_at),
                "finished_at": _utc_isoformat(row.finished_at),
                "light_count": row.light_count,
                "rem_count": row.rem_count,
                "promoted_count": row.promoted_count,
                "deferred_count": row.deferred_count,
                "decisions": decisions_by_run[row.run_id],
                "published_version_id": row.published_version_id,
                "reason": row.reason,
                "error": row.error,
            }
            for row in rows
        ]


# ---------------------------------------------------------------------------
# Worker lease management
# ---------------------------------------------------------------------------


def claim_queued(owner_id: str, lease_seconds: float) -> Optional[Dict[str, Any]]:
    """Atomically claim the oldest queued audit row and set a lease.

    Uses FOR UPDATE SKIP LOCKED so concurrent workers never block each other.
    Returns the payload the executor needs (run_id, tenant_id, user_id,
    agent_id, trigger_source) or None when no row is available.
    """
    sql = text("""
        WITH candidate AS (
            SELECT run_id
            FROM nexent.memory_dreaming_audit_t
            WHERE status = 'queued'
              AND delete_flag = 'N'
            ORDER BY started_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        UPDATE nexent.memory_dreaming_audit_t AS audit
        SET lock_owner = :owner_id,
            lock_until = now() + (:lease_seconds * interval '1 second'),
            status = 'running',
            current_phase = 'light',
            update_time = now()
        FROM candidate
        WHERE audit.run_id = candidate.run_id
        RETURNING audit.run_id,
                  audit.tenant_id,
                  audit.user_id,
                  audit.agent_id,
                  audit.trigger_source
    """)
    with get_db_session() as session:
        row = session.execute(sql, {
            "owner_id": owner_id,
            "lease_seconds": lease_seconds,
        }).fetchone()
        if row is None:
            return None
        return dict(row._mapping)


def renew_lease(run_id: int, owner_id: str, lease_seconds: float) -> bool:
    """Extend the lease only when the caller still owns it and it has not expired."""
    sql = text("""
        UPDATE nexent.memory_dreaming_audit_t
        SET lock_until = now() + (:lease_seconds * interval '1 second'),
            update_time = now()
        WHERE run_id = :run_id
          AND lock_owner = :owner_id
          AND lock_until > now()
          AND delete_flag = 'N'
        RETURNING run_id
    """)
    with get_db_session() as session:
        renewed = session.execute(sql, {
            "run_id": run_id,
            "owner_id": owner_id,
            "lease_seconds": lease_seconds,
        }).scalar_one_or_none()
        return renewed is not None


def release_lease(run_id: int, owner_id: str) -> bool:
    """Clear the lease fields only when the caller owns the lock."""
    sql = text("""
        UPDATE nexent.memory_dreaming_audit_t
        SET lock_owner = NULL,
            lock_until = NULL,
            update_time = now()
        WHERE run_id = :run_id
          AND lock_owner = :owner_id
          AND delete_flag = 'N'
        RETURNING run_id
    """)
    with get_db_session() as session:
        released = session.execute(sql, {
            "run_id": run_id,
            "owner_id": owner_id,
        }).scalar_one_or_none()
        return released is not None


def recover_stale(include_unexpired: bool = False) -> int:
    """Reap runs whose lease expired without completion.

    Marks them as failed and clears lock fields so they can be retried.
    ``include_unexpired`` is used by the single-replica startup path, where all
    RUNNING rows necessarily belong to the previous process.
    """
    lease_filter = "" if include_unexpired else "AND lock_until < now()"
    sql = text("""
        UPDATE nexent.memory_dreaming_audit_t
        SET status = 'failed',
            error = 'Worker lost — reaped by startup recovery',
            lock_owner = NULL,
            lock_until = NULL,
            finished_at = now(),
            update_time = now()
        WHERE status = 'running'
          {lease_filter}
          AND delete_flag = 'N'
    """.format(lease_filter=lease_filter))
    with get_db_session() as session:
        result = session.execute(sql)
        return result.rowcount or 0


def delete_user_dreaming_history(tenant_id: str, user_id: str) -> None:
    """Remove Dreaming state while preserving and restoring manual memory."""
    with get_db_session() as session:
        session.query(MemoryDreamingSchedule).filter(
            MemoryDreamingSchedule.tenant_id == tenant_id,
            MemoryDreamingSchedule.user_id == user_id,
        ).delete(synchronize_session=False)
        session.query(MemoryDreamingAudit).filter(
            MemoryDreamingAudit.tenant_id == tenant_id,
            MemoryDreamingAudit.user_id == user_id,
        ).delete(synchronize_session=False)
        versions = session.query(MemoryLongTermVersion).filter(
            MemoryLongTermVersion.tenant_id == tenant_id,
            MemoryLongTermVersion.scope == "user",
            MemoryLongTermVersion.subject_id == user_id,
            MemoryLongTermVersion.delete_flag == "N",
        ).with_for_update().all()
        active = next((version for version in versions if version.is_active), None)
        dreamed = [version for version in versions if version.source == "dreaming"]
        for version in dreamed:
            version.is_active = False
            version.delete_flag = "Y"
            version.updated_by = user_id
        if active in dreamed:
            session.flush()
            manual = max(
                (version for version in versions if version.source == "manual"),
                key=lambda version: version.version_no,
                default=None,
            )
            if manual is not None:
                manual.is_active = True
                manual.updated_by = user_id
