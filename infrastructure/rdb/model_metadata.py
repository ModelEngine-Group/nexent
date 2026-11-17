# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Credential-free Runtime model catalog backed by the scoped RecordStore."""

import sqlalchemy as sa
from nexent.storage.models import (
    Comparison,
    PageRequest,
    RecordQuery,
    Sort,
    StorageScope,
)

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.model_record import ModelRecord
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

DATASET = "model_metadata"
FIELDS = ("model_id", "tenant_id", "delete_flag", "model_type", "display_name", "model_repo", "model_name",
          "update_time", "create_time", "capability_profile_version")


def bind_model_metadata(scope, engine):
    source = ModelRecord.__table__
    table = sa.select(*(sa.cast(source.c[name], sa.String).label(name) if name in {"create_time", "update_time"}
                        else source.c[name] for name in FIELDS)).subquery("model_metadata")
    definition = DatasetDefinition(DATASET, "model_id", tuple(
        FieldDefinition(name, "integer" if name == "model_id" else "string", nullable=source.c[name].nullable)
        for name in FIELDS), frozenset({"runtime"}), tenant_field="tenant_id", active_field="delete_flag")
    return SQLRecordStore(scope, DatasetCatalog((definition,)), {DATASET: table}, engine, revision_fields={})


def read_model_metadata(query, actor, *, context):
    engine, records = record_engine(context), None
    try:
        records = bind_model_metadata(StorageScope("runtime", actor.tenant_id, actor.user_id, {DATASET}), engine)
        return records.query(DATASET, RecordQuery(where=(Comparison("model_type", "eq", query.model_type)
                                                        if query.model_type else None), order_by=(Sort("create_time", True), Sort("model_id", True))),
                             PageRequest(query.page_size, query.cursor), context=context)
    finally:
        close_owned(context, ([records.close] if records is not None else []) + [engine.dispose])
