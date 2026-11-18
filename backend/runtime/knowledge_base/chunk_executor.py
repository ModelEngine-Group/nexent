# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute existing chunk edits/deletes once; retain uncertain writes for explicit reconciliation."""

from contracts.knowledge_chunk_mutation import ChunkMutationIntent
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    OperationCancelled,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import (
    DeleteReceipt,
    FieldPatch,
    Revision,
    VectorKey,
    VectorRecord,
    WriteOutcome,
    WriteReceipt,
)
from runtime.knowledge_base.chunk_admission import ChunkMutationAdmission


def record_mutation_failure(journal, key, *, unknown, context):
    try:
        context.remaining()
    except (DeadlineExceeded, OperationCancelled):
        # The existing admission remains active; bookkeeping never extends the budget.
        return
    if unknown:
        journal.mark_unknown(
            key,
            writer_ended=True,
            error_code="CHUNK_WRITE_UNKNOWN",
            context=context,
        )
    else:
        journal.fail(
            key,
            known_not_applied=True,
            error_code="CHUNK_WRITE_REJECTED",
            context=context,
        )


def require_chunk_identity(row, intent, collection):
    key = VectorKey(collection, intent.chunk_id)
    if row is None:
        raise NotFound()
    if (
        not isinstance(row, VectorRecord)
        or row.key != key
        or row.payload.get("knowledge_id") != intent.knowledge_id
    ):
        raise ScopeDenied()
    if intent.file_ref is None:
        if any(
            row.payload.get(field) is not None
            for field in ("file_id", "file_version", "chunk_index")
        ):
            raise ScopeDenied()
    elif (
        any(
            row.payload.get(field) != value
            for field, value in intent.file_ref.model_dump().items()
        )
        or row.payload.get("chunk_index") != intent.chunk_index
    ):
        raise ScopeDenied()
    elif row.generation != Revision(intent.generation):
        raise Conflict()
    return row


def require_chunk_scope(journal, vectors, collection):
    if not isinstance(journal, ChunkMutationAdmission):
        raise InvalidInput()
    scope, owner = vectors.scope, journal.records.scope
    if (
        scope.system
        or scope.resource_prefix
        or scope.service_role != "runtime"
        or scope.tenant_id != owner.tenant_id
        or scope.actor_id != owner.actor_id
        or collection not in scope.namespaces
    ):
        raise ScopeDenied()


class ChunkMutationExecutor:
    fields = frozenset({"content", "filename", "location"})

    def __init__(self, journal, vectors, collection):
        require_chunk_scope(journal, vectors, collection)
        self.journal, self.vectors, self.collection = journal, vectors, collection

    def _record(self, intent, *, context):
        key = VectorKey(self.collection, intent.chunk_id)
        row = self.vectors.get(key, include_vector=False, context=context)
        return require_chunk_identity(row, intent, self.collection)

    def execute(self, intent, *, context):
        if not isinstance(intent, ChunkMutationIntent):
            raise InvalidInput()
        intent = ChunkMutationIntent.model_validate(intent.model_dump(mode="json"))
        if (
            intent.operation not in {"update", "delete"}
            or intent.operation == "update"
            and (not intent.changes or not intent.changes.keys() <= self.fields)
        ):
            raise InvalidInput()
        row, admitted = self.journal.reserve(intent, context=context)
        if not admitted:
            return row
        key = row["mutation_id"]
        try:
            current = self._record(intent, context=context)
        except Exception:
            record_mutation_failure(self.journal, key, unknown=False, context=context)
            raise
        row, started = self.journal.begin(key, context=context)
        if not started:
            return row
        try:
            if intent.operation == "update":
                receipt = self.vectors.patch_payload(
                    current.key,
                    FieldPatch(set_values=intent.changes),
                    expected_generation=current.generation,
                    context=context,
                )
                valid = isinstance(receipt, WriteReceipt)
                matched = receipt.matched if valid else None
            else:
                receipt = self.vectors.delete_key(
                    current.key, expected_generation=current.generation, context=context
                )
                valid = isinstance(receipt, DeleteReceipt)
                matched = receipt.deleted if valid else None
            if (
                not valid
                or not isinstance(receipt.outcome, WriteOutcome)
                or receipt.outcome is WriteOutcome.UNKNOWN
                or type(matched) is not bool
            ):
                raise OutcomeUnknown()
            if receipt.outcome is WriteOutcome.FAILED:
                raise Conflict()
            if not matched:
                raise NotFound()
        except (Conflict, ScopeDenied, InvalidInput, NotFound, CapabilityUnsupported):
            record_mutation_failure(self.journal, key, unknown=False, context=context)
            raise
        except Exception:
            record_mutation_failure(self.journal, key, unknown=True, context=context)
            raise
        # A failed/unknown metadata commit must never turn into a second vector write.
        return self.journal.complete(
            key,
            count_delta=-1 if intent.operation == "delete" else 0,
            outcome=WriteOutcome.CONFIRMED,
            context=context,
        )
