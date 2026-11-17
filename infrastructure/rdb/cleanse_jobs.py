# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Trusted logical schema and RecordStore composition for Management cleanse jobs."""

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

DATASET = "file_cleanse_jobs"


def column(name, kind, comment, **kwargs):
    return sa.Column(name, kind, comment=comment, **kwargs)


class FileCleanseJob(TableBase):
    __tablename__ = "file_cleanse_job_t"
    __table_args__: ClassVar[dict] = {"schema": "nexent"}
    id = column(
        "id", sa.Integer, "Technical cleansing job primary key.", primary_key=True
    )
    job_id = column(
        "job_id",
        sa.String(32),
        "Stable public idempotent cleansing job identifier.",
        nullable=False,
        unique=True,
    )
    tenant_id = column(
        "tenant_id",
        sa.String(100),
        "Tenant owning the authorized cleansing request.",
        nullable=False,
    )
    user_id = column(
        "user_id",
        sa.String(100),
        "User owning the request and its inspect/cancel access.",
        nullable=False,
    )
    run_id = column(
        "run_id",
        sa.String(38),
        "Authorized AgentOS run requiring the source file.",
        nullable=True,
    )
    scope_kind = column(
        "scope_kind",
        sa.String(30),
        "Authorization context: run callback or knowledge file.",
        nullable=False,
        server_default="run",
    )
    knowledge_id = column(
        "knowledge_id",
        sa.Integer,
        "Knowledge base reference authorized by Management; knowledge scope only.",
        nullable=True,
    )
    file_id = column(
        "file_id",
        sa.String(32),
        "Stable knowledge file identifier; knowledge scope only.",
        nullable=True,
    )
    file_version = column(
        "file_version",
        sa.Integer,
        "Authorized knowledge file generation; knowledge scope only.",
        nullable=True,
    )
    request_hash = column(
        "request_hash",
        sa.String(64),
        "SHA256 of the canonical scope-specific cleansing request payload.",
        nullable=False,
    )
    request_payload = column(
        "request_payload",
        sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
        "Validated run or knowledge cleansing request; no credentials or raw file bytes.",
        nullable=False,
    )
    parser_version = column(
        "parser_version",
        sa.String(128),
        "Pinned parser build required when executing this job.",
        nullable=False,
    )
    status = column(
        "status",
        sa.String(30),
        "queued/running/completed/failed/cancelled lifecycle state.",
        nullable=False,
    )
    reconcile_required = column(
        "reconcile_required",
        sa.Boolean,
        "Unknown write outcome blocks automatic retry until reconciliation.",
        nullable=False,
    )
    execution_ended = column(
        "execution_ended", sa.Boolean,
        "Confirmed local parser execution and process group have ended; NULL for legacy unknown, independent of object write certainty.",
        nullable=True, server_default=sa.true(),
    )
    attempt_id = column(
        "attempt_id",
        sa.String(32),
        "Per-claim fencing token, replaced on lease takeover.",
        nullable=True,
    )
    owner_id = column(
        "owner_id",
        sa.String(100),
        "Worker instance holding the current attempt lease.",
        nullable=True,
    )
    lease_until = column(
        "lease_until",
        sa.DateTime(timezone=True),
        "UTC expiration of the current worker attempt.",
        nullable=True,
    )
    artifact = column(
        "artifact",
        sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
        "Confirmed ObjectReference only after successful publication.",
        nullable=True,
    )
    error_code = column(
        "error_code",
        sa.String(128),
        "Sanitized stable terminal failure classification.",
        nullable=True,
    )
    revision = column(
        "revision",
        sa.Integer,
        "RecordStore optimistic concurrency revision.",
        nullable=False,
    )


cleanse_jobs = FileCleanseJob.__table__
for name, description in {
    "create_time": "UTC time the job was admitted.",
    "update_time": "UTC time of the latest state change.",
    "created_by": "Trusted actor admitting the job.",
    "updated_by": "Trusted actor performing the latest state update.",
    "delete_flag": "Soft deletion marker, N active and Y deleted.",
}.items():
    cleanse_jobs.c[name].comment = description
    cleanse_jobs.c[name].nullable = False
cleanse_jobs.c.delete_flag.server_default = sa.DefaultClause("N")
sa.Index(
    "idx_file_cleanse_job_knowledge",
    cleanse_jobs.c.tenant_id,
    cleanse_jobs.c.knowledge_id,
    cleanse_jobs.c.file_id,
    cleanse_jobs.c.file_version,
)
sa.CheckConstraint(
    sa.or_(
        sa.and_(
            cleanse_jobs.c.scope_kind == "run",
            cleanse_jobs.c.run_id.is_not(None),
            cleanse_jobs.c.knowledge_id.is_(None),
            cleanse_jobs.c.file_id.is_(None),
            cleanse_jobs.c.file_version.is_(None),
        ),
        sa.and_(
            cleanse_jobs.c.scope_kind == "knowledge",
            cleanse_jobs.c.run_id.is_(None),
            cleanse_jobs.c.knowledge_id.is_not(None),
            cleanse_jobs.c.knowledge_id > 0,
            cleanse_jobs.c.file_id.is_not(None),
            cleanse_jobs.c.file_id.regexp_match("^[0-9a-f]{32}$"),
            cleanse_jobs.c.file_version.is_not(None),
            cleanse_jobs.c.file_version >= 0,
        ),
    ),
    name="ck_file_cleanse_job_scope",
    table=cleanse_jobs,
)
sa.Index(
    "idx_file_cleanse_job_owner",
    cleanse_jobs.c.tenant_id,
    cleanse_jobs.c.user_id,
    cleanse_jobs.c.run_id,
)
sa.Index(
    "idx_file_cleanse_job_ready",
    cleanse_jobs.c.tenant_id,
    cleanse_jobs.c.status,
    cleanse_jobs.c.lease_until,
)


def bind_cleanse_jobs(scope, engine):
    fields = tuple(
        FieldDefinition(
            field.name,
            "boolean"
            if field.name in {"reconcile_required", "execution_ended"}
            else "integer"
            if field.name in {"id", "revision", "knowledge_id", "file_version"}
            else "object"
            if field.name in {"request_payload", "artifact"}
            else "string",
            nullable=field.nullable,
        )
        for field in cleanse_jobs.columns
    )
    catalog = DatasetCatalog(
        (
            DatasetDefinition(
                DATASET,
                "id",
                fields,
                frozenset({"management"}),
                frozenset({"management"}),
                tenant_field="tenant_id",
                active_field="delete_flag",
            ),
        )
    )
    return SQLRecordStore(
        scope,
        catalog,
        {DATASET: cleanse_jobs},
        engine,
        revision_fields={DATASET: "revision"},
        audit_mappings={
            DATASET: RecordAudit(
                "create_time",
                "update_time",
                "created_by",
                "updated_by",
                extra_dates=frozenset({"lease_until"}),
            )
        },
    )
