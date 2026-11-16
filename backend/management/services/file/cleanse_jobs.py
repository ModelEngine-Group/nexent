# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Durable cleansing admission, authorization and lease fencing through storage ports."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from contracts.agentos_knowledge import (
    FileCleanseLookup,
    FileCleanseRequest,
    FileCleanseState,
    ObjectReference,
)
from nexent.storage.errors import Conflict, InvalidInput, NotFound
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Junction,
    PageRequest,
    RecordQuery,
)

DATASET = "file_cleanse_jobs"


def both(*terms):
    return Junction("and", terms)


class CleanseJobs:
    def __init__(self, records, *, authorize, parser_version, clock=None):
        if not parser_version or len(parser_version) > 128 or not callable(authorize):
            raise InvalidInput()
        self.records = records
        self.authorize = authorize
        self.parser_version = parser_version
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _owned(self, lookup):
        return both(
            Comparison("job_id", "eq", lookup.job_id),
            Comparison("run_id", "eq", lookup.run_id),
            Comparison("user_id", "eq", self.records.scope.actor_id),
        )

    @staticmethod
    def state(row):
        return FileCleanseState(
            run_id=row["run_id"],
            job_id=row["job_id"],
            status=row["status"],
            artifact=ObjectReference.model_validate(row["artifact"])
            if row["artifact"]
            else None,
            error_code=row["error_code"],
        )

    def _find(self, where, context):
        rows = self.records.query(
            DATASET, RecordQuery(where=where), PageRequest(limit=1), context=context
        ).items
        if not rows:
            raise NotFound()
        return rows[0]

    def submit(self, request: FileCleanseRequest, *, context):
        self.authorize(request)
        payload = request.model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        identity = json.dumps(
            [
                self.records.scope.tenant_id,
                self.records.scope.actor_id,
                request.run_id,
                request.idempotency_key,
            ],
            separators=(",", ":"),
        )
        job_id = uuid5(NAMESPACE_URL, identity).hex
        lookup = FileCleanseLookup(run_id=request.run_id, job_id=job_id)
        try:
            existing = self._find(self._owned(lookup), context)
        except NotFound:
            existing = None
        if existing is None:
            try:
                existing = self.records.create(
                    DATASET,
                    {
                        "job_id": job_id,
                        "user_id": self.records.scope.actor_id,
                        "run_id": request.run_id,
                        "request_hash": digest,
                        "request_payload": payload,
                        "parser_version": self.parser_version,
                        "status": "queued",
                        "reconcile_required": False,
                        "attempt_id": None,
                        "owner_id": None,
                        "lease_until": None,
                        "artifact": None,
                        "error_code": None,
                    },
                    context=context,
                )
            except Conflict:
                existing = self._find(self._owned(lookup), context)
        if existing["request_hash"] != digest:
            raise Conflict()
        return self.state(existing)

    def inspect(self, lookup, *, context):
        self.authorize(lookup)
        return self.state(self._find(self._owned(lookup), context))

    def cancel(self, lookup, *, context):
        self.authorize(lookup)
        with self.records.transaction(context=context) as tx:
            tx.claim(
                DATASET,
                RecordQuery(
                    where=both(
                        self._owned(lookup),
                        Comparison("status", "in", ["queued", "running"]),
                    )
                ),
                FieldPatch(
                    set_values={
                        "status": "cancelled",
                        "owner_id": None,
                        "attempt_id": None,
                        "lease_until": None,
                    }
                ),
                limit=1,
                context=context,
            )
        return self.state(self._find(self._owned(lookup), context))

    def claim(self, owner_id, *, lease_seconds, job_id=None, context):
        if (
            not isinstance(owner_id, str)
            or not 0 < len(owner_id) <= 100
            or type(lease_seconds) is not int
            or not 0 < lease_seconds <= 3600
        ):
            raise InvalidInput()
        now = self.clock()
        candidates = Junction(
            "or",
            (
                Comparison("status", "eq", "queued"),
                both(
                    Comparison("status", "eq", "running"),
                    Comparison("lease_until", "lte", now.isoformat()),
                ),
            ),
        )
        candidates = both(candidates, Comparison("reconcile_required", "eq", False))
        if job_id is not None:
            candidates = both(candidates, Comparison("job_id", "eq", job_id))
        with self.records.transaction(context=context) as tx:
            rows = tx.claim(
                DATASET,
                RecordQuery(where=candidates),
                FieldPatch(
                    set_values={
                        "status": "running",
                        "attempt_id": uuid4().hex,
                        "owner_id": owner_id,
                        "lease_until": (
                            now + timedelta(seconds=lease_seconds)
                        ).isoformat(),
                    }
                ),
                limit=1,
                context=context,
            )
        return rows[0] if rows else None

    def transition(
        self,
        handle,
        *,
        status,
        artifact=None,
        error_code=None,
        lease_seconds=None,
        context,
    ):
        if status not in {"running", "completed", "failed"}:
            raise InvalidInput()
        if status == "completed" and not isinstance(artifact, ObjectReference):
            raise InvalidInput()
        if status != "completed" and artifact is not None:
            raise InvalidInput()
        if error_code is not None and (
            not isinstance(error_code, str) or len(error_code) > 128
        ):
            raise InvalidInput()
        now = self.clock()
        where = both(
            Comparison("job_id", "eq", handle["job_id"]),
            Comparison("status", "eq", "running"),
            Comparison("owner_id", "eq", handle["owner_id"]),
            Comparison("attempt_id", "eq", handle["attempt_id"]),
            Comparison("lease_until", "gt", now.isoformat()),
        )
        values = {
            "status": status,
            "artifact": artifact.model_dump(mode="json") if artifact else None,
            "error_code": error_code,
        }
        if status == "running":
            if type(lease_seconds) is not int or not 0 < lease_seconds <= 3600:
                raise InvalidInput()
            values["lease_until"] = (now + timedelta(seconds=lease_seconds)).isoformat()
        else:
            values["lease_until"] = None
        with self.records.transaction(context=context) as tx:
            rows = tx.claim(
                DATASET,
                RecordQuery(where=where),
                FieldPatch(set_values=values),
                limit=1,
                context=context,
            )
        return bool(rows)

    def mark_uncertain(self, handle, *, context):
        where = both(
            Comparison("job_id", "eq", handle["job_id"]),
            Comparison("status", "eq", "running"),
            Comparison("owner_id", "eq", handle["owner_id"]),
            Comparison("attempt_id", "eq", handle["attempt_id"]),
        )
        with self.records.transaction(context=context) as tx:
            rows = tx.claim(
                DATASET,
                RecordQuery(where=where),
                FieldPatch(
                    set_values={
                        "reconcile_required": True,
                        "error_code": "CLEANSE_OUTCOME_UNKNOWN",
                    }
                ),
                limit=1,
                context=context,
            )
        return bool(rows)

    def ready(self, *, limit=100, context):
        where = both(
            Comparison("reconcile_required", "eq", False),
            Junction(
                "or",
                (
                    Comparison("status", "eq", "queued"),
                    both(
                        Comparison("status", "eq", "running"),
                        Comparison("lease_until", "lte", self.clock().isoformat()),
                    ),
                ),
            ),
        )
        return self.records.query(
            DATASET, RecordQuery(where=where), PageRequest(limit=limit), context=context
        ).items
