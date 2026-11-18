# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Close every record handle and engine owned by a Runtime mutation operation."""

from contextlib import contextmanager

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_chunk_mutations import bind_chunk_mutations


@contextmanager
def knowledge_chunk_mutation_ports(actor, *, context, writable=True):
    engine, records = record_engine(context), None
    try:
        records = bind_chunk_mutations(actor, engine, writable=writable)
        yield records
    finally:
        close_owned(
            context, ([records.close] if records is not None else []) + [engine.dispose]
        )
