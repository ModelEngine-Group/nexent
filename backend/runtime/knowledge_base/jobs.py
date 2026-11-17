# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime KB admission, writer fencing and authoritative visibility over RecordStore."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from contracts.agentos_knowledge import (
    KnowledgeFileDelete,
    KnowledgeFileUpload,
    KnowledgeJobLookup,
    KnowledgeJobState,
    knowledge_job_id,
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

JOBS = "runtime_knowledge_jobs"
FILES = "runtime_knowledge_files"


def _all(*terms):
    return Junction("and", terms)


def job_state(row):
    return KnowledgeJobState(
        **{
            name: row[name]
            for name in (
                "knowledge_id",
                "file_id",
                "file_version",
                "job_id",
                "status",
                "error_code",
                "physical_cleanup_complete",
            )
        }
    )


def _lookup(row):
    return KnowledgeJobLookup(
        **{
            name: row[name]
            for name in ("knowledge_id", "file_id", "file_version", "job_id")
        }
    )


class KnowledgeJobs:
    def __init__(self, records, *, authorize, clock=None):
        scope = records.scope
        if (
            scope.system
            or scope.service_role != "runtime"
            or not {JOBS, FILES} <= scope.namespaces
        ):
            raise ScopeDenied()
        if not callable(authorize):
            raise InvalidInput()
        self.records, self.authorize = records, authorize
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _file_id(self, reference):
        return uuid5(
            NAMESPACE_URL,
            json.dumps(
                [
                    "runtime-kb-file",
                    self.records.scope.tenant_id,
                    reference.knowledge_id,
                    reference.file_id,
                ],
                separators=(",", ":"),
            ),
        ).hex

    def _file(self, tx, reference, context, *, create=False):
        key = self._file_id(reference)
        row = tx.get(FILES, key, context=context)
        if row is None and create:
            row = tx.create(
                FILES,
                {
                    "record_id": key,
                    "knowledge_id": reference.knowledge_id,
                    "file_id": reference.file_id,
                    "latest_version": -1,
                    "active_job_id": None,
                    "visible_job_id": None,
                    "visible_version": None,
                    "visible_generation": None,
                    "tombstone_version": -1,
                },
                context=context,
            )
        return row

    def _job(self, tx, lookup, context):
        row = tx.get(JOBS, lookup.job_id, context=context)
        if (
            row is None
            or row["user_id"] != self.records.scope.actor_id
            or any(
                row[name] != getattr(lookup, name)
                for name in ("knowledge_id", "file_id", "file_version")
            )
        ):
            raise NotFound()
        return row

    @staticmethod
    def _patch(tx, dataset, row, values, context):
        key = row["job_id" if dataset == JOBS else "record_id"]
        receipt = tx.patch(
            dataset,
            key,
            FieldPatch(set_values=values),
            expected=Revision(str(row["revision"])),
            context=context,
        )
        if receipt.outcome is WriteOutcome.UNKNOWN:
            raise OutcomeUnknown(operation_id=context.operation_id)
        if receipt.outcome is not WriteOutcome.CONFIRMED or not receipt.matched:
            raise Conflict()
        return tx.get(dataset, key, context=context)

    def _lock_file(self, tx, reference, context, *, create=False):
        row = self._file(tx, reference, context, create=create)
        if row is None:
            raise NotFound()
        # A CAS update holds the file row lock until the surrounding transaction ends.
        return self._patch(tx, FILES, row, {}, context)

    @staticmethod
    def _covered(reference):
        return _all(
            Comparison("knowledge_id", "eq", reference.knowledge_id),
            Comparison("file_id", "eq", reference.file_id),
            Comparison("file_version", "lte", reference.file_version),
        )

    def _cancel_covered(self, tx, reference, context):
        cursor = None
        while True:
            page = tx.query(
                JOBS,
                RecordQuery(where=self._covered(reference)),
                PageRequest(limit=100, cursor=cursor),
                context=context,
            )
            for row in page.items:
                if row["operation"] == "upload" and row["status"] in {
                    "queued",
                    "running",
                }:
                    self._patch(tx, JOBS, row, {"status": "cancelled"}, context)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor

    def submit(self, request, *, context):
        if (
            not isinstance(request, (KnowledgeFileUpload, KnowledgeFileDelete))
            or max(request.knowledge_id, request.file_version) > 2**31 - 1
        ):
            raise InvalidInput()
        self.authorize(request, context=context)
        operation = "upload" if isinstance(request, KnowledgeFileUpload) else "delete"
        payload = request.model_dump(mode="json")
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
        if len(encoded) > 16384:
            raise InvalidInput()
        digest = hashlib.sha256(encoded).hexdigest()
        job_id = knowledge_job_id(request, self.records.scope.tenant_id, self.records.scope.actor_id)
        lookup = KnowledgeJobLookup(
            knowledge_id=request.knowledge_id,
            file_id=request.file_id,
            file_version=request.file_version,
            job_id=job_id,
        )
        if self.records.get(JOBS, job_id, context=context) is not None:
            existing = self._job(self.records, lookup, context)
            if existing["request_hash"] != digest:
                raise Conflict()
            return job_state(existing)
        with self.records.transaction(context=context) as tx:
            manifest = self._lock_file(tx, request, context, create=True)
            if operation == "upload":
                if (
                    request.file_version <= manifest["tombstone_version"]
                    or request.file_version < manifest["latest_version"]
                ):
                    raise Conflict()
                active = (
                    tx.get(JOBS, manifest["active_job_id"], context=context)
                    if manifest["active_job_id"]
                    else None
                )
                if (
                    active
                    and active["file_version"] == request.file_version
                    and not active["writer_ended"]
                ):
                    raise Conflict()
                self._cancel_covered(tx, request, context)
                values = {
                    "latest_version": request.file_version,
                    "active_job_id": job_id,
                }
            else:
                self._cancel_covered(tx, request, context)
                values = {
                    "tombstone_version": max(
                        manifest["tombstone_version"], request.file_version
                    )
                }
                if manifest["latest_version"] <= request.file_version:
                    values["active_job_id"] = None
                if (
                    manifest["visible_version"] is not None
                    and manifest["visible_version"] <= request.file_version
                ):
                    values.update(
                        visible_job_id=None,
                        visible_version=None,
                        visible_generation=None,
                    )
            row = tx.create(
                JOBS,
                {
                    "job_id": job_id,
                    "user_id": self.records.scope.actor_id,
                    "knowledge_id": request.knowledge_id,
                    "file_id": request.file_id,
                    "file_version": request.file_version,
                    "operation": operation,
                    "request_hash": digest,
                    "request_payload": payload,
                    "status": "queued" if operation == "upload" else "cleanup_pending",
                    "owner_id": None,
                    "attempt_id": None,
                    "lease_until": None,
                    "write_started": False,
                    "writer_ended": True,
                    "reconcile_required": False,
                    "chunk_count": None,
                    "error_code": None,
                    "physical_cleanup_complete": False,
                },
                context=context,
            )
            self._patch(tx, FILES, manifest, values, context)
        return job_state(row)

    def inspect(self, lookup, *, context):
        self.authorize(lookup, context=context)
        return job_state(self._job(self.records, lookup, context))

    @staticmethod
    def _current(manifest, job):
        return (
            manifest["active_job_id"] == job["job_id"]
            and job["file_version"] > manifest["tombstone_version"]
        )

    def claim(self, lookup, *, owner_id, lease_seconds, context):
        if (
            not isinstance(owner_id, str)
            or not 0 < len(owner_id) <= 100
            or type(lease_seconds) is not int
            or not 0 < lease_seconds <= 3600
        ):
            raise InvalidInput()
        self.authorize(lookup, context=context)
        # Check ownership before touching a file visible to other users of the tenant.
        self._job(self.records, lookup, context)
        now = self.clock()
        with self.records.transaction(context=context) as tx:
            manifest = self._lock_file(tx, lookup, context)
            row = self._job(tx, lookup, context)
            eligible = row["status"] == "queued" or (
                row["status"] == "running"
                and datetime.fromisoformat(row["lease_until"]) <= now
            )
            if (
                row["operation"] != "upload"
                or not eligible
                or row["write_started"]
                or row["reconcile_required"]
                or not self._current(manifest, row)
            ):
                return None
            return self._patch(
                tx,
                JOBS,
                row,
                {
                    "status": "running",
                    "owner_id": owner_id,
                    "attempt_id": uuid4().hex,
                    "lease_until": (now + timedelta(seconds=lease_seconds)).isoformat(),
                },
                context,
            )

    def _attempt(self, tx, handle, context, *, allow_cancelled=False, lease=True):
        row = self._job(tx, _lookup(handle), context)
        if row["status"] not in (
            {"running", "cancelled", "failed"} if allow_cancelled else {"running"}
        ) or any(
            not row[name] or row[name] != handle[name]
            for name in ("owner_id", "attempt_id")
        ):
            return None
        if lease and datetime.fromisoformat(row["lease_until"]) <= self.clock():
            return None
        return row

    def begin_execution(self, handle, *, context):
        self.authorize(_lookup(handle), context=context)
        with self.records.transaction(context=context) as tx:
            manifest = self._lock_file(tx, _lookup(handle), context)
            row = self._attempt(tx, handle, context)
            if row is None or row["write_started"] or not self._current(manifest, row):
                return False
            self._patch(
                tx,
                JOBS,
                row,
                {
                    "write_started": True,
                    "writer_ended": False,
                    "reconcile_required": True,
                },
                context,
            )
            if manifest["visible_version"] == row["file_version"]:
                self._patch(
                    tx,
                    FILES,
                    manifest,
                    {
                        "visible_job_id": None,
                        "visible_version": None,
                        "visible_generation": None,
                    },
                    context,
                )
        return True

    def renew(self, handle, *, lease_seconds, context):
        if type(lease_seconds) is not int or not 0 < lease_seconds <= 3600:
            raise InvalidInput()
        self.authorize(_lookup(handle), context=context)
        with self.records.transaction(context=context) as tx:
            manifest = self._lock_file(tx, _lookup(handle), context)
            row = self._attempt(tx, handle, context)
            if row is None or not self._current(manifest, row):
                return False
            self._patch(
                tx,
                JOBS,
                row,
                {
                    "lease_until": (
                        self.clock() + timedelta(seconds=lease_seconds)
                    ).isoformat()
                },
                context,
            )
        return True

    def complete(self, handle, *, chunk_count, context):
        if type(chunk_count) is not int or not 0 <= chunk_count <= 2**31 - 1:
            raise InvalidInput()
        self.authorize(_lookup(handle), context=context)
        with self.records.transaction(context=context) as tx:
            manifest = self._lock_file(tx, _lookup(handle), context)
            row = self._attempt(tx, handle, context)
            if (
                row is None
                or not row["write_started"]
                or not self._current(manifest, row)
            ):
                return False
            self._patch(
                tx,
                JOBS,
                row,
                {
                    "status": "completed",
                    "writer_ended": True,
                    "reconcile_required": False,
                    "chunk_count": chunk_count,
                },
                context,
            )
            self._patch(
                tx,
                FILES,
                manifest,
                {
                    "visible_job_id": row["job_id"],
                    "visible_version": row["file_version"],
                    "visible_generation": row["attempt_id"],
                },
                context,
            )
        return True

    def end_attempt(self, handle, *, writer_ended, context):
        if type(writer_ended) is not bool:
            raise InvalidInput()
        # A cancelled or revoked owner may still record its own definitive resource closure.
        with self.records.transaction(context=context) as tx:
            self._lock_file(tx, _lookup(handle), context)
            row = self._attempt(tx, handle, context, allow_cancelled=True, lease=False)
            if row is None:
                return False
            writer_ended = row["writer_ended"] or writer_ended
            self._patch(
                tx,
                JOBS,
                row,
                {
                    "status": "cancelled" if row["status"] == "cancelled" else "failed",
                    "writer_ended": writer_ended,
                    "reconcile_required": not writer_ended,
                    "error_code": "KNOWLEDGE_EXECUTION_FAILED"
                    if writer_ended
                    else "KNOWLEDGE_OUTCOME_UNKNOWN",
                },
                context,
            )
        return True

    def _writers_active(self, tx, reference, context):
        return bool(
            tx.count(
                JOBS,
                RecordQuery(
                    where=_all(
                        self._covered(reference),
                        Comparison("operation", "eq", "upload"),
                        Comparison("write_started", "eq", True),
                        Comparison("writer_ended", "eq", False),
                    )
                ),
                context=context,
            )
        )

    def cleanup_ready(self, lookup, *, context):
        self.authorize(lookup, context=context)
        row = self._job(self.records, lookup, context)
        if row["operation"] != "delete":
            raise InvalidInput()
        with self.records.transaction(context=context) as tx:
            self._lock_file(tx, lookup, context)
            return not self._writers_active(tx, lookup, context)

    def begin_delete(self, lookup, *, owner_id, context):
        if not isinstance(owner_id, str) or not owner_id.strip() or len(owner_id) > 100:
            raise InvalidInput()
        self.authorize(lookup, context=context)
        self._job(self.records, lookup, context)
        with self.records.transaction(context=context) as tx:
            manifest = self._lock_file(tx, lookup, context)
            row = self._job(tx, lookup, context)
            if row["operation"] != "delete":
                raise InvalidInput()
            if manifest["tombstone_version"] < lookup.file_version:
                raise Conflict()
            if (row["status"] != "cleanup_pending" or row["owner_id"] is not None
                    or row["write_started"] or row["reconcile_required"]
                    or self._writers_active(tx, lookup, context)):
                return None
            return self._patch(tx, JOBS, row, {
                "owner_id": owner_id, "attempt_id": uuid4().hex,
                "write_started": True, "writer_ended": False, "reconcile_required": True,
            }, context)

    def finish_delete(self, handle, *, physical_absence_confirmed, context):
        if physical_absence_confirmed is not True:
            raise InvalidInput()
        if not isinstance(handle, dict):
            raise Conflict()
        lookup = _lookup(handle)
        self.authorize(lookup, context=context)
        with self.records.transaction(context=context) as tx:
            manifest = self._lock_file(tx, lookup, context)
            row = self._job(tx, lookup, context)
            if row["operation"] != "delete":
                raise InvalidInput()
            if (manifest["tombstone_version"] < lookup.file_version
                or row["status"] not in {"cleanup_pending", "deleted"}
                or not row["write_started"] or any(
                not row[name] or row[name] != handle.get(name)
                for name in ("owner_id", "attempt_id")
            )):
                raise Conflict()
            if self._writers_active(tx, lookup, context):
                raise Conflict()
            if row["status"] != "deleted":
                row = self._patch(
                    tx,
                    JOBS,
                    row,
                    {"status": "deleted", "physical_cleanup_complete": True,
                     "writer_ended": True, "reconcile_required": False},
                    context,
                )
        return job_state(row)

    def is_visible(self, reference, generation, *, context):
        # Search authorizes its knowledge scope before applying this authoritative final filter.
        row = self._file(self.records, reference, context)
        return bool(
            row
            and row["visible_version"] == reference.file_version
            and row["visible_generation"] == generation
            and reference.file_version > row["tombstone_version"]
        )
