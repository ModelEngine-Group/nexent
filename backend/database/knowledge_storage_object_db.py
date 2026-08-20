"""Database access for the knowledge-base source-object storage ledger."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .client import as_dict, get_db_session
from .db_models import KnowledgeStorageObject


COMMITTED_STATUS = "COMMITTED"
DELETED_STATUS = "DELETED"


class StorageObjectConflictError(ValueError):
    """Raised when an object identity is already bound to different accounting data."""


def _validate_commit_input(
    tenant_id: str,
    knowledge_id: int,
    index_name: str,
    bucket_name: str,
    object_name: str,
    raw_bytes: int,
) -> None:
    required_strings = {
        "tenant_id": tenant_id,
        "index_name": index_name,
        "bucket_name": bucket_name,
        "object_name": object_name,
    }
    for field_name, value in required_strings.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")
    if not isinstance(knowledge_id, int) or isinstance(knowledge_id, bool):
        raise ValueError("knowledge_id must be an integer")
    _validate_raw_bytes(raw_bytes)


def _validate_raw_bytes(raw_bytes: int) -> None:
    if not isinstance(raw_bytes, int) or isinstance(raw_bytes, bool) or raw_bytes < 0:
        raise ValueError("raw_bytes must be a non-negative integer")


def _find_by_identity(session: Any, bucket_name: str, object_name: str) -> Optional[KnowledgeStorageObject]:
    return (
        session.query(KnowledgeStorageObject)
        .filter(
            KnowledgeStorageObject.bucket_name == bucket_name,
            KnowledgeStorageObject.object_name == object_name,
        )
        .first()
    )


def _resolve_idempotent_commit(
    existing: KnowledgeStorageObject,
    tenant_id: str,
    knowledge_id: int,
    index_name: str,
    raw_bytes: int,
) -> Dict[str, Any]:
    expected = (tenant_id, knowledge_id, index_name, raw_bytes)
    actual = (
        existing.tenant_id,
        existing.knowledge_id,
        existing.index_name,
        existing.raw_bytes,
    )
    if actual != expected:
        raise StorageObjectConflictError(
            "storage object identity is already bound to different ownership or size"
        )
    return as_dict(existing)


def commit_storage_object(
    tenant_id: str,
    knowledge_id: int,
    index_name: str,
    bucket_name: str,
    object_name: str,
    raw_bytes: int,
    created_by: Optional[str] = None,
    updated_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Commit one retained KB source object, idempotently by object identity.

    A replay with the same tenant, KB, index, and byte size returns the existing
    row without creating another charge. Reusing the object identity for any
    different ownership or size raises ``StorageObjectConflictError``.
    """
    _validate_commit_input(
        tenant_id,
        knowledge_id,
        index_name,
        bucket_name,
        object_name,
        raw_bytes,
    )
    effective_updated_by = updated_by if updated_by is not None else created_by

    try:
        with get_db_session() as session:
            existing = _find_by_identity(session, bucket_name, object_name)
            if existing is not None:
                return _resolve_idempotent_commit(
                    existing,
                    tenant_id,
                    knowledge_id,
                    index_name,
                    raw_bytes,
                )

            row = KnowledgeStorageObject(
                tenant_id=tenant_id,
                knowledge_id=knowledge_id,
                index_name=index_name,
                bucket_name=bucket_name,
                object_name=object_name,
                raw_bytes=raw_bytes,
                status=COMMITTED_STATUS,
                delete_flag="N",
                created_by=created_by,
                updated_by=effective_updated_by,
            )
            session.add(row)
            session.flush()
            return as_dict(row)
    except IntegrityError:
        # A concurrent insert can win after the initial lookup. Resolve the
        # resulting unique-key race using the same idempotency rules.
        with get_db_session() as session:
            existing = _find_by_identity(session, bucket_name, object_name)
            if existing is None:
                raise
            return _resolve_idempotent_commit(
                existing,
                tenant_id,
                knowledge_id,
                index_name,
                raw_bytes,
            )


def get_storage_object(
    tenant_id: str,
    bucket_name: str,
    object_name: str,
    *,
    include_deleted: bool = False,
) -> Optional[Dict[str, Any]]:
    """Return one tenant-owned ledger row without exposing another tenant's row."""
    with get_db_session() as session:
        query = session.query(KnowledgeStorageObject).filter(
            KnowledgeStorageObject.tenant_id == tenant_id,
            KnowledgeStorageObject.bucket_name == bucket_name,
            KnowledgeStorageObject.object_name == object_name,
        )
        if not include_deleted:
            query = query.filter(
                KnowledgeStorageObject.delete_flag == "N",
                KnowledgeStorageObject.status == COMMITTED_STATUS,
            )
        row = query.first()
        return as_dict(row) if row is not None else None


