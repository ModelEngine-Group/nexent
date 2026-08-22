"""Database access for durable knowledge-base file lifecycle records."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from sqlalchemy import text

from .client import as_dict, get_db_session
from .db_models import KnowledgeFileLifecycle


ACTIVE_STATUSES = (
    "UPLOADING",
    "UPLOADED",
    "PROCESSING",
    "FORWARDING",
    "FAILED",
    "COMPLETED",
)
HIDDEN_STATUSES = ("DELETE_REQUESTED", "DELETED")


def new_file_id() -> str:
    """Generate a stable, opaque file ID without exposing object paths."""
    return uuid4().hex


def create_file_record(
    *,
    file_id: Optional[str],
    tenant_id: str,
    knowledge_id: int,
    index_name: str,
    original_filename: str,
    bucket_name: Optional[str] = None,
    object_name: Optional[str] = None,
    file_size: Optional[int] = None,
    status: str = "UPLOADING",
    stage: str = "UPLOAD",
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Create one lifecycle record before an object upload starts."""
    row = KnowledgeFileLifecycle(
        file_id=file_id or new_file_id(),
        tenant_id=str(tenant_id),
        knowledge_id=int(knowledge_id),
        index_name=index_name,
        original_filename=original_filename or "",
        bucket_name=bucket_name,
        object_name=object_name,
        file_size=file_size,
        status=status,
        stage=stage,
        created_by=created_by,
        updated_by=created_by,
    )
    with get_db_session() as session:
        session.add(row)
        session.flush()
        return as_dict(row)


def get_file_record(
    *,
    file_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    index_name: Optional[str] = None,
    object_name: Optional[str] = None,
    include_hidden: bool = False,
) -> Optional[Dict[str, Any]]:
    """Find a lifecycle record by stable ID or legacy path identity."""
    if not file_id and not object_name:
        return None
    with get_db_session() as session:
        query = session.query(KnowledgeFileLifecycle)
        if file_id:
            query = query.filter(KnowledgeFileLifecycle.file_id == file_id)
        else:
            query = query.filter(KnowledgeFileLifecycle.object_name == object_name)
        if tenant_id is not None:
            query = query.filter(KnowledgeFileLifecycle.tenant_id == str(tenant_id))
        if index_name is not None:
            query = query.filter(KnowledgeFileLifecycle.index_name == index_name)
        if not include_hidden:
            query = query.filter(KnowledgeFileLifecycle.status.notin_(HIDDEN_STATUSES))
        row = query.order_by(KnowledgeFileLifecycle.update_time.desc()).first()
        return as_dict(row) if row is not None else None


def list_file_records(
    *,
    index_name: str,
    tenant_id: Optional[str] = None,
    include_hidden: bool = False,
) -> List[Dict[str, Any]]:
    """List lifecycle records for a knowledge base."""
    with get_db_session() as session:
        query = session.query(KnowledgeFileLifecycle).filter(
            KnowledgeFileLifecycle.index_name == index_name,
        )
        if tenant_id is not None:
            query = query.filter(KnowledgeFileLifecycle.tenant_id == str(tenant_id))
        if not include_hidden:
            query = query.filter(KnowledgeFileLifecycle.status.notin_(HIDDEN_STATUSES))
        return [as_dict(row) for row in query.order_by(KnowledgeFileLifecycle.create_time.asc()).all()]


def transition_file_record(
    file_id: str,
    *,
    status: Optional[str] = None,
    stage: Optional[str] = None,
    expected_statuses: Optional[Iterable[str]] = None,
    expected_version: Optional[int] = None,
    updated_by: Optional[str] = None,
    **fields: Any,
) -> Optional[Dict[str, Any]]:
    """Apply an optimistic-lock lifecycle update, returning None on a stale update."""
    allowed_fields = {
        "bucket_name",
        "object_name",
        "file_size",
        "uploaded_at",
        "completed_at",
        "process_task_id",
        "forward_task_id",
        "parent_task_id",
        "processing_attempt",
        "error_code",
        "error_message",
        "error_stage",
        "failed_at",
        "delete_requested_at",
        "deleted_at",
        "delete_requested_by",
        "storage_object_id",
    }
    with get_db_session() as session:
        query = session.query(KnowledgeFileLifecycle).filter(
            KnowledgeFileLifecycle.file_id == file_id,
        )
        if expected_statuses:
            query = query.filter(KnowledgeFileLifecycle.status.in_(tuple(expected_statuses)))
        if expected_version is not None:
            query = query.filter(KnowledgeFileLifecycle.version == expected_version)
        row = query.with_for_update().first()
        if row is None:
            return None
        if status is not None:
            row.status = status
        if stage is not None:
            row.stage = stage
        for key, value in fields.items():
            if key in allowed_fields:
                setattr(row, key, value)
        if updated_by is not None:
            row.updated_by = updated_by
        row.version = int(row.version or 0) + 1
        session.flush()
        return as_dict(row)


def create_delete_tombstone(
    *,
    tenant_id: str,
    knowledge_id: int,
    index_name: str,
    object_name: str,
    original_filename: str = "",
    file_id: Optional[str] = None,
    requested_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update a hidden tombstone for legacy paths."""
    existing = get_file_record(
        file_id=file_id,
        tenant_id=tenant_id,
        index_name=index_name,
        object_name=object_name,
        include_hidden=True,
    )
    if existing:
        updated = transition_file_record(
            existing["file_id"],
            status="DELETED",
            stage="DELETE",
            delete_requested_at=datetime.utcnow(),
            deleted_at=datetime.utcnow(),
            delete_requested_by=requested_by,
            updated_by=requested_by,
        )
        return updated or existing
    created = create_file_record(
        file_id=file_id,
        tenant_id=tenant_id,
        knowledge_id=knowledge_id,
        index_name=index_name,
        original_filename=original_filename,
        object_name=object_name,
        status="DELETED",
        stage="DELETE",
        created_by=requested_by,
    )
    return transition_file_record(
        created["file_id"],
        delete_requested_at=datetime.utcnow(),
        deleted_at=datetime.utcnow(),
        delete_requested_by=requested_by,
        updated_by=requested_by,
    ) or created


def cleanup_expired_file_records(
    *,
    retention_days: int = 30,
    batch_size: int = 500,
) -> int:
    """Delete completed cache rows and deletion tombstones after retention."""
    cutoff = datetime.utcnow() - timedelta(days=max(1, int(retention_days)))
    with get_db_session() as session:
        lock_result = session.execute(
            text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
            {"lock_key": 78231491},
        )
        if not bool(lock_result.scalar()):
            return 0
        rows = (
            session.query(KnowledgeFileLifecycle)
            .filter(
                KnowledgeFileLifecycle.status.in_(("COMPLETED", "DELETED")),
                KnowledgeFileLifecycle.update_time < cutoff,
            )
            .order_by(KnowledgeFileLifecycle.update_time.asc())
            .limit(max(1, int(batch_size)))
            .all()
        )
        for row in rows:
            session.delete(row)
        return len(rows)
