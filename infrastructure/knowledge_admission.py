# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own scoped records and DAC readers for a single admission transaction."""

from contextlib import contextmanager

from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from contracts.knowledge_admission import UPLOAD_ADMISSION_DATASET as FILES
from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_admission import bind_admission_records


@contextmanager
def knowledge_admission_ports(actor, *, context, readonly=False):
    engine, owned = record_engine(context, connections=2), []
    try:
        records = bind_admission_records(StorageScope('management', actor.tenant_id, actor.user_id, {KB, FILES}), engine,
                                         readonly=readonly)
        owned.append(records)
        resources = bind_cleanse_resources(StorageScope('management', actor.tenant_id, actor.user_id, set(TABLES)), engine)
        owned.append(resources)
        yield records, resources
    finally:
        close_owned(context, [port.close for port in reversed(owned)] + [engine.dispose])
