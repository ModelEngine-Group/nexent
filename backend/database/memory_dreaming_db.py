"""Persistence and PostgreSQL advisory locking for manual Dreaming runs."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import func, text

from .client import get_db_session
from .db_models import (
    MemoryDreamingActivationAudit,
    MemoryDreamingAudit,
    MemoryDreamingVersion,
)


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


def get_active_version(
    tenant_id: str, user_id: str, agent_id: str
) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        row = (
            session.query(MemoryDreamingVersion)
            .filter(
                MemoryDreamingVersion.tenant_id == tenant_id,
                MemoryDreamingVersion.user_id == user_id,
                MemoryDreamingVersion.agent_id == agent_id,
                MemoryDreamingVersion.is_active.is_(True),
                MemoryDreamingVersion.delete_flag == "N",
            )
            .first()
        )
        return _version_to_dict(row) if row else None


def create_and_activate_version(
    *,
    tenant_id: str,
    user_id: str,
    agent_id: str,
    run_id: int,
    parent_version_id: Optional[int],
    raw_content: str,
    published_content: str,
    published_units: List[Dict[str, Any]],
    source_evidence_ids: List[str],
    config_snapshot: Dict[str, Any],
    raw_char_count: int,
    published_char_count: int,
    compression_status: str,
    compression_attempts: int,
    omitted_evidence_ids: List[str],
    mechanical_truncation: bool,
    compression_audit: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Atomically append and activate a version for one locked scope."""
    with get_db_session() as session:
        existing = (
            session.query(MemoryDreamingVersion)
            .filter(
                MemoryDreamingVersion.run_id == run_id,
                MemoryDreamingVersion.tenant_id == tenant_id,
                MemoryDreamingVersion.user_id == user_id,
                MemoryDreamingVersion.agent_id == agent_id,
                MemoryDreamingVersion.delete_flag == "N",
            )
            .first()
        )
        if existing is not None:
            return _version_to_dict(existing)
        scope = (
            MemoryDreamingVersion.tenant_id == tenant_id,
            MemoryDreamingVersion.user_id == user_id,
            MemoryDreamingVersion.agent_id == agent_id,
            MemoryDreamingVersion.delete_flag == "N",
        )
        next_version = (
            session.query(func.coalesce(func.max(MemoryDreamingVersion.version_no), 0))
            .filter(*scope)
            .scalar()
            + 1
        )
        session.query(MemoryDreamingVersion).filter(
            *scope, MemoryDreamingVersion.is_active.is_(True)
        ).update({"is_active": False}, synchronize_session=False)
        row = MemoryDreamingVersion(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            version_no=next_version,
            parent_version_id=parent_version_id,
            run_id=run_id,
            is_active=True,
            raw_content=raw_content,
            published_content=published_content,
            published_units=published_units,
            source_evidence_ids=source_evidence_ids,
            config_snapshot=config_snapshot,
            raw_char_count=raw_char_count,
            published_char_count=published_char_count,
            compression_status=compression_status,
            compression_attempts=compression_attempts,
            omitted_evidence_ids=omitted_evidence_ids,
            mechanical_truncation=mechanical_truncation,
            compression_audit=compression_audit,
            created_by="dreaming",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _version_to_dict(row)


def list_versions(
    tenant_id: str,
    user_id: str,
    *,
    agent_id: str,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        rows = (
            session.query(MemoryDreamingVersion)
            .filter(
                MemoryDreamingVersion.tenant_id == tenant_id,
                MemoryDreamingVersion.user_id == user_id,
                MemoryDreamingVersion.agent_id == agent_id,
                MemoryDreamingVersion.delete_flag == "N",
            )
            .order_by(MemoryDreamingVersion.version_no.desc())
            .limit(limit)
            .all()
        )
        return [_version_to_dict(row) for row in rows]


def activate_version(
    tenant_id: str,
    user_id: str,
    agent_id: str,
    version_id: int,
    *,
    actor_user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Switch the active pointer without modifying immutable version content."""
    with get_db_session() as session:
        rows = (
            session.query(MemoryDreamingVersion)
            .filter(
                MemoryDreamingVersion.tenant_id == tenant_id,
                MemoryDreamingVersion.user_id == user_id,
                MemoryDreamingVersion.agent_id == agent_id,
                MemoryDreamingVersion.delete_flag == "N",
            )
            .all()
        )
        target = next((row for row in rows if row.version_id == version_id), None)
        if target is None:
            return None
        current = next((row for row in rows if row.is_active), None)
        if current is not None and current.version_id == version_id:
            return _version_to_dict(target)
        actor = actor_user_id or user_id
        session.query(MemoryDreamingVersion).filter(
            MemoryDreamingVersion.tenant_id == tenant_id,
            MemoryDreamingVersion.user_id == user_id,
            MemoryDreamingVersion.agent_id == agent_id,
            MemoryDreamingVersion.delete_flag == "N",
            MemoryDreamingVersion.is_active.is_(True),
        ).update(
            {"is_active": False, "updated_by": actor},
            synchronize_session=False,
        )
        session.flush()
        target.is_active = True
        target.updated_by = actor
        session.add(
            MemoryDreamingActivationAudit(
                tenant_id=tenant_id,
                user_id=user_id,
                agent_id=agent_id,
                actor_user_id=actor,
                from_version_id=current.version_id if current else None,
                to_version_id=version_id,
                reason="user_switch",
                created_by=actor,
            )
        )
        session.commit()
        session.refresh(target)
        return _version_to_dict(target)


def _version_to_dict(row: MemoryDreamingVersion) -> Dict[str, Any]:
    return {
        "version_id": row.version_id,
        "tenant_id": row.tenant_id,
        "user_id": row.user_id,
        "agent_id": row.agent_id,
        "version_no": row.version_no,
        "parent_version_id": row.parent_version_id,
        "run_id": row.run_id,
        "is_active": row.is_active,
        "raw_content": row.raw_content,
        "published_content": row.published_content,
        "published_units": row.published_units or [],
        "source_evidence_ids": row.source_evidence_ids or [],
        "config_snapshot": row.config_snapshot or {},
        "raw_char_count": row.raw_char_count,
        "published_char_count": row.published_char_count,
        "compression_status": row.compression_status,
        "compression_attempts": row.compression_attempts,
        "omitted_evidence_ids": row.omitted_evidence_ids or [],
        "mechanical_truncation": row.mechanical_truncation,
        "compression_audit": row.compression_audit or [],
        "created_at": row.create_time.isoformat() if row.create_time else None,
    }


def update_audit(run_id: int, values: Dict[str, Any]) -> bool:
    allowed = {
        "status",
        "current_phase",
        "finished_at",
        "light_count",
        "rem_count",
        "promoted_count",
        "deferred_count",
        "result_json",
        "error",
    }
    with get_db_session() as session:
        row = (
            session.query(MemoryDreamingAudit)
            .filter(MemoryDreamingAudit.run_id == run_id)
            .first()
        )
        if row is None:
            return False
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
        return [
            {
                "run_id": row.run_id,
                "tenant_id": row.tenant_id,
                "user_id": row.user_id,
                "agent_id": row.agent_id,
                "trigger_source": row.trigger_source,
                "status": row.status,
                "current_phase": row.current_phase,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "light_count": row.light_count,
                "rem_count": row.rem_count,
                "promoted_count": row.promoted_count,
                "deferred_count": row.deferred_count,
                "result": row.result_json,
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


def recover_stale() -> int:
    """Reap runs whose lease expired without completion.

    Marks them as failed and clears lock fields so they can be retried.
    Safe to call on every worker startup.
    """
    sql = text("""
        UPDATE nexent.memory_dreaming_audit_t
        SET status = 'failed',
            error = 'Worker lost — reaped by startup recovery',
            lock_owner = NULL,
            lock_until = NULL,
            finished_at = now(),
            update_time = now()
        WHERE status = 'running'
          AND lock_until < now()
          AND delete_flag = 'N'
    """)
    with get_db_session() as session:
        result = session.execute(sql)
        return result.rowcount or 0
