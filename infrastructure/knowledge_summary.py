# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned summary metadata/resource ports with bounded capacity for live DAC in transactions."""

from contextlib import contextmanager

from contracts.knowledge_summary import SUMMARY_DATASET, SUMMARY_MODEL_DATASET
from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_summary import bind_summary_records


@contextmanager
def summary_ports(tenant_id, user_id, *, context, models=False):
    engine, records, resources = record_engine(context, connections=2), None, None
    try:
        names = {SUMMARY_DATASET, SUMMARY_MODEL_DATASET} if models else {SUMMARY_DATASET}
        records = bind_summary_records(StorageScope('management', tenant_id, user_id, names), engine)
        resources = bind_cleanse_resources(StorageScope('management', tenant_id, user_id,
            set(TABLES) - {'cleanse_files', 'knowledge_file_history'}), engine)
        yield records, resources
    finally:
        close_owned(context, ([records.close] if records is not None else [])
                    + ([resources.close] if resources is not None else []) + [engine.dispose])


@contextmanager
def summary_dispatch_ports(*, context):
    from infrastructure.rdb.knowledge_summary_dispatch import bind_summary_dispatch

    engine, records = record_engine(context), None
    try:
        records = bind_summary_dispatch(engine)
        yield records
    finally:
        close_owned(context, ([records.close] if records is not None else []) + [engine.dispose])
