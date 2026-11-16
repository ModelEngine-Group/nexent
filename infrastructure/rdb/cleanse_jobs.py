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
        nullable=False,
    )
    request_hash = column(
        "request_hash",
        sa.String(64),
        "SHA256 of the canonical FileCleanseRequest payload.",
        nullable=False,
    )
    request_payload = column(
        "request_payload",
        sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
        "Validated FileCleanseRequest only; no credentials or raw file bytes.",
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
            if field.name == "reconcile_required"
            else "integer"
            if field.name in {"id", "revision"}
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
