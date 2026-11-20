# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own current-actor deletion records and DAC resources without a system write handle."""

from contextlib import contextmanager

from contracts.knowledge import STORAGE_LEDGER_DATASET, STORAGE_LEDGER_HISTORY_DATASET
from contracts.knowledge_deletion import DELETION_DATASET, DELETION_KNOWLEDGE_DATASET
from contracts.knowledge_ingestion import ACTIVE_LEGACY_FILE_IDS
from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_deletion import bind_deletion_records


@contextmanager
def knowledge_deletion_ports(actor, *, context):
    engine, owned = record_engine(context), []
    try:
        records = bind_deletion_records(
            StorageScope("management", actor.tenant_id, actor.user_id,
                         {DELETION_DATASET, DELETION_KNOWLEDGE_DATASET, STORAGE_LEDGER_DATASET, STORAGE_LEDGER_HISTORY_DATASET,
                          ACTIVE_LEGACY_FILE_IDS}), engine,
        )
        owned.append(records)
        resources = bind_cleanse_resources(
            StorageScope("management", actor.tenant_id, actor.user_id, set(TABLES)), engine,
        )
        owned.append(resources)
        yield records, resources
    finally:
        close_owned(context, [record.close for record in reversed(owned)] + [engine.dispose])


@contextmanager
def deletion_source_objects(row, actor, *, context):
    from nexent.storage.errors import ScopeDenied

    from infrastructure.object_storage.composition import bind_source_objects

    context.remaining()
    if row['tenant_id'] != actor.tenant_id:
        raise ScopeDenied()
    if row['object_name'] is None:
        yield None
        return
    objects = bind_source_objects(actor.tenant_id, actor.user_id, row['object_name'], row['bucket_name'])
    try:
        yield objects
    finally:
        close_owned(context, [objects.close])


@contextmanager
def deletion_preview_objects(row, actor, key, *, context):
    from nexent.storage.errors import ScopeDenied

    from infrastructure.object_storage.composition import bind_source_objects

    context.remaining()
    if row['tenant_id'] != actor.tenant_id or not key.startswith('preview/converted/'):
        raise ScopeDenied()
    objects = bind_source_objects(actor.tenant_id, actor.user_id, key, row['bucket_name'])
    try:
        yield objects
    finally:
        close_owned(context, [objects.close])
