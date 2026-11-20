# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scoped ingestion snapshots reuse lifecycle CAS and audit columns."""

import pytest
import sqlalchemy as sa
from contracts.knowledge_ingestion import INGESTION_DATASET
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import FieldPatch, Revision, StorageScope

from infrastructure.rdb.knowledge_ingestion import (
    bind_ingestion_records,
    ingestion_catalog,
)
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_contract import intent


@pytest.fixture
def records(monkeypatch):
    from infrastructure.rdb import knowledge_ingestion as module

    definition, original, _ = ingestion_catalog()
    columns = []
    for field in definition.fields:
        source = original.c[field.name]
        kind = (
            sa.JSON(none_as_null=True)
            if field.name == "ingestion_request"
            else source.type
        )
        columns.append(
            sa.Column(
                field.name,
                kind,
                primary_key=source.primary_key,
                nullable=source.nullable,
                onupdate=source.onupdate.arg if source.onupdate is not None else None,
            )
        )
    table = sa.Table("ingestion_files", sa.MetaData(), *columns)
    monkeypatch.setattr(module, "files", table)
    engine = sa.create_engine("sqlite://")
    table.create(engine)
    value = intent()
    row = {
        "file_id": value.file_id,
        "tenant_id": "tenant-a",
        "knowledge_id": 1,
        "index_name": "kb-one",
        "original_filename": value.filename,
        "source_generation": 0,
        "source_space": value.source.space,
        "source_key": value.source.key,
        "source_revision": value.source.version,
        "source_sha256": value.source.sha256,
        "status": "UPLOADED",
        "stage": "UPLOAD",
        "processing_attempt": 0,
        "version": 3,
        "delete_flag": "N",
    }
    with engine.begin() as conn:
        conn.execute(table.insert(), row)
    scope = StorageScope("management", "tenant-a", "user-a", {INGESTION_DATASET})
    port = bind_ingestion_records(scope, engine)
    try:
        yield port, engine, table
    finally:
        port.close()
        engine.dispose()


def test_snapshot_is_nullable_and_has_a_database_comment():
    _, table, _ = ingestion_catalog()
    assert table.c.ingestion_request.nullable
    assert "snapshot" in table.c.ingestion_request.comment.lower()
    assert "16 KiB" in table.c.ingestion_request.comment


def test_port_preserves_snapshot_updates_audit_and_rejects_stale_cas(records):
    port, _, _ = records
    value = intent()
    row = port.get(INGESTION_DATASET, value.file_id, context=context())
    assert row["ingestion_request"] is None
    patch = FieldPatch(
        set_values={
            "ingestion_request": value.model_dump(mode="json"),
            "stage": "INGEST_ACCEPTED",
        }
    )
    receipt = port.patch(
        INGESTION_DATASET,
        value.file_id,
        patch,
        expected=Revision("3"),
        context=context(),
    )
    assert receipt.matched and receipt.revision == Revision("4")
    saved = port.get(INGESTION_DATASET, value.file_id, context=context())
    assert saved["ingestion_request"] == value.model_dump(mode="json")
    assert saved["updated_by"] == "user-a" and saved["update_time"]
    assert not port.patch(
        INGESTION_DATASET,
        value.file_id,
        FieldPatch(set_values={"stage": "STALE"}),
        expected=Revision("3"),
        context=context(),
    ).matched
    assert (
        port.get(INGESTION_DATASET, value.file_id, context=context())["stage"]
        == "INGEST_ACCEPTED"
    )


def test_port_cannot_cross_tenants_or_mutate_scope_audit_fields(records):
    port, engine, _ = records
    foreign = bind_ingestion_records(
        StorageScope("management", "tenant-b", "user-a", {INGESTION_DATASET}), engine
    )
    try:
        assert (
            foreign.get(INGESTION_DATASET, intent().file_id, context=context()) is None
        )
        assert not foreign.patch(
            INGESTION_DATASET,
            intent().file_id,
            FieldPatch(set_values={"stage": "FOREIGN"}),
            expected=Revision("3"),
            context=context(),
        ).matched
    finally:
        foreign.close()
    for name in ("tenant_id", "created_by", "updated_by", "version", "delete_flag"):
        with pytest.raises(ScopeDenied):
            port.patch(
                INGESTION_DATASET,
                intent().file_id,
                FieldPatch(set_values={name: "foreign"}),
                context=context(),
            )
