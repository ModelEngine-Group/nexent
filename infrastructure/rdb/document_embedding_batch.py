# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read credential-free tenant embedding batch settings through StorageInterface."""

import sqlalchemy as sa
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied
from nexent.storage.models import Comparison, PageRequest, RecordQuery, StorageScope

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.model_record import ModelRecord
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.rdb.tenant_config_record import TenantConfig
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

SLOTS = "document_embedding_slots"
MODELS = "document_embedding_batches"
DATASETS = frozenset({SLOTS, MODELS})
slots, models = TenantConfig.__table__, ModelRecord.__table__


def bind_document_embedding_settings(scope, engine):
    if (scope.system or scope.service_role != "runtime" or scope.namespaces != DATASETS or scope.resource_prefix):
        raise ScopeDenied()
    tables = {
        SLOTS: sa.select(*(slots.c[name] for name in
            ("tenant_config_id", "tenant_id", "config_key", "config_value", "delete_flag"))).subquery(SLOTS),
        MODELS: sa.select(*(models.c[name] for name in
            ("model_id", "tenant_id", "chunk_batch", "delete_flag"))).subquery(MODELS),
    }
    definitions = tuple(DatasetDefinition(name, "tenant_config_id" if name == SLOTS else "model_id",
        tuple(FieldDefinition(column.name, "integer" if column.name in {"tenant_config_id", "model_id", "chunk_batch"}
                              else "string", nullable=column.nullable) for column in table.c),
        frozenset({"runtime"}), tenant_field="tenant_id", active_field="delete_flag")
        for name, table in tables.items())
    return SQLRecordStore(scope, DatasetCatalog(definitions), tables, engine, revision_fields={})


def read_document_embedding_batch(actor, resource_tenant_id, model_type, *, context):
    if resource_tenant_id not in {actor.tenant_id, ASSET_OWNER_TENANT_ID}:
        raise ScopeDenied()
    if model_type not in {"embedding", "multi_embedding"}:
        raise InvalidInput()
    context.remaining()
    engine, records = record_engine(context), None
    try:
        records = bind_document_embedding_settings(
            StorageScope("runtime", resource_tenant_id, actor.user_id, DATASETS), engine)
        key = "EMBEDDING_ID" if model_type == "embedding" else "MULTI_EMBEDDING_ID"
        page = records.query(SLOTS, RecordQuery(where=Comparison("config_key", "eq", key)),
                             PageRequest(limit=2), context=context)
        if len(page.items) > 1 or page.next_cursor:
            raise Conflict()
        if not page.items:
            return 10
        try:
            model_id = int(page.items[0]["config_value"])
        except (ValueError, TypeError):
            return 10
        if model_id <= 0:
            return 10
        model = records.get(MODELS, model_id, context=context)
        batch = model.get("chunk_batch") if model else None
        if batch is None:
            return 10
        if type(batch) is not int or batch <= 0:
            raise InvalidInput()
        return min(batch, 64)
    finally:
        close_owned(context, ([records.close] if records is not None else []) + [engine.dispose])
