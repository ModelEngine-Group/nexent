"""Backfill and reconcile knowledge-base MinIO source-object accounting."""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from consts.const import ASSET_OWNER_ATTACHMENTS_PREFIX, MINIO_DEFAULT_BUCKET
from database.attachment_db import get_file_size_from_minio_strict
from database.knowledge_db import get_knowledge_info_by_tenant_id
from database.knowledge_storage_object_db import (
    StorageObjectConflictError,
    commit_storage_object,
    get_storage_object,
    list_committed_storage_objects,
    mark_storage_object_deleted,
    update_storage_object_raw_bytes,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StorageObjectReference:
    """Canonical MinIO object identity derived without ownership guessing."""

    bucket_name: str
    object_name: str


def resolve_storage_reference(
    path_or_url: Optional[str],
    default_bucket: Optional[str] = MINIO_DEFAULT_BUCKET,
) -> Optional[StorageObjectReference]:
    """Resolve storage references that carry reliable MinIO identity evidence."""
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

    default_bucket_prefixes = (
        "knowledge_base/",
        f"{ASSET_OWNER_ATTACHMENTS_PREFIX}/",
    )
    if value.startswith(default_bucket_prefixes) and default_bucket:
        return StorageObjectReference(default_bucket, value)

    return None


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
    """Idempotently release one charge after physical deletion is confirmed."""
    released = mark_storage_object_deleted(
        tenant_id=tenant_id,
        bucket_name=bucket_name,
        object_name=object_name,
        updated_by=updated_by,
    )
    if released:
        invalidate_storage_usage_cache(tenant_id)
    return released


class KnowledgeStorageReconciliationService:
    """Conservative historical backfill and ledger-versus-MinIO repair."""

    def __init__(
        self,
        tenant_id: str,
        vdb_core: Any,
        *,
        default_bucket: Optional[str] = MINIO_DEFAULT_BUCKET,
        updated_by: Optional[str] = None,
    ) -> None:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not default_bucket:
            raise ValueError("MinIO default bucket is required")
        self.tenant_id = tenant_id
        self.vdb_core = vdb_core
        self.default_bucket = default_bucket
        self.updated_by = updated_by

    @staticmethod
    def _new_report(operation: str, apply: bool) -> Dict[str, Any]:
        return {
            "operation": operation,
            "mode": "apply" if apply else "dry_run",
            "summary": {
                "knowledge_bases_scanned": 0,
                "references_scanned": 0,
                "candidates": 0,
                "already_recorded": 0,
                "applied": 0,
                "missing": 0,
                "conflicting": 0,
                "unresolved": 0,
                "size_drift": 0,
                "errors": 0,
            },
            "candidates": [],
            "applied": [],
            "already_recorded": [],
            "missing": [],
            "conflicting": [],
            "unresolved": [],
            "size_drift": [],
            "errors": [],
        }

    @staticmethod
    def _append(report: Dict[str, Any], category: str, item: Dict[str, Any]) -> None:
        report[category].append(item)
        report["summary"][category] += 1

    @staticmethod
    def _validate_size(raw_bytes: Any) -> int:
        if not isinstance(raw_bytes, int) or isinstance(raw_bytes, bool) or raw_bytes < 0:
            raise ValueError(f"Invalid authoritative MinIO object size: {raw_bytes!r}")
        return raw_bytes

    def _read_authoritative_size(self, reference: StorageObjectReference) -> Tuple[bool, Optional[int]]:
        raw_bytes = get_file_size_from_minio_strict(
            object_name=reference.object_name,
            bucket=reference.bucket_name,
        )
        if raw_bytes is None:
            return False, None
        return True, self._validate_size(raw_bytes)

    @staticmethod
    def _evidence(
        knowledge: Dict[str, Any],
        reference: StorageObjectReference,
        raw_path: str,
    ) -> Dict[str, Any]:
        return {
            "tenant_id": knowledge.get("tenant_id"),
            "knowledge_id": knowledge.get("knowledge_id"),
            "index_name": knowledge.get("index_name"),
            "path_or_url": raw_path,
            "bucket_name": reference.bucket_name,
            "object_name": reference.object_name,
        }

    def backfill(self, *, apply: bool = False) -> Dict[str, Any]:
        """Backfill evidence-backed ES source references using MinIO metadata."""
        report = self._new_report("backfill", apply)
        knowledge_bases = get_knowledge_info_by_tenant_id(self.tenant_id) or []
        report["summary"]["knowledge_bases_scanned"] = len(knowledge_bases)

        resolved: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for knowledge in knowledge_bases:
            index_name = knowledge.get("index_name")
            knowledge_id = knowledge.get("knowledge_id")
            if not index_name or knowledge_id is None:
                self._append(report, "errors", {
                    "index_name": index_name,
                    "reason": "knowledge record is missing index_name or knowledge_id",
                })
                continue
            try:
                documents = self.vdb_core.get_documents_detail_strict(index_name)
            except Exception as exc:
                self._append(report, "errors", {
                    "index_name": index_name,
                    "reason": f"failed to read Elasticsearch references: {exc}",
                })
                continue

            seen_paths = set()
            for document in documents:
                raw_path = str((document or {}).get("path_or_url") or "")
                if raw_path in seen_paths:
                    continue
                seen_paths.add(raw_path)
                report["summary"]["references_scanned"] += 1
                reference = resolve_storage_reference(raw_path, self.default_bucket)
                if reference is None:
                    self._append(report, "unresolved", {
                        "tenant_id": self.tenant_id,
                        "knowledge_id": knowledge_id,
                        "index_name": index_name,
                        "path_or_url": raw_path,
                        "reason": "reference does not provide reliable MinIO identity",
                    })
                    continue
                evidence = self._evidence(knowledge, reference, raw_path)
                resolved.setdefault(
                    (reference.bucket_name, reference.object_name), []
                ).append(evidence)

        for (bucket_name, object_name), evidence_items in resolved.items():
            owners = {
                (str(item.get("tenant_id")), str(item.get("knowledge_id")), item.get("index_name"))
                for item in evidence_items
            }
            if len(owners) != 1:
                self._append(report, "conflicting", {
                    "bucket_name": bucket_name,
                    "object_name": object_name,
                    "evidence": evidence_items,
                    "reason": "the same physical object is referenced by multiple knowledge bases",
                })
                continue

            evidence = evidence_items[0]
            reference = StorageObjectReference(bucket_name, object_name)
            try:
                exists, raw_bytes = self._read_authoritative_size(reference)
            except Exception as exc:
                self._append(report, "errors", {
                    **evidence,
                    "reason": f"failed to read MinIO metadata: {exc}",
                })
                continue
            if not exists:
                self._append(report, "missing", {
                    **evidence,
                    "reason": "referenced MinIO object does not exist",
                })
                continue

            existing = get_storage_object(
                self.tenant_id,
                bucket_name,
                object_name,
                include_deleted=True,
            )
            if existing:
                same_owner = (
                    str(existing.get("tenant_id")) == str(self.tenant_id)
                    and str(existing.get("knowledge_id")) == str(evidence.get("knowledge_id"))
                    and existing.get("index_name") == evidence.get("index_name")
                )
                if not same_owner:
                    self._append(report, "conflicting", {
                        **evidence,
                        "ledger_record": existing,
                        "reason": "ledger ownership conflicts with Elasticsearch evidence",
                    })
                    continue
                if existing.get("status") == "DELETED" or existing.get("delete_flag") == "Y":
                    self._append(report, "conflicting", {
                        **evidence,
                        "ledger_record": existing,
                        "reason": "a terminal deleted ledger row exists for the live object",
                    })
                    continue
                if existing.get("status") == "COMMITTED":
                    existing_bytes = int(existing.get("raw_bytes") or 0)
                    if existing_bytes == raw_bytes:
                        self._append(report, "already_recorded", {
                            **evidence,
                            "raw_bytes": raw_bytes,
                        })
                        continue
                    drift = {
                        **evidence,
                        "ledger_raw_bytes": existing_bytes,
                        "minio_raw_bytes": raw_bytes,
                    }
                    self._append(report, "size_drift", drift)
                    if apply:
                        try:
                            if update_storage_object_raw_bytes(
                                tenant_id=self.tenant_id,
                                bucket_name=bucket_name,
                                object_name=object_name,
                                raw_bytes=raw_bytes,
                                updated_by=self.updated_by,
                            ):
                                self._append(report, "applied", {
                                    **drift,
                                    "repair": "update_raw_bytes",
                                })
                            else:
                                raise RuntimeError("active ledger row disappeared before size repair")
                        except Exception as exc:
                            self._append(report, "errors", {
                                **drift,
                                "reason": f"failed to repair size drift: {exc}",
                            })
                    continue

            candidate = {**evidence, "raw_bytes": raw_bytes}
            self._append(report, "candidates", candidate)
            if not apply:
                continue
            try:
                committed = commit_storage_object(
                    tenant_id=self.tenant_id,
                    knowledge_id=evidence["knowledge_id"],
                    index_name=evidence["index_name"],
                    bucket_name=bucket_name,
                    object_name=object_name,
                    raw_bytes=raw_bytes,
                    created_by=self.updated_by,
                    updated_by=self.updated_by,
                )
                if committed.get("status") != "COMMITTED" or committed.get("delete_flag") == "Y":
                    raise RuntimeError("ledger commit did not produce an active COMMITTED row")
                self._append(report, "applied", candidate)
            except StorageObjectConflictError as exc:
                self._append(report, "conflicting", {
                    **candidate,
                    "reason": f"ledger identity conflicts with another owner: {exc}",
                })
            except Exception as exc:
                self._append(report, "errors", {
                    **candidate,
                    "reason": f"failed to commit ledger row: {exc}",
                })

        if report["summary"]["applied"]:
            invalidate_storage_usage_cache(self.tenant_id)
        return report

    def reconcile(self, *, apply: bool = False) -> Dict[str, Any]:
        """Compare active ledger rows with MinIO and safely repair explicit drift."""
        report = self._new_report("reconcile", apply)
        rows = list_committed_storage_objects(self.tenant_id) or []

        for row in rows:
            reference = StorageObjectReference(
                bucket_name=row["bucket_name"],
                object_name=row["object_name"],
            )
            identity = {
                "tenant_id": row.get("tenant_id"),
                "knowledge_id": row.get("knowledge_id"),
                "index_name": row.get("index_name"),
                "bucket_name": reference.bucket_name,
                "object_name": reference.object_name,
            }
            try:
                exists, actual_bytes = self._read_authoritative_size(reference)
            except Exception as exc:
                self._append(report, "errors", {
                    **identity,
                    "reason": f"failed to read MinIO metadata: {exc}",
                })
                continue

            if not exists:
                item = {
                    **identity,
                    "ledger_raw_bytes": int(row.get("raw_bytes") or 0),
                    "reason": "active ledger object is missing from MinIO",
                }
                self._append(report, "missing", item)
                if apply:
                    try:
                        if mark_storage_object_deleted(
                            tenant_id=self.tenant_id,
                            bucket_name=reference.bucket_name,
                            object_name=reference.object_name,
                            updated_by=self.updated_by,
                        ):
                            self._append(report, "applied", {**item, "repair": "mark_deleted"})
                    except Exception as exc:
                        self._append(report, "errors", {
                            **item,
                            "reason": f"failed to mark missing object deleted: {exc}",
                        })
                continue

            ledger_bytes = int(row.get("raw_bytes") or 0)
            if ledger_bytes == actual_bytes:
                self._append(report, "already_recorded", {
                    **identity,
                    "raw_bytes": actual_bytes,
                })
                continue

            item = {
                **identity,
                "ledger_raw_bytes": ledger_bytes,
                "minio_raw_bytes": actual_bytes,
            }
            self._append(report, "size_drift", item)
            if apply:
                try:
                    updated = update_storage_object_raw_bytes(
                        tenant_id=self.tenant_id,
                        bucket_name=reference.bucket_name,
                        object_name=reference.object_name,
                        raw_bytes=actual_bytes,
                        updated_by=self.updated_by,
                    )
                    if updated:
                        self._append(report, "applied", {**item, "repair": "update_raw_bytes"})
                    else:
                        self._append(report, "errors", {
                            **item,
                            "reason": "active ledger row disappeared before size repair",
                        })
                except Exception as exc:
                    self._append(report, "errors", {
                        **item,
                        "reason": f"failed to repair size drift: {exc}",
                    })

        if report["summary"]["applied"]:
            invalidate_storage_usage_cache(self.tenant_id)
        return report
