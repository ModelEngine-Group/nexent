# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Legacy read-only tables need no synthetic revision or writable capability."""

import pytest
import sqlalchemy as sa
from nexent.storage.errors import InvalidInput, ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)
from test.backend.infrastructure.test_record_store import context


def test_read_only_without_revision_and_all_writes_denied():
    engine = sa.create_engine("sqlite://")
    table = sa.Table(
        "legacy",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.String),
    )
    table.create(engine)
    with engine.begin() as conn:
        conn.execute(table.insert().values(id=1, tenant_id="tenant"))
    definition = DatasetDefinition(
        "legacy",
        "id",
        (
            FieldDefinition("id", "integer"),
            FieldDefinition("tenant_id", "string", nullable=True),
        ),
        frozenset({"management"}),
        tenant_field="tenant_id",
    )
    store = SQLRecordStore(
        StorageScope("management", "tenant", "user", {"legacy"}),
        DatasetCatalog((definition,)),
        {"legacy": table},
        engine,
        revision_fields={},
    )
    assert store.get("legacy", 1, context=context()) == {"id": 1, "tenant_id": "tenant"}
    with pytest.raises(ScopeDenied):
        store.create("legacy", {"id": 2}, context=context())
    writable = DatasetDefinition(
        "legacy",
        "id",
        definition.fields,
        definition.read_roles,
        frozenset({"management"}),
        tenant_field="tenant_id",
    )
    with pytest.raises(InvalidInput):
        SQLRecordStore(
            store.scope,
            DatasetCatalog((writable,)),
            {"legacy": table},
            engine,
            revision_fields={},
        )
    engine.dispose()
