# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Fence deletion side effects after the caller has checked current resource DAC."""

import re
from datetime import UTC, datetime

from contracts.agentos_knowledge import KnowledgeJobState, ObjectReference
from contracts.knowledge_deletion import DELETION_DATASET, KnowledgeDeletionIntent
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import FieldPatch, Revision, WriteOutcome


class DeletionPhaseChanged(Conflict):
    """A captured lifecycle revision changed; its side effect must not be repeated."""


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
        waiting = intent.scope == 'full' and self.awaiting_source(row)
        if any(row[name] != getattr(intent, field) for name, field in (
            ("file_id", "file_id"), ("knowledge_id", "knowledge_id"),
            ("source_generation", "file_version"), ("index_name", "index_name"),
            ("original_filename", "filename"), ("object_name", "object_name"),
        ) if not (waiting and field == 'filename')):
            raise Conflict()
        source = [row[name] for name in ("source_space", "source_key", "source_revision", "source_sha256")]
        expected = ([intent.source.space, intent.source.key, intent.source.version, intent.source.sha256]
                    if intent.source is not None else [None] * 4)
        if intent.scope == "source_only" and row["stage"] == "SOURCE_DELETED":
            expected = [None] * 4
        if source != expected:
            if intent.scope != 'full' or intent.source is not None or not self.awaiting_source(row):
                raise Conflict()
            self._published_source(row)

    @staticmethod
    def awaiting_source(row):
        return row.get('deletion_request') is not None and (
            row['status'] == 'UPLOADING' and row['stage'] in {
                'SOURCE_UPLOAD', 'SOURCE_CONFIRMED', 'SOURCE_ACCOUNTED', 'SOURCE_REVIEW',
            } or row['status'] == 'UPLOADED' and row['stage'] == 'UPLOAD'
        )

    @staticmethod
    def _published_source(row):
        try:
            source = ObjectReference(space=row['source_space'], key=row['source_key'],
                                     version=row['source_revision'], sha256=row['source_sha256'])
        except ValueError:
            raise Conflict() from None
        if (source.space != 'files' or source.key != row['object_name']
                or source.sha256 != row['source_upload_sha256'] or not row['upload_owner_service']):
            raise Conflict()
        return source

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
        if receipt.outcome is not WriteOutcome.CONFIRMED:
            raise Conflict()
        if not receipt.matched:
            raise DeletionPhaseChanged()
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
        if row['status'] == 'UPLOADING':
            if row['stage'] in {'SOURCE_UPLOAD', 'SOURCE_CONFIRMED', 'SOURCE_ACCOUNTED', 'SOURCE_REVIEW'}:
                if (not row['bucket_name'] or not row['object_name'] or not row['upload_owner_service']
                        or not isinstance(row['source_upload_sha256'], str)
                        or not re.fullmatch(r'[0-9a-f]{64}', row['source_upload_sha256'])):
                    raise Conflict()
                # Keep the existing source owner eligible to confirm and account its write.
                return self._patch(row, {'deletion_request': intent.model_dump(mode='json'), 'deleted_vector_count': None}, context)
            if row['stage'] != 'UPLOAD' or intent.source is not None:
                raise Conflict()
        return self._patch(row, {
            "deletion_request": intent.model_dump(mode="json"),
            'deleted_vector_count': None,
            "status": "DELETE_REQUESTED" if intent.scope == "full" else "COMPLETED",
            "stage": "DELETE_ACCEPTED",
        }, context)

    def activate(self, row, *, context):
        intent = self.request(row)
        if intent.scope != 'full' or not self.awaiting_source(row):
            raise Conflict()
        ready = row['status'] == 'UPLOADED' or (
            row['status'] == 'UPLOADING' and row['stage'] == 'SOURCE_REVIEW'
            and row['error_code'] == 'STORAGE_QUOTA_EXCEEDED'
        )
        if not ready:
            return row
        source = self._published_source(row)
        if row['storage_object_id'] is None:
            raise Conflict()
        bound = KnowledgeDeletionIntent.model_validate({**intent.model_dump(mode='json'),
                                                        'source': source.model_dump(mode='json'),
                                                        'filename': row['original_filename']})
        return self._patch(row, {'deletion_request': bound.model_dump(mode='json'),
                                 'status': 'DELETE_REQUESTED', 'stage': 'DELETE_ACCEPTED'}, context)

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
        if stage == 'DELETE_CLEANSE_PENDING':
            if state.processed_chunks is None or state.total_chunks is None or state.processed_chunks != state.total_chunks:
                raise InvalidInput()
            return self._patch(row, {'stage': stage, 'deleted_vector_count': state.processed_chunks}, context)
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
            if row['deleted_vector_count'] is None:
                raise Conflict()
            values = {"status": "DELETED", "stage": "DELETE_DONE", "deleted_at": datetime.now(UTC).isoformat()}
        else:
            values = {"stage": "SOURCE_DELETED", **{name: None for name in (
                "source_space", "source_key", "source_revision", "source_sha256",
            )}}
        return self._patch(row, values, context)