def aggregate_committed_bytes_by_kb(
    tenant_id: str,
    knowledge_ids: Optional[Sequence[int]] = None,
) -> Dict[int, int]:
    """Aggregate active committed source bytes by KB for one tenant."""
    if knowledge_ids is not None and not knowledge_ids:
        return {}

    with get_db_session() as session:
        query = session.query(
            KnowledgeStorageObject.knowledge_id,
            func.sum(KnowledgeStorageObject.raw_bytes).label("committed_bytes"),
        ).filter(
            KnowledgeStorageObject.tenant_id == tenant_id,
            KnowledgeStorageObject.delete_flag == "N",
            KnowledgeStorageObject.status == COMMITTED_STATUS,
        )
        if knowledge_ids is not None:
            query = query.filter(KnowledgeStorageObject.knowledge_id.in_(knowledge_ids))
        rows = query.group_by(KnowledgeStorageObject.knowledge_id).all()
        return {
            int(knowledge_id): int(committed_bytes or 0)
            for knowledge_id, committed_bytes in rows
        }


def get_tenant_committed_bytes(tenant_id: str) -> int:
    """Return the active committed source bytes attributed to one tenant."""
    with get_db_session() as session:
        total = (
            session.query(func.coalesce(func.sum(KnowledgeStorageObject.raw_bytes), 0))
            .filter(
                KnowledgeStorageObject.tenant_id == tenant_id,
                KnowledgeStorageObject.delete_flag == "N",
                KnowledgeStorageObject.status == COMMITTED_STATUS,
            )
            .scalar()
        )
        return int(total or 0)


def list_committed_storage_objects(
    tenant_id: str,
    knowledge_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """List active committed source objects for one tenant and optional KB."""
    with get_db_session() as session:
        query = session.query(KnowledgeStorageObject).filter(
            KnowledgeStorageObject.tenant_id == tenant_id,
            KnowledgeStorageObject.delete_flag == "N",
            KnowledgeStorageObject.status == COMMITTED_STATUS,
        )
        if knowledge_id is not None:
            query = query.filter(KnowledgeStorageObject.knowledge_id == knowledge_id)
        rows = query.order_by(KnowledgeStorageObject.storage_object_id.asc()).all()
        return [as_dict(row) for row in rows]


def mark_storage_object_deleted(
    tenant_id: str,
    bucket_name: str,
    object_name: str,
    updated_by: Optional[str] = None,
) -> bool:
    """Soft-delete one tenant-owned object charge after physical deletion."""
    with get_db_session() as session:
        row = (
            session.query(KnowledgeStorageObject)
            .filter(
                KnowledgeStorageObject.tenant_id == tenant_id,
                KnowledgeStorageObject.bucket_name == bucket_name,
                KnowledgeStorageObject.object_name == object_name,
            )
            .first()
        )
        if row is None:
            return False
        if row.delete_flag == "Y" or row.status == DELETED_STATUS:
            return True

        row.status = DELETED_STATUS
        row.delete_flag = "Y"
        if updated_by is not None:
            row.updated_by = updated_by
        row.update_time = func.current_timestamp()
        session.flush()
        return True


def update_storage_object_raw_bytes(
    tenant_id: str,
    bucket_name: str,
    object_name: str,
    raw_bytes: int,
    updated_by: Optional[str] = None,
) -> bool:
    """Repair authoritative size drift for one active tenant-owned ledger row."""
    _validate_raw_bytes(raw_bytes)
    with get_db_session() as session:
        row = (
            session.query(KnowledgeStorageObject)
            .filter(
                KnowledgeStorageObject.tenant_id == tenant_id,
                KnowledgeStorageObject.bucket_name == bucket_name,
                KnowledgeStorageObject.object_name == object_name,
                KnowledgeStorageObject.delete_flag == "N",
                KnowledgeStorageObject.status == COMMITTED_STATUS,
            )
            .first()
        )
        if row is None:
            return False
        if row.raw_bytes == raw_bytes:
            return True

        row.raw_bytes = raw_bytes
        if updated_by is not None:
            row.updated_by = updated_by
        row.update_time = func.current_timestamp()
        session.flush()
        return True
