# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read synced document tag matches without exposing assignments or provider queries."""

from contextlib import contextmanager

import sqlalchemy as sa
from contracts.constants.constants import (
    ACTIVE_DELETE_FLAG,
    KNOWLEDGE_DOCUMENT_TYPE,
    SYNCED_STATUS,
)
from nexent.storage.models import StorageScope

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.document_tag_records import TABLES, _table
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

TAG_MATCHES = "hybrid_document_tag_matches"
PROJECTIONS = _table(
    "document_tag_projection", "projection_id",
    ("projection_id", "tenant_id", "provider", "knowledge_base_id", "resource_id", "status"),
)


def bind_hybrid_document_tags(actor, index_name, groups, engine):
    projection = PROJECTIONS
    query = sa.select(projection.c.resource_id, projection.c.tenant_id).where(
        projection.c.provider == "local",
        projection.c.knowledge_base_id == index_name,
        projection.c.status == SYNCED_STATUS,
    )
    if groups:
        assignment = TABLES["assignment"]
        query = query.select_from(projection.join(assignment, sa.and_(
            assignment.c.tenant_id == projection.c.tenant_id,
            assignment.c.resource_id == projection.c.resource_id,
        ))).where(
            assignment.c.resource_type == KNOWLEDGE_DOCUMENT_TYPE,
            assignment.c.delete_flag == ACTIVE_DELETE_FLAG,
            sa.or_(*(sa.and_(assignment.c.definition_id == definition, assignment.c.value_id.in_(values))
                     for definition, values in groups.items())),
        ).group_by(projection.c.resource_id, projection.c.tenant_id).having(
            sa.func.count(sa.distinct(assignment.c.definition_id)) == len(groups),
        )
    records = query.distinct().subquery(TAG_MATCHES)
    # The projection is distinct by resource and tenant; the port binds one tenant.
    records.primary_key.add(records.c.resource_id)
    definition = DatasetDefinition(
        TAG_MATCHES, "resource_id", (FieldDefinition("resource_id", "string"), FieldDefinition("tenant_id", "string")),
        frozenset({"management"}), tenant_field="tenant_id",
    )
    return SQLRecordStore(
        StorageScope("management", actor.tenant_id, actor.user_id, {TAG_MATCHES}),
        DatasetCatalog((definition,)), {TAG_MATCHES: records}, engine, revision_fields={},
    )


@contextmanager
def hybrid_document_tag_ports(actor, index_name, groups, *, context):
    engine, records = record_engine(context), None
    try:
        records = bind_hybrid_document_tags(actor, index_name, groups, engine)
        yield records
    finally:
        close_owned(context, ([records.close] if records is not None else []) + [engine.dispose])
