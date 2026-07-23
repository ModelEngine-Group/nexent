"""Persistence and PostgreSQL advisory locking for manual Dreaming runs."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import text

from .client import get_db_session
from .db_models import MemoryDreamingAudit


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


def create_audit(tenant_id: str, user_id: str, agent_id: str) -> int:
    with get_db_session() as session:
        row = MemoryDreamingAudit(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            trigger_source="manual",
            status="running",
            current_phase="light",
        )
        session.add(row)
        session.commit()
        return int(row.run_id)


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
        "finished_at": datetime.utcnow(),
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
