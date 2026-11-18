# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Domain-specific CAS journal; child submission ownership precedes every side effect."""

import re
from datetime import datetime, timezone

from contracts.agentos_knowledge import KnowledgeJobState, knowledge_job_id
from contracts.knowledge_cleanse import KnowledgeCleanseState, cleanse_job_id
from contracts.knowledge_ingestion import (
    INGESTION_DATASET,
    KnowledgeIngestionIntent,
    LegacyFileState,
    LegacyIngestionSnapshot,
)
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import FieldPatch, Revision, WriteOutcome


class IngestionPhaseChanged(Conflict):
    """Another participant changed the captured lifecycle revision; do not repeat its effect."""


class IngestionJournal:
    def __init__(self, records):
        scope = records.scope
        if (
            scope.system
            or scope.service_role != "management"
            or INGESTION_DATASET not in scope.namespaces
        ):
            raise ScopeDenied()
        self.records = records

    def record(self, file_id, *, context):
        row = self.records.get(INGESTION_DATASET, file_id, context=context)
        if row is None:
            raise NotFound()
        return row

    def _source(self, row, intent):
        if (
            row["tenant_id"] != self.records.scope.tenant_id
            or intent.user_id != self.records.scope.actor_id
        ):
            raise ScopeDenied()
        if (
            row.get("deletion_request") is not None
            or
            any(
                row[name] != getattr(intent, name)
                for name in ("file_id", "knowledge_id")
            )
            or row["source_generation"] != intent.file_version
            or row["original_filename"] != intent.filename
            or [
                row[name]
                for name in (
                    "source_space",
                    "source_key",
                    "source_revision",
                    "source_sha256",
                )
            ]
            != [
                intent.source.space,
                intent.source.key,
                intent.source.version,
                intent.source.sha256,
            ]
            or row["status"]
            not in {"UPLOADED", "PROCESSING", "FORWARDING", "COMPLETED", "FAILED"}
        ):
            raise Conflict()

    def request(self, row):
        intent = KnowledgeIngestionIntent.model_validate(row["ingestion_request"])
        self._source(row, intent)
        return intent

    def _patch(self, row, values, context):
        receipt = self.records.patch(
            INGESTION_DATASET,
            row["file_id"],
            FieldPatch(set_values=values),
            expected=Revision(str(row["version"])),
            context=context,
        )
        if receipt.outcome is WriteOutcome.UNKNOWN:
            raise OutcomeUnknown(operation_id=context.operation_id)
        if receipt.outcome is not WriteOutcome.CONFIRMED:
            raise Conflict()
        if not receipt.matched:
            raise IngestionPhaseChanged()
        return self.record(row["file_id"], context=context)

    def admit(self, intent, row, *, context):
        if not isinstance(intent, KnowledgeIngestionIntent):
            raise InvalidInput()
        self._source(row, intent)
        if intent.legacy_snapshot is not None and row['ingestion_request'] is None: raise InvalidInput()
        if row["ingestion_request"] is not None:
            if self.request(row) != intent:
                raise Conflict()
            return row
        if (
            row["status"] != "UPLOADED"
            or intent.attempt != row["processing_attempt"] + 1
            or any(
                row[name]
                for name in ("process_task_id", "forward_task_id", "parent_task_id")
            )
        ):
            raise Conflict()
        return self._accept(intent, row, context)

    def reprocess(self, row, intent, cleanse, runtime, *, context):
        if not isinstance(intent, KnowledgeIngestionIntent):
            raise InvalidInput()
        self._source(row, intent)
        prior = self.request(row)
        if intent.legacy_snapshot != prior.legacy_snapshot: raise Conflict()
        if (row['status'] != 'FAILED' or row['stage'] != 'FAILED'
                or prior.attempt != row['processing_attempt'] or intent.attempt != prior.attempt + 1
                or row['process_task_id'] != cleanse_job_id(prior.cleanse_request(), row['tenant_id'], prior.user_id)):
            raise Conflict()
        self._child(row, cleanse, KnowledgeCleanseState, 'process_task_id')
        if (cleanse.execution_ended is not True or cleanse.reconcile_required is not False
                or cleanse.artifact_ownership_known is not True):
            raise Conflict()
        if row['forward_task_id'] is None:
            if runtime is not None or cleanse.status not in {'failed', 'cancelled'}:
                raise Conflict()
        else:
            self._child(row, runtime, KnowledgeJobState, 'forward_task_id')
            if (cleanse.status != 'completed' or runtime.status not in {'failed', 'cancelled'}
                    or runtime.writer_ended is not True or runtime.reconcile_required is not False
                    or row['forward_task_id'] != knowledge_job_id(prior.runtime_request(cleanse.artifact),
                                                                 row['tenant_id'], prior.user_id)):
                raise Conflict()
        return self._accept(intent, row, context)

    def admit_legacy(self, intent, row, *, context):
        if not isinstance(intent, KnowledgeIngestionIntent) or intent.legacy_snapshot is None: raise InvalidInput()
        KnowledgeIngestionIntent.model_validate_json(intent.model_dump_json())
        self._source(row, intent)
        snapshot = intent.legacy_snapshot
        if snapshot.tenant_id != self.records.scope.tenant_id: raise ScopeDenied()
        if row['ingestion_request'] is not None:
            if self.request(row) != intent: raise Conflict()
            return row
        if (LegacyIngestionSnapshot.capture(row, resource_revision=snapshot.resource_revision, legacy_quiesced=True) != snapshot
            or intent.attempt != row['processing_attempt'] + 1
            or any(row[name] is not None for name in ('process_task_id', 'forward_task_id', 'parent_task_id'))):
            raise Conflict()
        return self._accept(intent, row, context)

    def restore_legacy(self, intent, row, *, context):
        if not isinstance(intent, KnowledgeIngestionIntent) or intent.legacy_snapshot is None: raise InvalidInput()
        self._source(row, intent)
        snapshot = intent.legacy_snapshot
        if snapshot.tenant_id != self.records.scope.tenant_id: raise ScopeDenied()
        if row['ingestion_request'] is None:
            if LegacyFileState.capture(row) != snapshot.previous: raise Conflict()
            return row
        if (self.request(row) != intent or row['stage'] != 'INGEST_ACCEPTED'
            or row['cleanse_status'] is not None or row['runtime_status'] is not None
            or row['forward_task_id'] is not None or row['parent_task_id'] is not None):
            raise Conflict()
        return self._patch(row, {**snapshot.previous.model_dump(), 'ingestion_request': None,
            'process_task_id': None, 'forward_task_id': None, 'parent_task_id': None}, context)

    def _accept(self, intent, row, context):
        return self._patch(
            row,
            {
                "ingestion_request": intent.model_dump(mode="json"),
                "processing_attempt": intent.attempt,
                "process_task_id": cleanse_job_id(
                    intent.cleanse_request(), row["tenant_id"], intent.user_id
                ),
                'forward_task_id': None,
                'parent_task_id': None,
                "status": "UPLOADED",
                "stage": "INGEST_ACCEPTED",
                "error_code": None,
                "error_message": None,
                "error_stage": None,
                "failed_at": None,
                "completed_at": None,
                "cleanse_status": None,
                "runtime_status": None,
                "processed_chunks": None,
                "total_chunks": None,
            },
            context,
        )

    def _phase(self, row, stages, status):
        intent = self.request(row)
        if row["stage"] not in stages or row["status"] != status:
            raise Conflict()
        return intent

    def begin_cleanse(self, row, *, context):
        self._phase(row, {"INGEST_ACCEPTED"}, "UPLOADED")
        return self._patch(
            row, {"status": "PROCESSING", "stage": "CLEANSE_SUBMITTING"}, context
        )

    def _child(self, row, state, expected_type, task_field):
        if not isinstance(state, expected_type) or any(
            getattr(state, name) != row[field]
            for name, field in (
                ("knowledge_id", "knowledge_id"),
                ("file_id", "file_id"),
                ("file_version", "source_generation"),
                ("job_id", task_field),
            )
        ):
            raise ScopeDenied()

    def _failed(self, row, state, stage, context):
        code = state.error_code or (
            "CANCELLED" if state.status == "cancelled" else "INGESTION_FAILED"
        )
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", code):
            code = "INGESTION_FAILED"
        return self._patch(
            row,
            {
                "status": "FAILED",
                "stage": "FAILED",
                "error_code": code,
                "error_message": None,
                "error_stage": stage,
                "failed_at": datetime.now(timezone.utc).isoformat(),
                **({"cleanse_status": state.status} if stage == "PROCESS" else {
                    "runtime_status": state.status, **self._runtime_progress(row, state)
                }),
            },
            context,
        )

    def observe_cleanse(self, row, state, *, context):
        self._phase(row, {"CLEANSE_SUBMITTING", "CLEANSE_PENDING"}, "PROCESSING")
        self._child(row, state, KnowledgeCleanseState, "process_task_id")
        if row["cleanse_status"] == "running" and state.status == "queued":
            raise Conflict()
        if state.status in {"failed", "cancelled"}:
            return self._failed(row, state, "PROCESS", context)
        if state.status not in {"queued", "running"}:
            raise InvalidInput()
        return (
            row
            if row["stage"] == "CLEANSE_PENDING" and row["cleanse_status"] == state.status
            else self._patch(row, {"stage": "CLEANSE_PENDING", "cleanse_status": state.status}, context)
        )

    def begin_runtime(self, row, state, *, context):
        intent = self._phase(
            row, {"CLEANSE_SUBMITTING", "CLEANSE_PENDING"}, "PROCESSING"
        )
        self._child(row, state, KnowledgeCleanseState, "process_task_id")
        if state.status != "completed" or state.artifact is None:
            raise InvalidInput()
        payload = intent.runtime_request(state.artifact)
        row = self._patch(
            row,
            {
                "status": "FORWARDING",
                "stage": "RUNTIME_SUBMITTING",
                "forward_task_id": knowledge_job_id(
                    payload, row["tenant_id"], intent.user_id
                ),
                "cleanse_status": "completed",
                "runtime_status": None,
                "processed_chunks": None,
                "total_chunks": None,
            },
            context,
        )
        return row, payload

    @staticmethod
    def _runtime_progress(row, state):
        values = {}
        for name in ("processed_chunks", "total_chunks"):
            value = getattr(state, name)
            if value is not None and (type(value) is not int or not 0 <= value <= 2**31 - 1):
                raise InvalidInput()
            prior = row[name]
            if value is not None and prior is not None and (
                value < prior if name == "processed_chunks" else value != prior
            ):
                raise Conflict()
            values[name] = value if value is not None else prior
        if (values["processed_chunks"] is not None and values["total_chunks"] is not None
                and values["processed_chunks"] > values["total_chunks"]):
            raise InvalidInput()
        return values

    def observe_runtime(self, row, state, *, context):
        self._phase(row, {"RUNTIME_SUBMITTING", "RUNTIME_PENDING"}, "FORWARDING")
        self._child(row, state, KnowledgeJobState, "forward_task_id")
        if row["runtime_status"] == "running" and state.status == "queued":
            raise Conflict()
        progress = self._runtime_progress(row, state)
        if state.status in {"failed", "cancelled"}:
            return self._failed(row, state, "FORWARD", context)
        if state.status == "completed":
            return self._patch(
                row,
                {
                    "status": "COMPLETED",
                    "stage": "COMPLETE",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "runtime_status": state.status,
                    **progress,
                },
                context,
            )
        if state.status not in {"queued", "running"}:
            raise InvalidInput()
        return (
            row
            if row["stage"] == "RUNTIME_PENDING" and row["runtime_status"] == state.status
            and all(row[name] == value for name, value in progress.items())
            else self._patch(row, {"stage": "RUNTIME_PENDING", "runtime_status": state.status, **progress}, context)
        )
