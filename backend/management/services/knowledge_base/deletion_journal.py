# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Fence deletion side effects after the caller has checked current resource DAC."""

from datetime import UTC, datetime

from contracts.agentos_knowledge import KnowledgeJobState
from contracts.knowledge_deletion import DELETION_DATASET, KnowledgeDeletionIntent
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import FieldPatch, Revision, WriteOutcome


class DeletionJournal:
    def __init__(self, records):
        scope = records.scope
        if scope.system or scope.service_role != "management" or DELETION_DATASET not in scope.namespaces:
            raise ScopeDenied()
        self.records = records

    def record(self, file_id, *, context):
        row = self.records.get(DELETION_DATASET, file_id, context=context)
        if row is None:
            raise NotFound()
        return row

    def _identity(self, row, intent):
        if row["tenant_id"] != self.records.scope.tenant_id or intent.user_id != self.records.scope.actor_id:
            raise ScopeDenied()
        if any(row[name] != getattr(intent, field) for name, field in (
            ("file_id", "file_id"), ("knowledge_id", "knowledge_id"),
            ("source_generation", "file_version"), ("index_name", "index_name"),
            ("original_filename", "filename"), ("object_name", "object_name"),
        )):
            raise Conflict()
        source = [row[name] for name in ("source_space", "source_key", "source_revision", "source_sha256")]
        expected = ([intent.source.space, intent.source.key, intent.source.version, intent.source.sha256]
                    if intent.source is not None else [None] * 4)
        if intent.scope == "source_only" and row["stage"] == "SOURCE_DELETED":
            expected = [None] * 4
        if source != expected:
            raise Conflict()

    def request(self, row):
        intent = KnowledgeDeletionIntent.model_validate(row["deletion_request"])
        self._identity(row, intent)
        return intent

    def _patch(self, row, values, context):
        receipt = self.records.patch(
            DELETION_DATASET, row["file_id"], FieldPatch(set_values=values),
            expected=Revision(str(row["version"])), context=context,
        )
        if receipt.outcome is WriteOutcome.UNKNOWN:
            raise OutcomeUnknown(operation_id=context.operation_id)
        if receipt.outcome is not WriteOutcome.CONFIRMED or not receipt.matched:
            raise Conflict()
        current = self.records.get(DELETION_DATASET, row["file_id"], context=context)
        if current is None:
            raise OutcomeUnknown(operation_id=context.operation_id)
        return current

    def _phase(self, row, stages):
        intent = self.request(row)
        if row["stage"] not in stages or row["status"] != (
            "DELETE_REQUESTED" if intent.scope == "full" else "COMPLETED"
        ):
            raise Conflict()
        return intent

    def admit(self, intent, row, *, context):
        if not isinstance(intent, KnowledgeDeletionIntent):
            raise InvalidInput()
        self._identity(row, intent)
        if row["deletion_request"] is not None:
            previous = KnowledgeDeletionIntent.model_validate(row["deletion_request"])
            source_completed = (
                row["status"] == "COMPLETED" and row["stage"] == "SOURCE_DELETED"
                and previous.scope == "source_only" and intent.scope == "full"
                and all(getattr(previous, name) == getattr(intent, name) for name in (
                    "knowledge_id", "file_id", "file_version", "index_name", "filename", "object_name",
                ))
            )
            if not source_completed:
                if self.request(row) != intent:
                    raise Conflict()
                return row
        if row["status"] not in {"UPLOADING", "UPLOADED", "PROCESSING", "FORWARDING", "FAILED", "COMPLETED"}:
            raise Conflict()
        if intent.scope == "source_only" and row["status"] != "COMPLETED":
            raise Conflict()
        if row["status"] == "UPLOADING" and (row["stage"] != "UPLOAD" or intent.source is not None):
            # A started source write must retain its publication/reconciliation owner.
            raise Conflict()
        return self._patch(row, {
            "deletion_request": intent.model_dump(mode="json"),
            "status": "DELETE_REQUESTED" if intent.scope == "full" else "COMPLETED",
            "stage": "DELETE_ACCEPTED",
        }, context)

    def begin_runtime(self, row, *, context):
        intent = self._phase(row, {"DELETE_ACCEPTED"})
        if intent.scope != "full":
            raise Conflict()
        pending = self._patch(row, {"stage": "DELETE_RUNTIME_SUBMITTING"}, context)
        return pending, intent.runtime_request()

    def observe_runtime(self, row, state, *, context):
        intent = self._phase(row, {"DELETE_RUNTIME_SUBMITTING", "DELETE_RUNTIME_PENDING"})
        if intent.scope != "full" or not isinstance(state, KnowledgeJobState):
            raise InvalidInput()
        lookup = intent.runtime_lookup(self.records.scope.tenant_id)
        if any(getattr(state, name) != getattr(lookup, name) for name in (
            "job_id", "knowledge_id", "file_id", "file_version",
        )):
            raise ScopeDenied()
        if state.status not in {"cleanup_pending", "deleted"} or (
            state.physical_cleanup_complete and state.status != "deleted"
        ):
            raise InvalidInput()
        stage = ("DELETE_CLEANSE_PENDING" if state.status == "deleted" and state.physical_cleanup_complete
                 else "DELETE_RUNTIME_PENDING")
        return row if row["stage"] == stage else self._patch(row, {"stage": stage}, context)

    def confirm_cleanse_drained(self, row, *, physical_completion_confirmed, context):
        intent = self._phase(row, {"DELETE_CLEANSE_PENDING"})
        if intent.scope != "full" or physical_completion_confirmed is not True:
            raise Conflict()
        return self._patch(row, {"stage": "DELETE_SOURCE_PENDING"}, context)

    def begin_source(self, row, *, context):
        intent = self.request(row)
        self._phase(row, {"DELETE_SOURCE_PENDING"} if intent.scope == "full" else {"DELETE_ACCEPTED"})
        return self._patch(row, {"stage": "DELETE_SOURCE_DELETING"}, context)

    def finish_source(self, row, *, physical_absence_confirmed, context):
        intent = self._phase(row, {"DELETE_SOURCE_DELETING"})
        if physical_absence_confirmed is not True:
            raise Conflict()
        if intent.scope == "full":
            values = {"status": "DELETED", "stage": "DELETE_DONE", "deleted_at": datetime.now(UTC).isoformat()}
        else:
            values = {"stage": "SOURCE_DELETED", **{name: None for name in (
                "source_space", "source_key", "source_revision", "source_sha256",
            )}}
        return self._patch(row, values, context)
