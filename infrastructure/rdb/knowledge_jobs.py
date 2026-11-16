# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime-owned durable KB jobs and authoritative per-file visibility catalogs."""

from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.rdb.base import TableBase
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

JOBS = "runtime_knowledge_jobs"
FILES = "runtime_knowledge_files"


class RuntimeKnowledgeJob(TableBase):
    __tablename__ = "runtime_knowledge_job_t"
    __table_args__: ClassVar[dict] = {
        "schema": "nexent",
        "comment": "Runtime KB execution and deletion requests with durable writer fencing.",
    }

    job_id = sa.Column(
        sa.String(32),
        primary_key=True,
        comment="Deterministic UUID technical identifier for one authorized idempotent request.",
    )
    tenant_id = sa.Column(
        sa.String(100), nullable=False, comment="Tenant owning the KB request."
    )
    user_id = sa.Column(
        sa.String(100),
        nullable=False,
        comment="User holding inspect and execution ownership of this request.",
    )
    knowledge_id = sa.Column(
        sa.Integer,
        nullable=False,
        comment="Logical knowledge resource reference, validated by Runtime authorization.",
    )
    file_id = sa.Column(
        sa.String(32),
        nullable=False,
        comment="Stable file reference authorized for the knowledge resource.",
    )
    file_version = sa.Column(
        sa.Integer,
        nullable=False,
        comment="Authorized file generation affected by this request.",
    )
    operation = sa.Column(
        sa.String(30),
        nullable=False,
        comment="Upload execution or deletion cleanup operation.",
    )
    request_hash = sa.Column(
        sa.String(64),
        nullable=False,
        comment="SHA256 of the canonical strict operation payload.",
    )
    request_payload = sa.Column(
        sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
        nullable=False,
        comment="Strict upload or delete DTO, at most 16 KiB, without credentials or document bytes.",
    )
    status = sa.Column(
        sa.String(30),
        nullable=False,
        comment="Queued, running, completed, failed, cancelled, cleanup_pending or deleted outcome.",
    )
    owner_id = sa.Column(
        sa.String(100),
        nullable=True,
        comment="Runtime instance currently owning this execution attempt.",
    )
    attempt_id = sa.Column(
        sa.String(32),
        nullable=True,
        comment="Unique fencing token used as vector generation by the current attempt.",
    )
    lease_until = sa.Column(
        sa.DateTime(timezone=True),
        nullable=True,
        comment="UTC deadline of the current owner's execution lease.",
    )
    write_started = sa.Column(
        sa.Boolean,
        nullable=False,
        comment="Execution intent committed before model or vector side effects begin.",
    )
    writer_ended = sa.Column(
        sa.Boolean,
        nullable=False,
        comment="Explicit confirmation that no model or storage request from this attempt can write later.",
    )
    reconcile_required = sa.Column(
        sa.Boolean,
        nullable=False,
        comment="Unconfirmed execution or write outcome forbids automatic replay.",
    )
    chunk_count = sa.Column(
        sa.Integer,
        nullable=True,
        comment="Number of confirmed chunks published by a completed upload.",
    )
    error_code = sa.Column(
        sa.String(128),
        nullable=True,
        comment="Stable sanitized execution failure code without provider details.",
    )
    physical_cleanup_complete = sa.Column(
        sa.Boolean,
        nullable=False,
        comment="Delete request has confirmed physical absence after all covered writers ended.",
    )
    revision = sa.Column(
        sa.Integer,
        nullable=False,
        server_default="1",
        comment="RecordStore optimistic concurrency revision.",
    )


class RuntimeKnowledgeFile(TableBase):
    __tablename__ = "runtime_knowledge_file_t"
    __table_args__: ClassVar[dict] = {
        "schema": "nexent",
        "comment": "Authoritative Runtime KB file visibility and deletion high-water mark.",
    }

    record_id = sa.Column(
        sa.String(32),
        primary_key=True,
        comment="Deterministic UUID technical identifier derived from tenant, knowledge and file.",
    )
    tenant_id = sa.Column(
        sa.String(100),
        nullable=False,
        comment="Tenant owning the file visibility record.",
    )
    knowledge_id = sa.Column(
        sa.Integer,
        nullable=False,
        comment="Logical authorized knowledge resource reference.",
    )
    file_id = sa.Column(
        sa.String(32), nullable=False, comment="Stable authorized file reference."
    )
    latest_version = sa.Column(
        sa.Integer,
        nullable=False,
        comment="Highest admitted upload version, or -1 before the first upload.",
    )
    active_job_id = sa.Column(
        sa.String(32),
        nullable=True,
        comment="Current upload request allowed to begin execution or publish visibility.",
    )
    visible_job_id = sa.Column(
        sa.String(32),
        nullable=True,
        comment="Completed upload request providing the authoritative visible generation.",
    )
    visible_version = sa.Column(
        sa.Integer,
        nullable=True,
        comment="Published file version; null while no version is visible.",
    )
    visible_generation = sa.Column(
        sa.String(32),
        nullable=True,
        comment="Attempt token required on returned vectors for the visible version.",
    )
    tombstone_version = sa.Column(
        sa.Integer,
        nullable=False,
        comment="Deletion high-water mark; versions at or below it cannot publish again.",
    )
    revision = sa.Column(
        sa.Integer,
        nullable=False,
        server_default="1",
        comment="RecordStore CAS serialization revision for file lifecycle decisions.",
    )


