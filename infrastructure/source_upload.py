# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Finite, process-local storage bindings for one preallocated KB source upload."""

from contextlib import contextmanager

from nexent.storage.models import StorageScope

from infrastructure.object_storage.composition import bind_source_objects
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.interrupted_uploads import bind_interrupted_uploads
from infrastructure.rdb.source_binding import DATASET
from infrastructure.rdb.source_candidates import bind_source_candidates
from infrastructure.rdb.upload_records import LEDGER, QUOTA, bind_upload_records


@contextmanager
def _source_ports(record, *, actor_id, writable, context, with_policy=False):
    engine = record_engine(context)
    records = objects = None
    try:
        namespaces = {DATASET, LEDGER, QUOTA} if with_policy else {DATASET, LEDGER}
        scope = StorageScope("management", record["tenant_id"], actor_id, namespaces)
        records = bind_upload_records(scope, engine, with_policy=with_policy)
        objects = bind_source_objects(
            record["tenant_id"],
            actor_id,
            record["object_name"],
            record["bucket_name"],
            writable=writable,
        )
        yield records, objects
    finally:
        cleanup = [engine.dispose]
        if records is not None:
            cleanup.insert(0, records.close)
        if objects is not None:
            cleanup.insert(0, objects.close)
        close_owned(context, cleanup)


def source_upload_ports(record, *, context):
    return _source_ports(
        record, actor_id=record["created_by"], writable=True, context=context
    )


def source_recovery_ports(record, *, context):
    return _source_ports(
        record,
        actor_id="source-reconciliation",
        writable=False,
        context=context,
        with_policy=True,
    )


@contextmanager
def source_candidate_ports(owner_service, *, context):
    engine = record_engine(context)
    candidates = None
    try:
        candidates = bind_source_candidates(owner_service, engine)
        yield candidates
    finally:
        callbacks = [engine.dispose]
        if candidates is not None:
            callbacks.insert(0, candidates.close)
        close_owned(context, callbacks)


@contextmanager
def interrupted_upload_ports(owner, *, context, record=None, expected_status="UPLOADING"):
    engine = record_engine(context)
    records = None
    try:
        records = bind_interrupted_uploads(owner, engine, record=record, expected_status=expected_status)
        yield records
    finally:
        close_owned(context, ([records.close] if records is not None else []) + [engine.dispose])
