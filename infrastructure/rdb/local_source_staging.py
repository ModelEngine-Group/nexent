# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management-only staging records for local uploads without a knowledge base."""

import sqlalchemy as sa
from contracts.knowledge_ingestion import LOCAL_SOURCE_DATASET as DATASET

from infrastructure.rdb.base import SCHEMA, TableBase
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)


class KnowledgeLocalSource(TableBase):
    __tablename__ = "knowledge_local_source_t"
    __table_args__ = (
        sa.CheckConstraint(
            "state IN ('UPLOADING', 'READY', 'BINDING', 'BOUND')",
            name="ck_local_source_state",
        ),
        sa.CheckConstraint("file_size >= 0", name="ck_local_source_size"),
        sa.Index(
            "idx_local_source_owner_path",
            "tenant_id",
            "created_by",
            "local_source_path",
            postgresql_where=sa.text("delete_flag = 'N'"),
        ),
        {"schema": SCHEMA},
    )
    stage_id = sa.Column(
        sa.String(32),
        primary_key=True,
        comment="Random local upload identity before KB binding.",
    )
    tenant_id = sa.Column(
        sa.String(100),
        nullable=False,
        comment="Tenant owning the unbound local upload.",
    )
    local_source_path = sa.Column(
        sa.String(2048),
        nullable=False,
        comment="Exact Management-owned local upload alias.",
    )
    original_filename = sa.Column(
        sa.String(1024),
        nullable=False,
        comment="Original basename returned to the upload caller.",
    )
    file_size = sa.Column(
        sa.BigInteger, nullable=False, comment="Expected local source size in bytes."
    )
    source_sha256 = sa.Column(
        sa.String(64),
        nullable=False,
        comment="SHA256 of the original local source bytes.",
    )
    state = sa.Column(
        sa.String(30),
        nullable=False,
        comment="Publication and single-target binding state.",
    )
    knowledge_id = sa.Column(
        sa.BigInteger,
        nullable=True,
        comment="Authorized target KB; null before binding.",
    )
    bound_file_id = sa.Column(
        sa.String(32),
        nullable=True,
        comment="Fixed target lifecycle ID; null before binding.",
    )
    version = sa.Column(
        sa.Integer,
        nullable=False,
        server_default="1",
        comment="Revision used for compare-and-set updates.",
    )


table = KnowledgeLocalSource.__table__
for _name, _comment in {
    "created_by": "User owning and permitted to consume the staged upload.",
    "updated_by": "Actor responsible for the latest staging change.",
    "create_time": "UTC time when the staging record was created.",
    "update_time": "UTC time when the staging record was last changed.",
    "delete_flag": "Active row marker N; soft-deleted row marker Y.",
}.items():
    table.c[_name].comment = _comment
    table.c[_name].nullable = False


def staging_catalog():
    integers = {"file_size", "knowledge_id", "version"}
    definition = DatasetDefinition(
        DATASET,
        "stage_id",
        tuple(
            FieldDefinition(
                c.name,
                "integer" if c.name in integers else "string",
                nullable=c.nullable,
            )
            for c in table.c
        ),
        frozenset({"management"}),
        frozenset({"management"}),
        tenant_field="tenant_id",
        active_field="delete_flag",
    )
    return (
        definition,
        table,
        RecordAudit("create_time", "update_time", "created_by", "updated_by"),
    )


def bind_local_source_staging(scope, engine):
    definition, relation, audit = staging_catalog()
    return SQLRecordStore(
        scope,
        DatasetCatalog((definition,)),
        {DATASET: relation},
        engine,
        revision_fields={DATASET: "version"},
        audit_mappings={DATASET: audit},
    )
