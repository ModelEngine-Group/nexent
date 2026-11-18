# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persist one admitted chunk write without storing or automatically replaying its body."""

import re

from contracts.agentos_knowledge import KnowledgeFileReference
from contracts.knowledge_base_deletion import BASE_DELETION_DATASET as BASE
from contracts.knowledge_chunk_mutation import (
    ACTIVE_STATUSES,
    CHANGES,
    STATES,
    ChunkMutationIntent,
    chunk_key,
    mutation_id,
    state_id,
)
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Junction,
    PageRequest,
    RecordQuery,
    Revision,
    WriteOutcome,
)


def assert_knowledge_open(records, knowledge_id, *, context):
    rows = records.query(BASE, RecordQuery(where=Comparison("knowledge_id", "eq", knowledge_id)),
                         PageRequest(limit=1), context=context)
    if rows.items:
        raise Conflict()


class ChunkMutationJournal:
    def __init__(self, records, knowledge_id):
        scope = records.scope
        if (
            scope.system
            or scope.resource_prefix
            or scope.service_role != "runtime"
            or not {CHANGES, STATES} <= scope.namespaces
        ):
            raise ScopeDenied()
        if type(knowledge_id) is not int or knowledge_id <= 0:
            raise InvalidInput()
        self.records, self.knowledge_id = records, knowledge_id
        self.tenant, self.user = scope.tenant_id, scope.actor_id
        self.state_key = state_id(self.tenant, knowledge_id)

    def _state(self, records, context):
        row = records.get(STATES, self.state_key, context=context)
        if row is not None and (
            row["tenant_id"] != self.tenant
            or row["knowledge_id"] != self.knowledge_id
            or row["state_id"] != self.state_key
            or type(row["epoch"]) is not int
            or row["epoch"] < 0
            or type(row["active_count"]) is not int
            or row["active_count"] < 0
        ):
            raise ScopeDenied()
        return row

    def _owned(self, records, key, context):
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
            raise InvalidInput()
        row = records.get(CHANGES, key, context=context)
        if row is None:
            raise NotFound()
        if (
            row["mutation_id"] != key
            or row["tenant_id"] != self.tenant
            or row["knowledge_id"] != self.knowledge_id
            or row["user_id"] != self.user
        ):
            raise ScopeDenied()
        return row

    @staticmethod
    def _patch(records, dataset, row, values, context, *, cas=True):
        key = row["mutation_id" if dataset == CHANGES else "state_id"]
        receipt = records.patch(
            dataset,
            key,
            values if isinstance(values, FieldPatch) else FieldPatch(set_values=values),
            expected=Revision(str(row["revision"])) if cas else None,
            context=context,
        )
        if receipt.outcome is WriteOutcome.UNKNOWN:
            raise OutcomeUnknown(operation_id=context.operation_id)
        if receipt.outcome is not WriteOutcome.CONFIRMED or not receipt.matched:
            raise Conflict()
        return records.get(dataset, key, context=context)

    def _active(self, records, context):
        state = self._state(records, context)
        if state is None or state["active_count"] <= 0:
            raise Conflict()
        return state

    def _locked_state(self, records, context):
        state = self._state(records, context)
        if state is None:
            return records.create(
                STATES,
                {
                    "state_id": self.state_key,
                    "knowledge_id": self.knowledge_id,
                    "epoch": 0,
                    "active_count": 0,
                },
                context=context,
            )
        # An atomic zero increment locks only this metadata transaction, not provider I/O.
        return self._patch(
            records,
            STATES,
            state,
            FieldPatch(increments={"epoch": 0}),
            context,
            cas=False,
        )

    @staticmethod
    def _error_code(value):
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Z][A-Z0-9_]{0,99}", value
        ):
            raise InvalidInput()
        return value

    def reserve(self, intent, *, context):
        if not isinstance(intent, ChunkMutationIntent):
            raise InvalidInput()
        intent = ChunkMutationIntent.model_validate(intent.model_dump(mode="json"))
        if intent.knowledge_id != self.knowledge_id:
            raise ScopeDenied()
        with self.records.transaction(context=context) as tx:
            return self._reserve(tx, intent, context)

    def _reserve(self, tx, intent, context):
        key = mutation_id(self.tenant, self.user, intent)
        digest = intent.fingerprint()
        existing = tx.get(CHANGES, key, context=context)
        if existing is not None:
            row = self._owned(tx, key, context)
            if row["request_sha256"] != digest:
                raise Conflict()
            return row, False
        state = self._locked_state(tx, context)
        existing = tx.get(CHANGES, key, context=context)
        if existing is not None:
            row = self._owned(tx, key, context)
            if row["request_sha256"] != digest:
                raise Conflict()
            return row, False
        if intent.expected_change_epoch is not None and state["epoch"] != intent.expected_change_epoch:
            raise Conflict()
        logical_key = chunk_key(self.tenant, self.knowledge_id, intent.chunk_id)
        pending = tx.query(
            CHANGES,
            RecordQuery(
                where=self._where(
                    Comparison("chunk_key", "eq", logical_key),
                    Comparison("status", "in", list(ACTIVE_STATUSES)),
                )
            ),
            PageRequest(limit=1),
            context=context,
        )
        if pending.items:
            raise Conflict()
        ref = intent.file_ref
        row = tx.create(
            CHANGES,
            {
                "mutation_id": key,
                "knowledge_id": self.knowledge_id,
                "user_id": self.user,
                "chunk_id": intent.chunk_id,
                "chunk_key": logical_key,
                "operation": intent.operation,
                "request_sha256": digest,
                "resource_revision": intent.resource_revision,
                "file_id": ref.file_id if ref else None,
                "file_version": ref.file_version if ref else None,
                "generation": intent.generation,
                "chunk_index": intent.chunk_index,
                "status": "reserved",
                "writer_ended": True,
                "count_delta": None,
                "commit_epoch": None,
                "error_code": None,
            },
            context=context,
        )
        self._patch(
            tx, STATES, state, {"active_count": state["active_count"] + 1}, context
        )
        return row, True

    def inspect(self, key, *, context):
        return self._owned(self.records, key, context)

    def begin(self, key, *, context):
        with self.records.transaction(context=context) as tx:
            self._locked_state(tx, context)
            row = self._owned(tx, key, context)
            if row["status"] != "reserved":
                return row, False
            self._active(tx, context)
            return self._patch(
                tx, CHANGES, row, {"status": "writing", "writer_ended": False}, context
            ), True

    def complete(self, key, *, count_delta, outcome, context):
        if type(count_delta) is not int or outcome is not WriteOutcome.CONFIRMED:
            raise InvalidInput()
        with self.records.transaction(context=context) as tx:
            self._locked_state(tx, context)
            row = self._owned(tx, key, context)
            allowed = {"create": {0, 1}, "update": {0}, "delete": {-1, 0}}
            if count_delta not in allowed[row["operation"]]:
                raise InvalidInput()
            if row["status"] == "completed":
                if row["count_delta"] != count_delta:
                    raise Conflict()
                return row
            if row["status"] != "writing":
                raise Conflict()
            state = self._active(tx, context)
            epoch = state["epoch"] + 1
            row = self._patch(
                tx,
                CHANGES,
                row,
                {
                    "status": "completed",
                    "writer_ended": True,
                    "count_delta": count_delta,
                    "commit_epoch": epoch,
                    "error_code": None,
                },
                context,
            )
            self._patch(
                tx,
                STATES,
                state,
                {"epoch": epoch, "active_count": state["active_count"] - 1},
                context,
            )
            return row

    def fail(self, key, *, known_not_applied, error_code, context):
        if known_not_applied is not True:
            raise InvalidInput()
        error_code = self._error_code(error_code)
        with self.records.transaction(context=context) as tx:
            self._locked_state(tx, context)
            row = self._owned(tx, key, context)
            if row["status"] == "failed":
                if row["error_code"] != error_code:
                    raise Conflict()
                return row
            if row["status"] not in {"reserved", "writing"}:
                raise Conflict()
            state = self._active(tx, context)
            row = self._patch(
                tx,
                CHANGES,
                row,
                {"status": "failed", "writer_ended": True, "error_code": error_code},
                context,
            )
            self._patch(
                tx, STATES, state, {"active_count": state["active_count"] - 1}, context
            )
            return row

    def mark_unknown(self, key, *, writer_ended, error_code, context):
        if type(writer_ended) is not bool:
            raise InvalidInput()
        error_code = self._error_code(error_code)
        with self.records.transaction(context=context) as tx:
            self._locked_state(tx, context)
            row = self._owned(tx, key, context)
            if row["status"] not in {"writing", "unknown"}:
                raise Conflict()
            self._active(tx, context)
            if row["status"] == "unknown":
                if (
                    row["error_code"] != error_code
                    or row["writer_ended"]
                    and not writer_ended
                ):
                    raise Conflict()
                if row["writer_ended"] == writer_ended:
                    return row
            return self._patch(
                tx,
                CHANGES,
                row,
                {
                    "status": "unknown",
                    "writer_ended": writer_ended,
                    "error_code": error_code,
                },
                context,
            )

    def revision(self, *, context):
        row = self._state(self.records, context)
        if row is not None and row["active_count"]:
            raise Conflict()
        return row["epoch"] if row is not None else 0

    def _where(self, *terms):
        return Junction(
            "and", (Comparison("knowledge_id", "eq", self.knowledge_id), *terms)
        )

    def _file(self, ref):
        if (
            not isinstance(ref, KnowledgeFileReference)
            or ref.knowledge_id != self.knowledge_id
        ):
            raise ScopeDenied()
        return (
            Comparison("file_id", "eq", ref.file_id),
            Comparison("file_version", "eq", ref.file_version),
        )

    def _sum(self, *terms, context):
        revision = self.revision(context=context)
        count = self.records.sum(
            CHANGES,
            "count_delta",
            RecordQuery(
                where=self._where(Comparison("status", "eq", "completed"), *terms)
            ),
            context=context,
        )
        if self.revision(context=context) != revision:
            raise Conflict()
        return count

    def file_delta(self, file_ref, generation, *, context):
        if not isinstance(generation, str) or not generation or len(generation) > 256:
            raise InvalidInput()
        return self._sum(
            *self._file(file_ref),
            Comparison("generation", "eq", generation),
            context=context,
        )

    def standalone_count(self, *, context):
        count = self._sum(Comparison("file_id", "is_null", True), context=context)
        if count < 0:
            raise Conflict()
        return count

    def assert_drained(self, *, file_ref=None, context):
        terms = [Comparison("status", "in", list(ACTIVE_STATUSES))]
        if file_ref is not None:
            self._file(file_ref)
            terms.extend(
                (
                    Comparison("file_id", "eq", file_ref.file_id),
                    Comparison("file_version", "lte", file_ref.file_version),
                )
            )
        page = self.records.query(
            CHANGES,
            RecordQuery(where=self._where(*terms)),
            PageRequest(limit=1),
            context=context,
        )
        if page.items:
            raise Conflict()
