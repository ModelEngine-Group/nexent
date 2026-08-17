"""Persistence for immutable tenant/user Markdown long-term memory versions."""

from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func

from .client import get_db_session
from .db_models import MemoryLongTermVersion


def _serialize(row: MemoryLongTermVersion, *, include_content: bool = True) -> Dict[str, Any]:
    authored_at = row.authored_at
    if authored_at is not None:
        if authored_at.tzinfo is None:
            authored_at = authored_at.replace(tzinfo=timezone.utc)
        else:
            authored_at = authored_at.astimezone(timezone.utc)
    value = {
        "version_id": row.version_id, "tenant_id": row.tenant_id, "scope": row.scope,
        "subject_id": row.subject_id, "version_no": row.version_no,
        "parent_version_id": row.parent_version_id, "is_active": row.is_active,
        "source": row.source, "author_user_id": row.author_user_id,
        "editor_user_id": row.editor_user_id,
        "authored_at": authored_at.isoformat().replace("+00:00", "Z") if authored_at else None,
        "dreaming_run_id": row.dreaming_run_id, "character_count": row.character_count,
        "generation_audit": row.generation_audit or {}, "evidence_ids": row.evidence_ids or [],
        "fallback_details": row.fallback_details or {}, "omission_details": row.omission_details or {},
    }
    if include_content:
        value.update(content=row.content, raw_dreaming_input=row.raw_dreaming_input)
    return value


def get_active(tenant_id: str, scope: str, subject_id: str) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        row = session.query(MemoryLongTermVersion).filter(
            MemoryLongTermVersion.tenant_id == tenant_id, MemoryLongTermVersion.scope == scope,
            MemoryLongTermVersion.subject_id == subject_id, MemoryLongTermVersion.is_active.is_(True),
            MemoryLongTermVersion.delete_flag == "N",
        ).first()
        return _serialize(row) if row else None


def get_version(tenant_id: str, scope: str, subject_id: str, version_id: int) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        row = session.query(MemoryLongTermVersion).filter(
            MemoryLongTermVersion.tenant_id == tenant_id, MemoryLongTermVersion.scope == scope,
            MemoryLongTermVersion.subject_id == subject_id, MemoryLongTermVersion.version_id == version_id,
            MemoryLongTermVersion.delete_flag == "N",
        ).first()
        return _serialize(row) if row else None


def list_versions(tenant_id: str, scope: str, subject_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        rows = session.query(MemoryLongTermVersion).filter(
            MemoryLongTermVersion.tenant_id == tenant_id, MemoryLongTermVersion.scope == scope,
            MemoryLongTermVersion.subject_id == subject_id, MemoryLongTermVersion.delete_flag == "N",
        ).order_by(MemoryLongTermVersion.version_no.desc()).limit(limit).all()
        return [_serialize(row, include_content=False) for row in rows]


def create_and_activate(*, tenant_id: str, scope: str, subject_id: str, content: str,
                        source: str, actor_user_id: str, expected_active_version_id: Optional[int],
                        dreaming_run_id: Optional[int] = None, raw_dreaming_input: Optional[str] = None,
                        generation_audit: Optional[Dict[str, Any]] = None,
                        evidence_ids: Optional[List[str]] = None,
                        fallback_details: Optional[Dict[str, Any]] = None,
                        omission_details: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Create an immutable child; return None when expected active is stale."""
    with get_db_session() as session:
        scope_filter = (MemoryLongTermVersion.tenant_id == tenant_id,
                        MemoryLongTermVersion.scope == scope,
                        MemoryLongTermVersion.subject_id == subject_id,
                        MemoryLongTermVersion.delete_flag == "N")
        current = session.query(MemoryLongTermVersion).filter(
            *scope_filter, MemoryLongTermVersion.is_active.is_(True)).with_for_update().first()
        current_id = int(current.version_id) if current else None
        if current_id != expected_active_version_id:
            return None
        if dreaming_run_id is not None:
            existing = session.query(MemoryLongTermVersion).filter(
                MemoryLongTermVersion.dreaming_run_id == dreaming_run_id).first()
            if existing:
                return _serialize(existing)
        version_no = int(session.query(func.coalesce(func.max(MemoryLongTermVersion.version_no), 0))
                         .filter(*scope_filter).scalar()) + 1
        if current:
            current.is_active = False
            session.flush()
        row = MemoryLongTermVersion(
            tenant_id=tenant_id, scope=scope, subject_id=subject_id, version_no=version_no,
            parent_version_id=current_id, is_active=True, content=content, source=source,
            author_user_id=actor_user_id, editor_user_id=actor_user_id,
            dreaming_run_id=dreaming_run_id, character_count=len(content),
            raw_dreaming_input=raw_dreaming_input, generation_audit=generation_audit or {},
            evidence_ids=evidence_ids or [], fallback_details=fallback_details or {},
            omission_details=omission_details or {}, created_by=actor_user_id, updated_by=actor_user_id,
        )
        session.add(row); session.flush()
        session.commit(); session.refresh(row)
        return _serialize(row)


def activate(tenant_id: str, scope: str, subject_id: str, version_id: int,
             actor_user_id: str, expected_active_version_id: Optional[int]) -> tuple[str, Optional[Dict[str, Any]]]:
    with get_db_session() as session:
        rows = session.query(MemoryLongTermVersion).filter(
            MemoryLongTermVersion.tenant_id == tenant_id, MemoryLongTermVersion.scope == scope,
            MemoryLongTermVersion.subject_id == subject_id, MemoryLongTermVersion.delete_flag == "N",
        ).with_for_update().all()
        target = next((row for row in rows if row.version_id == version_id), None)
        if target is None: return "not_found", None
        current = next((row for row in rows if row.is_active), None)
        current_id = int(current.version_id) if current else None
        if current_id != expected_active_version_id: return "conflict", None
        if current_id == version_id: return "ok", _serialize(target)
        if current:
            # The partial unique index permits only one active row per scope.
            # Flush the deactivation first; otherwise SQLAlchemy may batch both
            # updates with the activation first and transiently violate it.
            current.is_active = False
            session.flush()
        target.is_active = True; target.updated_by = actor_user_id
        session.commit(); session.refresh(target)
        return "ok", _serialize(target)
