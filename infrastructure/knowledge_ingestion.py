# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own only record handles needed by the Management ingestion coordinator."""

from contextlib import contextmanager

from contracts.knowledge_ingestion import INGESTION_DATASET
from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_ingestion import bind_ingestion_records
from infrastructure.rdb.knowledge_ingestion_dispatch import bind_ingestion_dispatch


@contextmanager
def ingestion_dispatch_ports(*, context):
    engine, records = record_engine(context), None
    try:
        records = bind_ingestion_dispatch(engine)
        yield records
    finally:
        close_owned(
            context, ([records.close] if records is not None else []) + [engine.dispose]
        )


@contextmanager
def knowledge_ingestion_ports(tenant_id, user_id, *, context):
    engine = record_engine(context)
    records = resources = None
    try:
        records = bind_ingestion_records(
            StorageScope("management", tenant_id, user_id, {INGESTION_DATASET}), engine
        )
        resources = bind_cleanse_resources(
            StorageScope(
                "management",
                tenant_id,
                user_id,
                set(TABLES) - {"knowledge_file_history"},
            ),
            engine,
        )
        yield records, resources
    finally:
        close_owned(
            context,
            ([records.close] if records is not None else [])
            + ([resources.close] if resources is not None else [])
            + [engine.dispose],
        )
