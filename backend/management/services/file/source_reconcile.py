# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Confirm old source identity without retransmission, deletion or accounting publication."""

from datetime import datetime, timedelta, timezone

from management.services.file.source_publish import (
    DATASET,
    binding_values,
    confirmed_reference,
    validate_scope,
)
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import FieldPatch, ObjectRef, Revision


class SourceReconciler:
    def __init__(self, records, objects, *, clock=None, retry_seconds=300):
        validate_scope(records, objects)
        if (
            type(retry_seconds) is not int
            or not 1 <= retry_seconds <= 3600
            or clock is not None
            and not callable(clock)
        ):
            raise InvalidInput()
        self.records = records
        self.objects = objects
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.retry_seconds = retry_seconds

    def _patch(self, row, values, result, context):
        receipt = self.records.patch(
            DATASET,
            row["file_id"],
            FieldPatch(set_values=values),
            expected=Revision(str(row["version"])),
            context=context,
        )
        return result if receipt.matched else "stale"

    def reconcile(
        self,
        file_id,
        *,
        owner_service,
        owner_user_id,
        expected_version,
        cutoff,
        context,
    ):
        if (
            type(expected_version) is not int
            or expected_version < 0
            or not isinstance(cutoff, datetime)
            or cutoff.tzinfo is None
            or cutoff.utcoffset() is None
        ):
            raise InvalidInput()
        context.remaining()
        row = self.records.get(DATASET, file_id, context=context)
        if not row:
            return "stale"
        if (
            row["created_by"] != owner_user_id
            or row["upload_owner_service"] != owner_service
        ):
            raise ScopeDenied()
        if (
            row["version"] != expected_version
            or row["status"] != "UPLOADING"
            or row["stage"] != "SOURCE_UPLOAD"
        ):
            return "stale"
        started, after = row["source_upload_started_at"], row["source_reconcile_after"]
        if (
            not started
            or datetime.fromisoformat(started) > cutoff
            or after
            and datetime.fromisoformat(after) > self.clock()
        ):
            return "waiting"
        target = ObjectRef(
            "files",
            row["object_name"],
            Revision(row["source_revision"]) if row["source_revision"] else None,
        )
        try:
            metadata = self.objects.stat(target, context=context)
        except NotFound:
            return self._patch(
                row,
                {
                    "source_reconcile_after": (
                        self.clock() + timedelta(seconds=self.retry_seconds)
                    ).isoformat(),
                    "error_code": "SOURCE_UPLOAD_PENDING",
                    "error_stage": "SOURCE_RECONCILE",
                },
                "pending",
                context,
            )
        except Conflict:
            return self._review(row, context)
        try:
            source = confirmed_reference(
                metadata, target, row["source_upload_sha256"], row["file_size"]
            )
            if row["source_revision"] and any(
                row[name] != value for name, value in binding_values(source).items()
            ):
                return self._review(row, context)
        except (OutcomeUnknown, ValueError):
            return self._review(row, context)
        return self._patch(
            row,
            {
                **binding_values(source),
                "stage": "SOURCE_CONFIRMED",
                "source_reconcile_after": None,
                "error_code": None,
                "error_stage": None,
            },
            "confirmed",
            context,
        )

    def _review(self, row, context):
        return self._patch(
            row,
            {
                "stage": "SOURCE_REVIEW",
                "source_reconcile_after": None,
                "error_code": "SOURCE_IDENTITY_MISMATCH",
                "error_stage": "SOURCE_RECONCILE",
            },
            "review",
            context,
        )
