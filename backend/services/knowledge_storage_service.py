"""Knowledge-base source-object accounting helpers.

This module is the service boundary between upload lifecycle handling and the
durable MinIO source-object ledger. Generic MinIO uploads must not call these
helpers unless :func:`resolve_storage_context` returns a valid tenant-owned KB.
"""

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from consts.const import MINIO_DEFAULT_BUCKET
from database.attachment_db import delete_file, get_file_size_from_minio_strict
from database.knowledge_db import get_knowledge_record
from database.knowledge_storage_object_db import (
    COMMITTED_STATUS,
    aggregate_committed_bytes_by_kb,
    commit_storage_object,
    get_tenant_committed_bytes,
    mark_storage_object_deleted,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnowledgeStorageContext:
    """Validated ownership and object-bucket context for one KB upload."""

    tenant_id: str
    knowledge_id: int
    index_name: str
    bucket_name: str


def resolve_storage_context(
    index_name: Optional[str],
    uploader_tenant_id: Optional[str],
) -> Optional[KnowledgeStorageContext]:
    """Resolve a KB only when the index belongs to the uploader's tenant."""
    if not index_name or not uploader_tenant_id:
        return None

    knowledge = get_knowledge_record({
        "index_name": index_name,
        "tenant_id": uploader_tenant_id,
    })
    if not knowledge:
        return None

    knowledge_id = knowledge.get("knowledge_id")
    owner_tenant_id = knowledge.get("tenant_id")
    if knowledge_id is None or owner_tenant_id != uploader_tenant_id:
        return None

    bucket_name = MINIO_DEFAULT_BUCKET
    if not bucket_name:
        raise RuntimeError("MinIO default bucket is not configured")

    return KnowledgeStorageContext(
        tenant_id=uploader_tenant_id,
        knowledge_id=int(knowledge_id),
        index_name=index_name,
        bucket_name=bucket_name,
    )


def get_committed_bytes_by_kb(
    tenant_id: str,
    knowledge_ids: Optional[Iterable[int]] = None,
) -> Dict[int, int]:
    """Return committed source bytes keyed by integer knowledge ID."""
    selected_ids = list(knowledge_ids) if knowledge_ids is not None else None
    raw_totals = aggregate_committed_bytes_by_kb(
        tenant_id=tenant_id,
        knowledge_ids=selected_ids,
    )
    return {
        int(knowledge_id): int(raw_bytes or 0)
        for knowledge_id, raw_bytes in (raw_totals or {}).items()
    }


def get_tenant_committed_source_bytes(tenant_id: str) -> int:
    """Return all active source bytes owned by the tenant, including orphaned KB rows."""
    return int(get_tenant_committed_bytes(tenant_id=tenant_id) or 0)


def commit_uploaded_object(
    context: KnowledgeStorageContext,
    object_name: str,
    created_by: Optional[str] = None,
) -> Dict:
    """Read authoritative MinIO size and idempotently commit one source object."""
    raw_bytes = get_file_size_from_minio_strict(
        object_name=object_name,
        bucket=context.bucket_name,
    )
    if raw_bytes is None:
        raise FileNotFoundError(f"MinIO object does not exist: {object_name}")
    if not isinstance(raw_bytes, int) or isinstance(raw_bytes, bool) or raw_bytes < 0:
        raise ValueError(f"Invalid authoritative object size for {object_name}")

    record = commit_storage_object(
        tenant_id=context.tenant_id,
        knowledge_id=context.knowledge_id,
        index_name=context.index_name,
        bucket_name=context.bucket_name,
        object_name=object_name,
        raw_bytes=raw_bytes,
        created_by=created_by,
        updated_by=created_by,
    )
    if (
        not record
        or record.get("status") != COMMITTED_STATUS
        or record.get("delete_flag") != "N"
    ):
        raise RuntimeError(f"Failed to commit storage accounting for {object_name}")
    return record


def compensate_uploaded_objects(
    context: KnowledgeStorageContext,
    object_names: Iterable[str],
    updated_by: Optional[str] = None,
) -> None:
    """Delete only the supplied new objects and release charges after deletion succeeds."""
    for object_name in object_names:
        try:
            delete_result = delete_file(
                object_name=object_name,
                bucket=context.bucket_name,
            )
            if not delete_result.get("success"):
                logger.error(
                    "Failed to compensate KB source object %s: %s",
                    object_name,
                    delete_result.get("error", "unknown deletion error"),
                )
                try:
                    # If the database failure was transient, a retry keeps the
                    # retained object charged instead of leaving it invisible.
                    commit_uploaded_object(
                        context=context,
                        object_name=object_name,
                        created_by=updated_by,
                    )
                except Exception:
                    logger.critical(
                        "KB source object %s remains in MinIO and could not be charged",
                        object_name,
                        exc_info=True,
                    )
                continue

            if not mark_storage_object_deleted(
                tenant_id=context.tenant_id,
                bucket_name=context.bucket_name,
                object_name=object_name,
                updated_by=updated_by,
            ):
                logger.warning(
                    "No active storage ledger row found while compensating %s",
                    object_name,
                )
        except Exception:
            logger.exception(
                "Failed to compensate newly uploaded KB source object %s",
                object_name,
            )
