# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own one scoped, read-only record handle for a request's document tag display."""

from contextlib import contextmanager

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.document_tag_records import bind_document_tag_records


@contextmanager
def document_tag_ports(actor, *, context):
    engine, records = record_engine(context), None
    try:
        records = bind_document_tag_records(actor, engine)
        yield records
    finally:
        close_owned(
            context, ([records.close] if records is not None else []) + [engine.dispose]
        )
