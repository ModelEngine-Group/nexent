# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Close every record handle and engine owned by a Runtime mutation operation."""

from contextlib import contextmanager

from contracts.knowledge_chunk_mutation import CHANGES, STATES
from nexent.storage.models import StorageScope

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_lifecycle import bind_knowledge_lifecycle


@contextmanager
def knowledge_chunk_mutation_ports(actor, *, context):
    engine, records = record_engine(context), None
    try:
        scope = StorageScope("runtime", actor.tenant_id, actor.user_id, {CHANGES, STATES})
        records = bind_knowledge_lifecycle(scope, engine, mode="mutation")
        yield records
    finally:
        close_owned(
            context, ([records.close] if records is not None else []) + [engine.dispose]
        )
