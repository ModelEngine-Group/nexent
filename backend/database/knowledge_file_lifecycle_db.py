"""Database access for durable knowledge-base file lifecycle records."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

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
    """Create one lifecycle record before upload; filename may later be made unique."""
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


def create_file_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create a batch of lifecycle records in one transaction.

    The upload workflow must not persist a partial batch.  Keeping the whole
    insert in one session means a constraint or database failure rolls back
    every row before any object is written to MinIO.
    """
    rows = []
    for record in records:
        rows.append(
            KnowledgeFileLifecycle(
                file_id=record.get("file_id") or new_file_id(),
                tenant_id=str(record["tenant_id"]),
                knowledge_id=int(record["knowledge_id"]),
                index_name=record["index_name"],
                original_filename=record.get("original_filename") or "",
                bucket_name=record.get("bucket_name"),
                object_name=record.get("object_name"),
                file_size=record.get("file_size"),
                status=record.get("status", "UPLOADING"),
                stage=record.get("stage", "UPLOAD"),
                created_by=record.get("created_by"),
                updated_by=record.get("updated_by", record.get("created_by")),
            )
        )

    if not rows:
        return []

    with get_db_session() as session:
        session.add_all(rows)
        session.flush()
        return [as_dict(row) for row in rows]


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
        "original_filename",
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
        "deleted_at",
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


def delete_file_record(
    file_id: str,
    *,
    expected_statuses: Optional[Iterable[str]] = None,
) -> bool:
    """Physically delete a lifecycle row, returning whether a row was removed.

    Deletion is idempotent: a concurrent request may remove the row first, in
    which case ``False`` is returned and the caller can treat it as already
    deleted.  Status filtering prevents a stale cleanup callback from
    deleting a newly active row that reuses an object identity.
    """
    with get_db_session() as session:
        query = session.query(KnowledgeFileLifecycle).filter(
            KnowledgeFileLifecycle.file_id == file_id,
        )
        if expected_statuses:
            query = query.filter(KnowledgeFileLifecycle.status.in_(tuple(expected_statuses)))
        return bool(query.delete(synchronize_session=False))


def delete_file_records_for_knowledge_base(
    *,
    index_name: str,
    tenant_id: Optional[str] = None,
    knowledge_id: Optional[int] = None,
) -> int:
    """Hard-delete lifecycle rows eligible after knowledge-base deletion.

    Knowledge-base deletion is guarded before this helper is called, so rows
    that are still being uploaded or processed are not removed. Keeping the
    status predicate here also protects against a new upload racing with the
    guard query.
    """
    deletable_statuses = (
        "FAILED",
        "COMPLETED",
        "DELETE_REQUESTED",
        "DELETED",
    )
    with get_db_session() as session:
        query = session.query(KnowledgeFileLifecycle).filter(
            KnowledgeFileLifecycle.index_name == index_name,
            KnowledgeFileLifecycle.status.in_(deletable_statuses),
        )
        if tenant_id is not None:
            query = query.filter(KnowledgeFileLifecycle.tenant_id == str(tenant_id))
        if knowledge_id is not None:
            query = query.filter(KnowledgeFileLifecycle.knowledge_id == int(knowledge_id))
        return int(query.delete(synchronize_session=False) or 0)


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
        if str(existing.get("status") or "").upper() == "DELETED":
            return existing
        updated = transition_file_record(
            existing["file_id"],
            status="DELETE_REQUESTED",
            stage="DELETE",
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
        status="DELETE_REQUESTED",
        stage="DELETE",
        created_by=requested_by,
    )
    return transition_file_record(
        created["file_id"],
        updated_by=requested_by,
    ) or created
