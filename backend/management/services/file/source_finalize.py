# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Idempotent source accounting followed by authoritative post-write quota admission."""

from datetime import datetime, timezone

from contracts.knowledge import KEY_TENANT_HARD_LIMIT_BYTES
from management.services.file.source_publish import (
    DATASET,
    binding_values,
    confirmed_reference,
    validate_scope,
)
from management.services.knowledge_base.usage_cache import invalidate_usage_cache
from nexent.storage.errors import Conflict, OutcomeUnknown, ScopeDenied
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Junction,
    ObjectRef,
    PageRequest,
    RecordQuery,
    Revision,
)

LEDGER = "knowledge_storage_objects"
QUOTA = "upload_tenant_config"


class SourceFinalizer:
    def __init__(self, records, objects):
        validate_scope(records, objects)
        self.records, self.objects = records, objects

    @staticmethod
    def _owned(records, file_id, user, service, context):
        row = records.get(DATASET, file_id, context=context)
        if (
            not row
            or row["created_by"] != user
            or row["upload_owner_service"] != service
        ):
            raise ScopeDenied()
        if row["status"] != "UPLOADED" and (
            row["status"] != "UPLOADING"
            or row["stage"]
            not in {"SOURCE_UPLOAD", "SOURCE_CONFIRMED", "SOURCE_ACCOUNTED"}
        ):
            raise Conflict()
        return row

    @staticmethod
    def _patch(records, row, values, context):
        receipt = records.patch(
            DATASET,
            row["file_id"],
            FieldPatch(set_values=values),
            expected=Revision(str(row["version"])),
            context=context,
        )
        if not receipt.matched:
            raise Conflict()

    @staticmethod
    def _same_source(row, original, binding):
        if (
            row["source_generation"] != original["source_generation"]
            or row["file_size"] != original["file_size"]
            or any(row[name] != value for name, value in binding.items())
        ):
            raise Conflict()

    @staticmethod
    def _ledger(records, row, context):
        matches = records.query(
            LEDGER,
            RecordQuery(
                where=Junction(
                    "and",
                    (
                        Comparison("bucket_name", "eq", row["bucket_name"]),
                        Comparison("object_name", "eq", row["object_name"]),
                    ),
                )
            ),
            PageRequest(limit=2),
            context=context,
        )
        if len(matches.items) > 1 or matches.next_cursor:
            raise Conflict()
        ledger = matches.items[0] if matches.items else None
        if ledger is not None and (
            ledger["status"] != "COMMITTED"
            or any(
                ledger[name] != row[name]
                for name in (
                    "tenant_id",
                    "knowledge_id",
                    "index_name",
                    "bucket_name",
                    "object_name",
                )
            )
            or ledger["raw_bytes"] != row["file_size"]
            or row["storage_object_id"] is not None
            and ledger["storage_object_id"] != row["storage_object_id"]
        ):
            raise Conflict()
        if ledger is None and (
            row["storage_object_id"] is not None
            or row["status"] == "UPLOADED"
            or row["stage"] == "SOURCE_ACCOUNTED"
        ):
            raise Conflict()
        if row["status"] == "UPLOADED" and row["storage_object_id"] is None:
            raise Conflict()
        return ledger

    @staticmethod
    def _within_quota(records, context):
        config = records.query(
            QUOTA,
            RecordQuery(
                where=Comparison("config_key", "eq", KEY_TENANT_HARD_LIMIT_BYTES)
            ),
            PageRequest(limit=2),
            context=context,
        )
        if len(config.items) > 1 or config.next_cursor:
            raise ScopeDenied()
        raw = config.items[0]["config_value"] if config.items else None
        try:
            limit = int(raw)
        except (ValueError, TypeError):
            return True
        total = records.sum(
            LEDGER,
            "raw_bytes",
            RecordQuery(where=Comparison("status", "eq", "COMMITTED")),
            context=context,
        )
        return total <= limit

    def account(
        self, file_id, *, owner_user_id, owner_service, context, expected_version=None
    ):
        original = self._owned(
            self.records, file_id, owner_user_id, owner_service, context
        )
        if expected_version is not None and original["version"] != expected_version:
            raise Conflict()
        if not original["source_revision"]:
            raise OutcomeUnknown()
        target = ObjectRef(
            "files", original["object_name"], Revision(original["source_revision"])
        )
        metadata = self.objects.stat(target, context=context)
        source = confirmed_reference(
            metadata, target, original["source_upload_sha256"], original["file_size"]
        )
        binding = binding_values(source)
        if any(original[name] != value for name, value in binding.items()):
            raise Conflict()
        try:
            with self.records.transaction(context=context) as tx:
                row = self._owned(tx, file_id, owner_user_id, owner_service, context)
                self._same_source(row, original, binding)
                ledger = self._ledger(tx, row, context)
                if row["status"] == "UPLOADED":
                    return row
                if ledger is None:
                    ledger = tx.create(
                        LEDGER,
                        {
                            "knowledge_id": row["knowledge_id"],
                            "index_name": row["index_name"],
                            "bucket_name": row["bucket_name"],
                            "object_name": row["object_name"],
                            "raw_bytes": row["file_size"],
                            "status": "COMMITTED",
                        },
                        context=context,
                    )
                if row["stage"] != "SOURCE_ACCOUNTED":
                    self._patch(
                        tx,
                        row,
                        {
                            "storage_object_id": ledger["storage_object_id"],
                            "stage": "SOURCE_ACCOUNTED",
                        },
                        context,
                    )
                return tx.get(DATASET, file_id, context=context)
        finally:
            # A commit reply may be lost; invalidate stale quota displays either way.
            invalidate_usage_cache(original["tenant_id"])

    def finish(
        self, file_id, *, owner_user_id, owner_service, context, expected_version=None
    ):
        original = self.account(
            file_id,
            owner_user_id=owner_user_id,
            owner_service=owner_service,
            context=context,
            expected_version=expected_version,
        )
        if original["status"] == "UPLOADED":
            return "uploaded"
        binding = {
            name: original[name]
            for name in (
                "source_space",
                "source_key",
                "source_revision",
                "source_sha256",
            )
        }
        # The charge is visible before the fresh authoritative quota read.
        with self.records.transaction(context=context) as tx:
            row = self._owned(tx, file_id, owner_user_id, owner_service, context)
            self._same_source(row, original, binding)
            self._ledger(tx, row, context)
            if row["status"] == "UPLOADED":
                return "uploaded"
            if row["stage"] != "SOURCE_ACCOUNTED":
                raise Conflict()
            if not self._within_quota(tx, context):
                self._patch(
                    tx,
                    row,
                    {
                        "stage": "SOURCE_REVIEW",
                        "error_code": "STORAGE_QUOTA_EXCEEDED",
                        "error_stage": "STORAGE_COMMIT",
                    },
                    context,
                )
                return "quota_review"
            self._patch(
                tx,
                row,
                {
                    "status": "UPLOADED",
                    "stage": "UPLOAD",
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "error_code": None,
                    "error_stage": None,
                    "source_reconcile_after": None,
                },
                context,
            )
            return "uploaded"
