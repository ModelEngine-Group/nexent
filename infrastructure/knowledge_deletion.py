# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own current-actor deletion records and DAC resources without a system write handle."""

from contextlib import contextmanager

from contracts.knowledge_deletion import DELETION_DATASET
from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_deletion import bind_deletion_records


@contextmanager
def knowledge_deletion_ports(actor, *, context):
    engine, owned = record_engine(context), []
    try:
        records = bind_deletion_records(
            StorageScope("management", actor.tenant_id, actor.user_id, {DELETION_DATASET}), engine,
        )
        owned.append(records)
        resources = bind_cleanse_resources(
            StorageScope("management", actor.tenant_id, actor.user_id, set(TABLES)), engine,
        )
        owned.append(resources)
        yield records, resources
    finally:
        close_owned(context, [record.close for record in reversed(owned)] + [engine.dispose])
