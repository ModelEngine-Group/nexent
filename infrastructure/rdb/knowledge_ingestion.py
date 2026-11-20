# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restricted lifecycle records for Management's persistent ingestion coordinator."""

from dataclasses import replace

import sqlalchemy as sa
from contracts.knowledge_ingestion import (
    ACTIVE_LEGACY_FILE_IDS,
    INGESTION_DATASET,
    LEGACY_FILE_ID_OCCUPANCY,
    LEGACY_FILE_IDENTITIES,
    is_canonical_file_id,
    legacy_ingestion_plan_hash,
)
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied
from nexent.storage.models import FieldPatch, Revision, StorageScope, WriteOutcome

from infrastructure.rdb.base import SCHEMA
from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

files = KnowledgeFileLifecycle.__table__
legacy_file_identities = sa.Table(
    "knowledge_legacy_file_identity_t", sa.MetaData(),
    sa.Column("original_file_id", sa.String(64), primary_key=True),
    sa.Column("standard_file_id", sa.String(32), unique=True, nullable=False),
    sa.Column("tenant_id", sa.String(100), nullable=False),
    sa.Column("knowledge_id", sa.BigInteger, nullable=False),
    sa.Column("lifecycle_revision", sa.BigInteger, nullable=False),
    sa.Column("source_generation", sa.Integer, nullable=False),
    sa.Column("plan_sha256", sa.String(64), nullable=False),
    sa.Column("version", sa.BigInteger, nullable=False),
    sa.Column("created_by", sa.String(100), nullable=False),
    sa.Column("updated_by", sa.String(100), nullable=False),
    sa.Column("create_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("update_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("activated_at", sa.DateTime(timezone=True)),
    schema=SCHEMA,
)


def active_legacy_file_ids(lifecycle):
    identities = legacy_file_identities
    original = lifecycle.alias("original_lifecycle")
    target = lifecycle.alias("standard_lifecycle")
    names = ("original_file_id", "standard_file_id", "tenant_id", "knowledge_id")
    projection = sa.select(*(identities.c[name] for name in names)).join(
        target, sa.and_(
            target.c.file_id == identities.c.standard_file_id,
            target.c.tenant_id == identities.c.tenant_id,
            target.c.knowledge_id == identities.c.knowledge_id,
        ),
    ).where(
        identities.c.activated_at.is_not(None),
        ~sa.exists(sa.select(1).where(original.c.file_id == identities.c.original_file_id)),
    ).subquery(ACTIVE_LEGACY_FILE_IDS)
    definition = DatasetDefinition(
        ACTIVE_LEGACY_FILE_IDS, "original_file_id",
        tuple(FieldDefinition(name, "integer" if name == "knowledge_id" else "string") for name in names),
        frozenset({"management"}), tenant_field="tenant_id",
    )
    return definition, projection


def bind_legacy_file_id_occupancy(actor_id, file_id, engine):
    if not is_canonical_file_id(file_id):
        raise InvalidInput()
    projection = sa.select(
        sa.literal(file_id).label("file_id"),
        sa.func.count().label("count"),
    ).where(files.c.file_id == file_id).subquery(LEGACY_FILE_ID_OCCUPANCY)
    projection.primary_key.add(projection.c.file_id)
    definition = DatasetDefinition(
        LEGACY_FILE_ID_OCCUPANCY, "file_id",
        (FieldDefinition("file_id", "string"), FieldDefinition("count", "integer")),
        frozenset({"management"}), allow_system=True,
    )
    return SQLRecordStore(
        StorageScope("management", None, actor_id, {LEGACY_FILE_ID_OCCUPANCY}, system=True),
        DatasetCatalog((definition,)), {LEGACY_FILE_ID_OCCUPANCY: projection}, engine, revision_fields={},
    )


def reserve_legacy_file_identity(actor, plan, engine, *, context):
    """Serialize reservations for the original row without changing its identity."""
    snapshot = plan.legacy_snapshot
    if snapshot is None or snapshot.previous_file_id is None:
        raise InvalidInput()
    if snapshot.tenant_id != actor.tenant_id or plan.user_id != actor.user_id:
        raise ScopeDenied()
    original_id = snapshot.previous_file_id
    values = {
        "original_file_id": original_id, "standard_file_id": plan.file_id,
        "tenant_id": actor.tenant_id, "knowledge_id": plan.knowledge_id,
        "lifecycle_revision": snapshot.lifecycle_revision, "source_generation": plan.file_version,
        "plan_sha256": legacy_ingestion_plan_hash(plan),
    }
    lifecycle, table, lifecycle_audit = ingestion_catalog()
    identity = DatasetDefinition(
        LEGACY_FILE_IDENTITIES, "original_file_id",
        tuple(FieldDefinition(column.name, "integer" if isinstance(column.type, sa.Integer) else "string")
              for column in legacy_file_identities.columns if column.name != "activated_at"),
        frozenset({"management"}), frozenset({"management"}), tenant_field="tenant_id",
    )
    store = SQLRecordStore(
        StorageScope("management", actor.tenant_id, actor.user_id, {INGESTION_DATASET, LEGACY_FILE_IDENTITIES}),
        DatasetCatalog((replace(lifecycle, write_roles=frozenset()), identity)),
        {INGESTION_DATASET: table, LEGACY_FILE_IDENTITIES: legacy_file_identities}, engine,
        revision_fields={INGESTION_DATASET: "version", LEGACY_FILE_IDENTITIES: "version"},
        audit_mappings={
            INGESTION_DATASET: lifecycle_audit,
            LEGACY_FILE_IDENTITIES: RecordAudit("create_time", "update_time", "created_by", "updated_by"),
        },
    )
    try:
        with store.transaction(context=context) as transaction:
            source = sa.select(table.c.file_id).where(
                transaction._where(INGESTION_DATASET, original_id),
                table.c.knowledge_id == plan.knowledge_id,
                table.c.version == snapshot.lifecycle_revision,
                table.c.source_generation == plan.file_version,
                table.c.status.in_(("UPLOADED", "COMPLETED", "FAILED")),
                table.c.ingestion_request.is_(None),
                table.c.deletion_request.is_(None),
            ).with_for_update()
            if transaction._execute(transaction._connection, source, context).scalar_one_or_none() is None:
                raise Conflict()
            occupied = sa.select(table.c.file_id).where(table.c.file_id == plan.file_id)
            if transaction._execute(transaction._connection, occupied, context).scalar_one_or_none() is not None:
                raise Conflict()
            existing = transaction.get(LEGACY_FILE_IDENTITIES, original_id, context=context)
            if existing is None:
                return transaction.create(LEGACY_FILE_IDENTITIES, values, context=context)
            if any(existing[name] != values[name] for name in ("standard_file_id", "tenant_id", "knowledge_id")):
                raise Conflict()
            evidence = {name: values[name] for name in ("lifecycle_revision", "source_generation", "plan_sha256")
                        if existing[name] != values[name]}
            if not evidence:
                return existing
            receipt = transaction.patch(
                LEGACY_FILE_IDENTITIES, original_id, FieldPatch(set_values=evidence),
                expected=Revision(str(existing["version"])), context=context,
            )
            if not receipt.matched or receipt.outcome is not WriteOutcome.CONFIRMED:
                raise Conflict()
            return transaction.get(LEGACY_FILE_IDENTITIES, original_id, context=context)
    finally:
        store.close()


def ingestion_catalog():
    names = (
        "file_id",
        "tenant_id",
        "knowledge_id",
        "index_name",
        "original_filename",
        "file_size",
        "storage_object_id",
        "bucket_name",
        "object_name",
        "local_source_path",
        "status",
        "stage",
        "source_generation",
        "source_space",
        "source_key",
        "source_revision",
        "source_sha256",
        "ingestion_request",
        "deletion_request",
        "processing_attempt",
        "process_task_id",
        "forward_task_id",
        "parent_task_id",
        "cleanse_status",
        "runtime_status",
        "processed_chunks",
        "total_chunks",
        "version",
        "error_code",
        "error_message",
        "error_stage",
        "completed_at",
        "failed_at",
        "created_by",
        "updated_by",
        "create_time",
        "update_time",
        "delete_flag",
    )
    integers = {"knowledge_id", "source_generation", "processing_attempt", "version", "file_size", "storage_object_id", "processed_chunks", "total_chunks"}
    fields = tuple(
        FieldDefinition(
            name,
            "object"
            if name in {"ingestion_request", "deletion_request"}
            else "integer"
            if name in integers
            else "string",
            nullable=files.c[name].nullable,
        )
        for name in names
    )
    definition = DatasetDefinition(
        INGESTION_DATASET,
        "file_id",
        fields,
        frozenset({"management"}),
        frozenset({"management"}),
        tenant_field="tenant_id",
        active_field="delete_flag",
    )
    audit = RecordAudit(
        "create_time",
        "update_time",
        "created_by",
        "updated_by",
        extra_dates=frozenset({"completed_at", "failed_at"}),
    )
    return definition, files, audit


def bind_ingestion_records(scope, engine):
    definition, table, audit = ingestion_catalog()
    return SQLRecordStore(
        scope,
        DatasetCatalog((definition,)),
        {INGESTION_DATASET: table},
        engine,
        revision_fields={INGESTION_DATASET: "version"},
        audit_mappings={INGESTION_DATASET: audit},
    )
