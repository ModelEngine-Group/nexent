# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime-only scalar mutation receipts and per-KB conditional revision markers."""

import sqlalchemy as sa
from contracts.knowledge_chunk_mutation import CHANGES, STATES
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

metadata = sa.MetaData(schema="nexent")


def audit_columns():
    return (
        sa.Column(
            "revision",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="Conditional metadata revision maintained by RecordStore.",
        ),
        sa.Column(
            "create_time",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="UTC creation audit time.",
        ),
        sa.Column(
            "update_time",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="UTC latest metadata update time.",
        ),
        sa.Column(
            "created_by",
            sa.String(100),
            nullable=False,
            comment="Actual actor that first created this metadata record.",
        ),
        sa.Column(
            "updated_by",
            sa.String(100),
            nullable=False,
            comment="Actual actor performing the latest metadata update.",
        ),
    )


changes = sa.Table(
    "runtime_knowledge_chunk_change_t",
    metadata,
    sa.Column(
        "mutation_id",
        sa.String(64),
        primary_key=True,
        comment="Deterministic digest of tenant, issuer, KB and idempotency key.",
    ),
    sa.Column(
        "tenant_id",
        sa.String(100),
        nullable=False,
        comment="Tenant owning the chunk mutation.",
    ),
    sa.Column(
        "knowledge_id",
        sa.BigInteger,
        nullable=False,
        comment="Existing Management KB identifier; no cross-service foreign key.",
    ),
    sa.Column(
        "user_id",
        sa.String(100),
        nullable=False,
        comment="Actual request issuer; never borrowed from the resource creator.",
    ),
    sa.Column(
        "chunk_id",
        sa.String(1024),
        nullable=False,
        comment="Original opaque logical chunk identifier.",
    ),
    sa.Column(
        "chunk_key",
        sa.String(64),
        nullable=False,
        comment="Digest of tenant, KB and logical chunk ID for bounded active-chunk lookup.",
    ),
    sa.Column(
        "operation",
        sa.String(30),
        nullable=False,
        comment="Requested single-chunk create, update or delete operation.",
    ),
    sa.Column(
        "request_sha256",
        sa.String(64),
        nullable=False,
        comment="Canonical intent digest for idempotency; no raw chunk content is stored.",
    ),
    sa.Column("native_documents", sa.Boolean, nullable=False, server_default=sa.false(),
              comment="Physical mutation target uses the original knowledge index."),
    sa.Column(
        "resource_revision",
        sa.String(64),
        nullable=False,
        comment="Authorized knowledge resource revision at request preparation.",
    ),
    sa.Column(
        "file_id",
        sa.String(32),
        comment="Optional genuine canonical file ID; NULL for standalone chunks.",
    ),
    sa.Column(
        "file_version",
        sa.BigInteger,
        comment="Pinned genuine file version; NULL for standalone chunks.",
    ),
    sa.Column(
        "generation",
        sa.String(256),
        comment="Pinned published vector generation; NULL for standalone chunks.",
    ),
    sa.Column(
        "chunk_index",
        sa.BigInteger,
        comment="Original ordinal within the pinned file generation; NULL for standalone chunks.",
    ),
    sa.Column(
        "status",
        sa.String(30),
        nullable=False,
        comment="reserved, writing, completed, failed or unknown; unknown blocks replay and cleanup.",
    ),
    sa.Column(
        "writer_ended",
        sa.Boolean,
        nullable=False,
        comment="Whether local execution ended; this alone does not resolve an unknown provider write.",
    ),
    sa.Column(
        "count_delta",
        sa.Integer,
        comment="Confirmed single-chunk cardinality effect; NULL until confirmed completion.",
    ),
    sa.Column(
        "commit_epoch",
        sa.BigInteger,
        comment="KB mutation epoch assigned atomically at confirmed completion.",
    ),
    sa.Column(
        "error_code",
        sa.String(100),
        comment="Bounded diagnostic code without provider details or request content.",
    ),
    *audit_columns(),
    sa.CheckConstraint(
        "operation IN ('create','update','delete')", name="ck_chunk_change_operation"
    ),
    sa.CheckConstraint(
        "status IN ('reserved','writing','completed','failed','unknown')",
        name="ck_chunk_change_status",
    ),
    sa.CheckConstraint(
        "knowledge_id > 0 AND revision >= 0", name="ck_chunk_change_revision"
    ),
    sa.CheckConstraint(
        "status <> 'writing' OR NOT writer_ended", name="ck_chunk_change_writing"
    ),
    sa.CheckConstraint(
        "status NOT IN ('reserved','completed','failed') OR writer_ended",
        name="ck_chunk_change_ended",
    ),
    sa.CheckConstraint(
        "(file_id IS NULL AND file_version IS NULL AND generation IS NULL AND chunk_index IS NULL) OR "
        "(file_id IS NOT NULL AND file_version IS NOT NULL AND file_version >= 0 AND generation IS NOT NULL "
        "AND chunk_index IS NOT NULL AND chunk_index >= 0)",
        name="ck_chunk_change_file",
    ),
    sa.CheckConstraint(
        "(status = 'completed' AND count_delta IS NOT NULL AND commit_epoch IS NOT NULL AND commit_epoch > 0) OR "
        "(status <> 'completed' AND count_delta IS NULL AND commit_epoch IS NULL)",
        name="ck_chunk_change_effect",
    ),
    sa.CheckConstraint(
        "count_delta IS NULL OR (operation = 'create' AND count_delta IN (0,1)) OR "
        "(operation = 'update' AND count_delta = 0) OR (operation = 'delete' AND count_delta IN (-1,0))",
        name="ck_chunk_change_delta",
    ),
    comment="Runtime chunk mutation receipts; hashes and scalar effects only, never a replayable payload queue.",
)
states = sa.Table(
    "runtime_knowledge_chunk_state_t",
    metadata,
    sa.Column(
        "state_id",
        sa.String(64),
        primary_key=True,
        comment="Deterministic per-tenant KB mutation marker key.",
    ),
    sa.Column(
        "tenant_id",
        sa.String(100),
        nullable=False,
        comment="Tenant owning the revision and admission marker.",
    ),
    sa.Column(
        "knowledge_id",
        sa.BigInteger,
        nullable=False,
        comment="Existing KB identifier in the owning tenant.",
    ),
    sa.Column(
        "epoch",
        sa.BigInteger,
        nullable=False,
        server_default="0",
        comment="Successful mutation epoch; failures do not advance it.",
    ),
    sa.Column(
        "active_count",
        sa.Integer,
        nullable=False,
        server_default="0",
        comment="Reserved, writing or unknown mutations; confirmed completion or failure releases one admission.",
    ),
    sa.Column("collection_setup", sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
              nullable=True, comment="Current collection setup owner and result fence; NULL permits normal KB lifecycle operations."),
    *audit_columns(),
    sa.UniqueConstraint("tenant_id", "knowledge_id", name="uq_chunk_state_scope"),
    sa.CheckConstraint(
        "knowledge_id > 0 AND epoch >= 0 AND revision >= 0 AND active_count >= 0",
        name="ck_chunk_state_revision",
    ),
    comment="Runtime per-KB CAS admission and successful mutation revision; no file is invented for standalone chunks.",
)
sa.Index(
    "idx_chunk_change_active",
    changes.c.tenant_id,
    changes.c.knowledge_id,
    changes.c.status,
)
sa.Index(
    "idx_chunk_change_key",
    changes.c.tenant_id,
    changes.c.knowledge_id,
    changes.c.chunk_key,
    changes.c.status,
)
sa.Index(
    "idx_chunk_change_file",
    changes.c.tenant_id,
    changes.c.knowledge_id,
    changes.c.file_id,
    changes.c.file_version,
    changes.c.generation,
)
sa.Index(
    "idx_chunk_change_epoch",
    changes.c.tenant_id,
    changes.c.knowledge_id,
    changes.c.commit_epoch,
)


def bind_chunk_mutations(actor, engine, *, writable=True):
    if type(writable) is not bool:
        raise ScopeDenied()
    scope = StorageScope("runtime", actor.tenant_id, actor.user_id, {CHANGES, STATES})
    tables = {CHANGES: changes, STATES: states}
    definitions = []
    for name, table in tables.items():
        definitions.append(
            DatasetDefinition(
                name,
                "mutation_id" if name == CHANGES else "state_id",
                tuple(
                    FieldDefinition(
                        column.name,
                        "boolean"
                        if isinstance(column.type, sa.Boolean)
                        else "integer"
                        if isinstance(column.type, sa.Integer)
                        else "object"
                        if isinstance(column.type, sa.JSON)
                        else "string",
                        nullable=column.nullable,
                    )
                    for column in table.columns
                ),
                frozenset({"runtime"}),
                frozenset({"runtime"}) if writable else frozenset(),
                tenant_field="tenant_id",
            )
        )
    return SQLRecordStore(
        scope,
        DatasetCatalog(tuple(definitions)),
        tables,
        engine,
        revision_fields={name: "revision" for name in tables} if writable else {},
        audit_mappings={
            name: RecordAudit("create_time", "update_time", "created_by", "updated_by")
            for name in tables
        },
    )
