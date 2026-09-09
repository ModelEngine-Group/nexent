"""Knowledge-base source-object accounting helpers.

This module is the service boundary between upload lifecycle handling and the
durable MinIO source-object ledger. Generic MinIO uploads must not call these
helpers unless :func:`resolve_storage_context` returns a valid tenant-owned KB.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse

from consts.const import ASSET_OWNER_ATTACHMENTS_PREFIX, MINIO_DEFAULT_BUCKET, PERMISSION_EDIT
from database.attachment_db import delete_file, get_file_size_from_minio_strict
from database.knowledge_db import get_knowledge_record
from database.knowledge_storage_object_db import (
    COMMITTED_STATUS,
    aggregate_committed_bytes_by_kb,
    commit_storage_object,
    get_committed_source_bytes_by_object_names,
    get_storage_object_by_identity,
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
    ingroup_permission: Optional[str] = None


@dataclass(frozen=True)
class StorageObjectReference:
    """Canonical MinIO object identity for an existing KB source path."""

    bucket_name: str
    object_name: str


def resolve_storage_object_knowledge(
    object_name: str,
    tenant_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve an active storage object to one tenant-owned knowledge base."""
    reference = resolve_storage_reference(object_name)
    if reference is None:
        return None

    ledger_record = get_storage_object_by_identity(
        bucket_name=reference.bucket_name,
        object_name=reference.object_name,
    )
    if not ledger_record:
        return None

    owner_tenant_id = str(ledger_record.get("tenant_id") or "")
    knowledge_id = ledger_record.get("knowledge_id")
    index_name = ledger_record.get("index_name")
    if not owner_tenant_id or knowledge_id is None or not index_name:
        return None

    if tenant_id is not None and owner_tenant_id != str(tenant_id):
        return None

    knowledge = get_knowledge_record({
        "index_name": index_name,
        "tenant_id": owner_tenant_id,
    })
    if not knowledge:
        return None

    if (
        knowledge.get("knowledge_id") is None
        or str(knowledge.get("knowledge_id")) != str(knowledge_id)
        or str(knowledge.get("index_name")) != str(index_name)
        or str(knowledge.get("tenant_id")) != owner_tenant_id
    ):
        return None

    return {
        "reference": reference,
        "ledger": ledger_record,
        "knowledge": knowledge,
    }


def resolve_storage_object_access(
    object_name: str,
    user_id: Optional[str],
    tenant_id: Optional[str],
    required_permission: str,
) -> bool:
    """Resolve a KB source object to its owning KB and enforce write access.

    Knowledge-base source reads intentionally remain public to authenticated
    users for backward compatibility. This resolver is therefore used for
    operations with write semantics, such as deleting a source object. It
    fails closed when the object cannot be mapped to one active ledger row and
    a matching knowledge-base record.
    """
    if not user_id or not tenant_id:
        return False

    normalized_permission = str(required_permission or "").upper()
    if normalized_permission not in {"EDIT", "DELETE", "MODIFY", "WRITE"}:
        return False

    try:
        ownership = resolve_storage_object_knowledge(
            object_name=object_name,
            tenant_id=tenant_id,
        )
    except Exception:
        logger.exception(
            "Failed to resolve storage-object ownership: object=%s user=%s tenant=%s",
            object_name,
            user_id,
            tenant_id,
        )
        return False
    if ownership is None:
        logger.warning(
            "Denied storage-object write without active ledger row: object=%s user=%s tenant=%s",
            object_name,
            user_id,
            tenant_id,
        )
        return False

    knowledge = ownership["knowledge"]
    index_name = knowledge["index_name"]

    # Import lazily to avoid the existing vectordatabase_service -> this
    # module import relationship during application startup.
    from management.services.knowledge_base.service import ElasticSearchService

    try:
        knowledge_permission = ElasticSearchService.resolve_knowledge_base_permission(
            index_name=str(index_name),
            user_id=str(user_id),
            tenant_id=str(tenant_id),
        )
    except (PermissionError, ValueError):
        return False
    except Exception:
        logger.exception(
            "Failed to resolve KB permission for storage object: object=%s index=%s",
            object_name,
            index_name,
        )
        return False

    return str(knowledge_permission or "").upper() in {PERMISSION_EDIT, "CREATOR"}


def resolve_storage_reference(path_or_url: Optional[str]) -> Optional[StorageObjectReference]:
    """Normalize supported KB source paths to a bucket and object key."""
    value = (path_or_url or "").strip()
    if not value:
        return None

    if value.startswith("s3://"):
        parsed = urlparse(value)
        object_name = parsed.path.lstrip("/")
        if parsed.netloc and object_name:
            return StorageObjectReference(parsed.netloc, object_name)
        return None

    if value.startswith("/"):
        bucket_name, separator, object_name = value.lstrip("/").partition("/")
        if separator and bucket_name and object_name:
            return StorageObjectReference(bucket_name, object_name)
        return None

    source_prefixes = (
        "knowledge_base/",
        f"{ASSET_OWNER_ATTACHMENTS_PREFIX}/",
    )
    if value.startswith(source_prefixes) and MINIO_DEFAULT_BUCKET:
        return StorageObjectReference(MINIO_DEFAULT_BUCKET, value)
    return None


def get_committed_source_bytes_by_paths(
    tenant_id: str,
    knowledge_id: int,
    paths: Iterable[str],
) -> Dict[str, int]:
    """Return committed source sizes for a batch of source paths."""
    references: Dict[str, StorageObjectReference] = {}
    for path in paths:
        reference = resolve_storage_reference(path)
        if reference is not None:
            references[path] = reference

    grouped_paths: Dict[str, set[str]] = {}
    for reference in references.values():
        grouped_paths.setdefault(reference.bucket_name, set()).add(
            reference.object_name
        )

    committed_by_identity: Dict[tuple[str, str], int] = {}
    for bucket_name, object_names in grouped_paths.items():
        committed = get_committed_source_bytes_by_object_names(
            tenant_id=tenant_id,
            knowledge_id=knowledge_id,
            bucket_name=bucket_name,
            object_names=sorted(object_names),
        )
        for object_name, raw_bytes in committed.items():
            committed_by_identity[(bucket_name, object_name)] = raw_bytes

    return {
        path: committed_by_identity.get(
            (reference.bucket_name, reference.object_name),
            0,
        )
        for path, reference in references.items()
    }


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
        ingroup_permission=knowledge.get("ingroup_permission"),
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


def invalidate_storage_usage_cache(tenant_id: str) -> None:
    """Invalidate quota usage lazily to avoid a module import cycle."""
    try:
        from services.quota_service import QuotaService

        QuotaService.invalidate_usage_cache(tenant_id)
    except Exception:
        logger.exception("Failed to invalidate quota cache for tenant %s", tenant_id)


def release_storage_charge(
    *,
    tenant_id: str,
    bucket_name: str,
    object_name: str,
    updated_by: Optional[str] = None,
) -> bool:
    """Release a committed source charge after physical deletion succeeds."""
    released = mark_storage_object_deleted(
        tenant_id=tenant_id,
        bucket_name=bucket_name,
        object_name=object_name,
        updated_by=updated_by,
    )
    if released:
        invalidate_storage_usage_cache(tenant_id)
    return released


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
