# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management ledger queries and release policy over neutral storage records."""

from contextlib import contextmanager
from time import monotonic
from uuid import uuid4

from contracts.knowledge import (
    STORAGE_LEDGER_DATASET as LEDGER,
)
from contracts.knowledge import (
    STORAGE_LEDGER_HISTORY_DATASET as HISTORY,
)
from contracts.knowledge import (
    STORAGE_LEDGER_OWNER_DATASET as LOOKUP,
)
from nexent.storage.errors import Conflict
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Junction,
    OperationContext,
    PageRequest,
    RecordQuery,
    Revision,
    Sort,
)

from infrastructure.storage_ledger import ledger_record_ports


def _context():
    return OperationContext("knowledge-ledger-" + uuid4().hex, monotonic() + 10)


@contextmanager
def _operation(tenant_id, actor_id=None, *, identity=None, context=None):
    context = context or _context()
    with (
        ledger_record_ports(
            tenant_id, actor_id or "storage-ledger", context=context, identity=identity
        ) as root,
        root.transaction(context=context) as records,
    ):
        yield records, context


def _active(*terms):
    return Junction("and", (Comparison("status", "eq", "COMMITTED"), *terms))


def _identity(bucket, key):
    return Junction(
        "and",
        (Comparison("bucket_name", "eq", bucket), Comparison("object_name", "eq", key)),
    )


def _one(records, dataset, where, context):
    page = records.query(
        dataset, RecordQuery(where=where), PageRequest(limit=2), context=context
    )
    if len(page.items) > 1 or page.next_cursor:
        raise Conflict(operation_id=context.operation_id)
    return page.items[0] if page.items else None


def _all(records, where, context, *, fields=()):
    last_id = None
    cursor = None
    projection = tuple(dict.fromkeys((*fields, "storage_object_id"))) if fields else ()
    while True:
        current = (
            where
            if last_id is None
            else Junction(
                "and", (where, Comparison("storage_object_id", "gt", last_id))
            )
        )
        page = records.query(
            LEDGER,
            RecordQuery(
                where=current, fields=projection, order_by=(Sort("storage_object_id"),)
            ),
            PageRequest(limit=500, cursor=cursor),
            context=context,
        )
        yield from page.items
        if page.next_cursor is None:
            return
        if page.items:
            last_id = page.items[-1]["storage_object_id"]
            cursor = None
        else:
            cursor = page.next_cursor


def _chunks(values):
    values = list(values)
    for offset in range(0, len(values), 1000):
        yield values[offset : offset + 1000]


def get_storage_object(tenant_id, bucket_name, object_name, *, include_deleted=False):
    with _operation(tenant_id) as (records, context):
        dataset = HISTORY if include_deleted else LEDGER
        where = _identity(bucket_name, object_name)
        return _one(
            records, dataset, where if include_deleted else _active(where), context
        )


def get_storage_object_by_identity(bucket_name, object_name, *, include_deleted=False):
    """Discover one exact object owner; callers must authorize its tenant and KB."""
    with _operation(None, identity=(bucket_name, object_name, include_deleted)) as (
        records,
        context,
    ):
        return _one(records, LOOKUP, None, context)


def aggregate_committed_bytes_by_kb(tenant_id, knowledge_ids=None):
    """Return one consistent active-tenant grouping without truncating large filters."""
    if knowledge_ids is not None and not knowledge_ids:
        return {}
    result = {}
    with _operation(tenant_id) as (records, context):
        filters = [None] if knowledge_ids is None else _chunks(knowledge_ids)
        for selected in filters:
            where = (
                _active()
                if selected is None
                else _active(Comparison("knowledge_id", "in", selected))
            )
            totals = records.sum_by(
                LEDGER,
                "raw_bytes",
                "knowledge_id",
                RecordQuery(where=where),
                context=context,
            )
            result.update({int(key): int(value) for key, value in totals.items()})
    return result


def get_committed_source_bytes_by_object_names(
    tenant_id, knowledge_id, bucket_name, object_names
):
    if not object_names:
        return {}
    result = {}
    with _operation(tenant_id) as (records, context):
        for selected in _chunks(object_names):
            where = _active(
                Comparison("knowledge_id", "eq", knowledge_id),
                Comparison("bucket_name", "eq", bucket_name),
                Comparison("object_name", "in", selected),
            )
            result.update(
                {
                    row["object_name"]: row["raw_bytes"]
                    for row in _all(
                        records, where, context, fields=("object_name", "raw_bytes")
                    )
                }
            )
    return result


def get_tenant_committed_bytes(tenant_id):
    with _operation(tenant_id) as (records, context):
        return records.sum(
            LEDGER, "raw_bytes", RecordQuery(where=_active()), context=context
        )


def list_committed_storage_objects(tenant_id, knowledge_id=None):
    with _operation(tenant_id) as (records, context):
        where = (
            _active()
            if knowledge_id is None
            else _active(Comparison("knowledge_id", "eq", knowledge_id))
        )
        return list(_all(records, where, context))


def mark_storage_object_deleted(tenant_id, bucket_name, object_name, updated_by=None):
    """Release a charge only after the caller confirms physical deletion; unknown commits propagate."""
    context = _context()
    for attempt in range(2):
        try:
            with _operation(tenant_id, updated_by, context=context) as (
                records,
                context,
            ):
                row = _one(
                    records, HISTORY, _identity(bucket_name, object_name), context
                )
                if row is None:
                    return False
                if row["delete_flag"] == "Y" or row["status"] == "DELETED":
                    return True
                receipt = records.patch(
                    LEDGER,
                    row["storage_object_id"],
                    FieldPatch(set_values={"status": "DELETED"}),
                    expected=Revision(str(row["version"])),
                    context=context,
                )
                if not receipt.matched:
                    raise Conflict(operation_id=context.operation_id)
                deleted = records.delete(
                    LEDGER,
                    row["storage_object_id"],
                    expected=receipt.revision,
                    context=context,
                )
                if not deleted.deleted:
                    raise Conflict(operation_id=context.operation_id)
                return True
        except Conflict:
            if attempt:
                raise
    raise AssertionError("Bounded ledger release must return or raise")
