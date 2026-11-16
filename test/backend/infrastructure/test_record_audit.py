# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Audit identity and UTC values survive writes, queries and soft deletion."""

import pytest
import sqlalchemy as sa
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    PageRequest,
    RecordQuery,
    Revision,
    StorageScope,
)

from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)
from test.backend.infrastructure.test_record_store import context


def test_audited_create_update_query_and_delete():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    columns = [
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant", sa.String),
        sa.Column("revision", sa.Integer),
        sa.Column("deleted", sa.String),
        sa.Column("status", sa.String),
    ]
    columns += [
        sa.Column(name, sa.DateTime(timezone=True))
        for name in ("created_at", "updated_at")
    ]
    columns += [sa.Column(name, sa.String) for name in ("created_by", "updated_by")]
    table = sa.Table("audited", metadata, *columns)
    metadata.create_all(engine)
    fields = tuple(
        FieldDefinition(
            column.name, "integer" if column.name == "revision" else "string"
        )
        for column in columns
    )
    catalog = DatasetCatalog(
        (
            DatasetDefinition(
                "jobs",
                "id",
                fields,
                {"runtime"},
                {"runtime"},
                tenant_field="tenant",
                active_field="deleted",
            ),
        )
    )
    audit = RecordAudit("created_at", "updated_at", "created_by", "updated_by")
    store = SQLRecordStore(
        StorageScope("runtime", "a", "actor-a", {"jobs"}),
        catalog,
        {"jobs": table},
        engine,
        revision_fields={"jobs": "revision"},
        audit_mappings={"jobs": audit},
    )
    try:
        created = store.create(
            "jobs", {"id": "one", "status": "queued"}, context=context()
        )
        assert created["created_by"] == created["updated_by"] == "actor-a"
        assert created["created_at"].endswith("+00:00")
        with pytest.raises(ScopeDenied):
            store.patch(
                "jobs",
                "one",
                FieldPatch(set_values={"created_by": "fake"}),
                context=context(),
            )
        store.patch(
            "jobs",
            "one",
            FieldPatch(set_values={"status": "running"}),
            expected=Revision("1"),
            context=context(),
        )
        updated = store.get("jobs", "one", context=context())
        assert (
            updated["created_at"] == created["created_at"] and updated["revision"] == 2
        )
        query = RecordQuery(
            where=Comparison("created_at", "gte", created["created_at"])
        )
        assert (
            len(store.query("jobs", query, PageRequest(), context=context()).items) == 1
        )
        assert store.delete(
            "jobs", "one", expected=Revision("2"), context=context()
        ).deleted
        assert store.get("jobs", "one", context=context()) is None
        assert not store.delete("jobs", "one", context=context()).deleted
        with engine.connect() as connection:
            row = connection.execute(sa.select(table)).mappings().one()
            assert (
                row["deleted"] == "Y"
                and row["revision"] == 3
                and row["updated_by"] == "actor-a"
            )
    finally:
        engine.dispose()
