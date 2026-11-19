# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind scoped catalog records and the original creation serialization policy."""

from contextlib import contextmanager

import sqlalchemy as sa
from nexent.storage.models import StorageScope

from infrastructure.rdb.account_record import UserAccount, UserTenant
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_search_records import KnowledgeRecord
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

CATALOG = "knowledge_catalog"
ACTOR = "knowledge_catalog_actor"
knowledge = KnowledgeRecord.__table__.to_metadata(sa.MetaData())
knowledge.append_column(
    sa.Column("version", sa.Integer, nullable=False, server_default="0")
)
FIELDS = [
    "knowledge_id",
    "tenant_id",
    "index_name",
    "knowledge_name",
    "knowledge_describe",
    "knowledge_sources",
    "embedding_model_name",
    "embedding_model_id",
    "group_ids",
    "ingroup_permission",
    "preserve_source_file",
    "quota_limit_bytes",
    "deletion_request",
    "delete_flag",
    "version",
    "create_time",
    "update_time",
    "created_by",
    "updated_by",
]


def bind_knowledge_catalog(actor, engine, *, writable=False, knowledge_name=None):
    scope = StorageScope("management", actor.tenant_id, actor.user_id, {CATALOG, ACTOR} if writable else {CATALOG})
    accounts, members = UserAccount.__table__, UserTenant.__table__
    roles = (
        sa.select(members.c.user_tenant_id, members.c.tenant_id, accounts.c.user_roles)
        .select_from(members.join(accounts, members.c.user_id == accounts.c.user_id))
        .where(
            members.c.user_id == actor.user_id,
            members.c.delete_flag == "N",
            accounts.c.delete_flag == "N",
        )
        .subquery(ACTOR)
    )

    def field(name):
        column = knowledge.c[name]
        kind = (
            "boolean"
            if isinstance(column.type, sa.Boolean)
            else "integer"
            if isinstance(column.type, sa.Integer)
            else ("object" if isinstance(column.type, sa.JSON) else "string")
        )
        return FieldDefinition(name, kind, nullable=column.nullable)

    definitions = (
        DatasetDefinition(
            CATALOG,
            "knowledge_id",
            tuple(field(name) for name in FIELDS),
            frozenset({"management"}),
            frozenset({"management"}) if writable else frozenset(),
            tenant_field="tenant_id",
            active_field="delete_flag",
        ),
        DatasetDefinition(
            ACTOR,
            "user_tenant_id",
            (
                FieldDefinition("user_tenant_id", "integer"),
                FieldDefinition("tenant_id", "string"),
                FieldDefinition("user_roles", "array"),
            ),
            frozenset({"management"}),
            tenant_field="tenant_id",
        ),
    )
    locks = ()
    if writable:
        locks = (
            f"knowledge-tenant-limit:{actor.tenant_id}",
            f"knowledge-user-limit:{actor.tenant_id}:{actor.user_id}",
        )
        if knowledge_name:
            locks += (f"knowledge-name:{actor.tenant_id}:{knowledge_name}",)
    return SQLRecordStore(
        scope,
        DatasetCatalog(definitions if writable else definitions[:1]),
        {CATALOG: knowledge, ACTOR: roles} if writable else {CATALOG: knowledge},
        engine,
        revision_fields={CATALOG: "version"},
        audit_mappings={
            CATALOG: RecordAudit(
                "create_time", "update_time", "created_by", "updated_by"
            )
        },
        transaction_locks=locks,
    )


@contextmanager
def knowledge_catalog_ports(actor, *, context, writable=False, knowledge_name=None):
    engine, records = record_engine(context), None
    try:
        records = bind_knowledge_catalog(
            actor, engine, writable=writable, knowledge_name=knowledge_name
        )
        yield records
    finally:
        close_owned(
            context, ([records.close] if records is not None else []) + [engine.dispose]
        )
