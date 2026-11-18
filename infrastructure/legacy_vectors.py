# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Only one proven historical index owner can obtain a legacy read-only record port."""

from contextlib import contextmanager

from contracts.knowledge_maintenance import (
    LEGACY_DOCUMENTS,
    LEGACY_INDEX_OWNER,
    LEGACY_VECTOR_METADATA,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.knowledge_vectors import _configured_client
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.legacy_index_owner import bind_legacy_index_owner
from infrastructure.vdb.legacy_records import LegacyVectorRecords


@contextmanager
def legacy_vector_records(actor, knowledge_id, index_name, *, context, cancellation_scope=None):
    engine, ownership, records = record_engine(context), None, None
    try:
        ownership = bind_legacy_index_owner(actor, knowledge_id, index_name, engine)
        row = ownership.get(LEGACY_INDEX_OWNER, index_name, context=context)
        if row is None or row['owner_count'] != 1 or row['selected_owner_count'] != 1:
            raise ScopeDenied()
        records = LegacyVectorRecords(StorageScope('management', actor.tenant_id, actor.user_id,
            {LEGACY_DOCUMENTS, LEGACY_VECTOR_METADATA}), index_name, _configured_client, cancellation_scope=cancellation_scope)
        yield records
    finally:
        close_owned(context, ([records.close] if records else []) + ([ownership.close] if ownership else []) + [engine.dispose])