jobs, files = RuntimeKnowledgeJob.__table__, RuntimeKnowledgeFile.__table__
for table in (jobs, files):
    for name, comment in {
        "create_time": "UTC admission time of this Runtime record.",
        "update_time": "UTC time of the latest Runtime lifecycle update.",
        "created_by": "Trusted actor creating the Runtime record.",
        "updated_by": "Trusted actor performing the latest lifecycle update.",
        "delete_flag": "Soft deletion marker, N active and Y deleted; tombstones remain active.",
    }.items():
        table.c[name].comment = comment
        table.c[name].nullable = False
    table.c.delete_flag.server_default = sa.DefaultClause("N")
    sa.CheckConstraint(
        "revision > 0 AND knowledge_id > 0",
        name=f"ck_{table.name}_identity",
        table=table,
    )

sa.CheckConstraint(
    "file_version >= 0 AND operation IN ('upload', 'delete')",
    name="ck_runtime_knowledge_job_operation",
    table=jobs,
)
sa.CheckConstraint(
    "status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'cleanup_pending', 'deleted')",
    name="ck_runtime_knowledge_job_status",
    table=jobs,
)
sa.CheckConstraint(
    "status <> 'running' OR (owner_id IS NOT NULL AND attempt_id IS NOT NULL AND lease_until IS NOT NULL)",
    name="ck_runtime_knowledge_job_owner",
    table=jobs,
)
sa.CheckConstraint(
    "writer_ended OR (write_started AND reconcile_required)",
    name="ck_runtime_knowledge_job_writer",
    table=jobs,
)
sa.CheckConstraint(
    "chunk_count IS NULL OR chunk_count >= 0",
    name="ck_runtime_knowledge_job_chunks",
    table=jobs,
)
sa.CheckConstraint(
    "NOT physical_cleanup_complete OR (operation = 'delete' AND status = 'deleted')",
    name="ck_runtime_knowledge_job_cleanup",
    table=jobs,
)
sa.CheckConstraint(
    "jsonb_typeof(request_payload) = 'object' AND octet_length(request_payload::text) <= 16384",
    name="ck_runtime_knowledge_job_payload",
    table=jobs,
).ddl_if(dialect="postgresql")
sa.CheckConstraint(
    "latest_version >= -1 AND tombstone_version >= -1",
    name="ck_runtime_knowledge_file_version",
    table=files,
)
sa.CheckConstraint(
    "(visible_job_id IS NULL AND visible_version IS NULL AND visible_generation IS NULL) OR (visible_job_id IS NOT NULL AND visible_version IS NOT NULL AND visible_generation IS NOT NULL AND visible_version > tombstone_version)",
    name="ck_runtime_knowledge_file_visibility",
    table=files,
)
sa.Index(
    "idx_runtime_knowledge_job_file",
    jobs.c.tenant_id,
    jobs.c.knowledge_id,
    jobs.c.file_id,
    jobs.c.file_version,
)
sa.Index(
    "idx_runtime_knowledge_job_ready",
    jobs.c.tenant_id,
    jobs.c.status,
    jobs.c.lease_until,
)
sa.Index(
    "idx_runtime_knowledge_file_scope",
    files.c.tenant_id,
    files.c.knowledge_id,
    files.c.file_id,
)


def bind_knowledge_jobs(scope, engine):
    tables = {JOBS: jobs, FILES: files}
    integer = {
        "knowledge_id",
        "file_version",
        "revision",
        "latest_version",
        "visible_version",
        "tombstone_version",
        "chunk_count",
    }
    boolean = {
        "write_started",
        "writer_ended",
        "reconcile_required",
        "physical_cleanup_complete",
    }
    definitions = tuple(
        DatasetDefinition(
            name,
            next(iter(table.primary_key.columns)).name,
            tuple(
                FieldDefinition(
                    field.name,
                    "integer"
                    if field.name in integer
                    else "boolean"
                    if field.name in boolean
                    else "object"
                    if field.name == "request_payload"
                    else "string",
                    nullable=field.nullable,
                )
                for field in table.columns
            ),
            frozenset({"runtime"}),
            frozenset({"runtime"}),
            tenant_field="tenant_id",
            active_field="delete_flag",
        )
        for name, table in tables.items()
    )
    return SQLRecordStore(
        scope,
        DatasetCatalog(definitions),
        tables,
        engine,
        revision_fields={name: "revision" for name in tables},
        audit_mappings={
            name: RecordAudit(
                "create_time",
                "update_time",
                "created_by",
                "updated_by",
                extra_dates=frozenset({"lease_until"}) if name == JOBS else frozenset(),
            )
            for name in tables
        },
    )
