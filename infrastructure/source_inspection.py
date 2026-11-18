# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned read-only source inspection ports retain the actual selected operator."""

from contextlib import contextmanager

from contracts.knowledge_maintenance import INSPECTION_FILES, INSPECTION_LEDGER
from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.source_inspection import bind_source_inspection_records


@contextmanager
def source_inspection_ports(actor, knowledge_id, *, context):
    engine, records, resources = record_engine(context), None, None
    try:
        records = bind_source_inspection_records(StorageScope('management', actor.tenant_id, actor.user_id,
            {INSPECTION_FILES, INSPECTION_LEDGER}), knowledge_id, engine)
        resources = bind_cleanse_resources(StorageScope('management', actor.tenant_id, actor.user_id,
            set(TABLES) - {'cleanse_files', 'knowledge_file_history'}), engine)
        yield records, resources
    finally:
        close_owned(context, ([records.close] if records else []) + ([resources.close] if resources else []) + [engine.dispose])
