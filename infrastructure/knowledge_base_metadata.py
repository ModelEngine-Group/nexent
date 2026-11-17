# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own one engine and scoped ports for a KB metadata finalization transaction."""

from contextlib import contextmanager

from contracts.knowledge_admission import (
    KNOWLEDGE_ADMISSION_DATASET,
    UPLOAD_ADMISSION_DATASET,
)
from contracts.knowledge_base_metadata import (
    KNOWLEDGE_CONVERSATIONS,
    KNOWLEDGE_TAG_ASSIGNMENTS,
    KNOWLEDGE_TAG_PROJECTIONS,
    KNOWLEDGE_TOOL_BINDINGS,
)
from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_base_metadata import bind_base_metadata_records


@contextmanager
def knowledge_base_metadata_ports(actor, *, context):
    engine, owned = record_engine(context, connections=2), []
    try:
        scope = StorageScope('management', actor.tenant_id, actor.user_id, {
            KNOWLEDGE_ADMISSION_DATASET, UPLOAD_ADMISSION_DATASET, KNOWLEDGE_CONVERSATIONS,
            KNOWLEDGE_TAG_ASSIGNMENTS, KNOWLEDGE_TAG_PROJECTIONS, KNOWLEDGE_TOOL_BINDINGS,
        })
        records = bind_base_metadata_records(scope, engine)
        owned.append(records)
        resources = bind_cleanse_resources(StorageScope('management', actor.tenant_id, actor.user_id, set(TABLES)), engine)
        owned.append(resources)
        yield records, resources
    finally:
        close_owned(context, [port.close for port in reversed(owned)] + [engine.dispose])
