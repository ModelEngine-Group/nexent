# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own the record handle for a single actor's unbound local upload operation."""

from contextlib import contextmanager

from contracts.knowledge_ingestion import LOCAL_SOURCE_DATASET
from nexent.storage.models import StorageScope

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.local_source_staging import bind_local_source_staging


@contextmanager
def local_source_staging_port(tenant_id, user_id, *, context):
    engine, records = record_engine(context), None
    try:
        records = bind_local_source_staging(
            StorageScope("management", tenant_id, user_id, {LOCAL_SOURCE_DATASET}),
            engine,
        )
        yield records
    finally:
        close_owned(
            context, ([records.close] if records is not None else []) + [engine.dispose]
        )
