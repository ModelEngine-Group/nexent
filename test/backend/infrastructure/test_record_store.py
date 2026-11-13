# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scoped record transactions with a controlled in-memory SQL backend."""

from time import monotonic

import pytest
import sqlalchemy as sa
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    InvalidInput,
    ScopeDenied,
)
from nexent.storage.models import FieldPatch, OperationContext, Revision, StorageScope

from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)


def context():
    return OperationContext("record-test", monotonic() + 5)


@pytest.fixture
def stores():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    table = sa.Table(
        "jobs",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant", sa.String, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("attempt", sa.Integer, default=0),
        sa.Column("detail", sa.String, nullable=True),
    )
    metadata.create_all(engine)
    fields = tuple(
        FieldDefinition(name, kind, nullable=name == "detail")
        for name, kind in [
            ("id", "string"),
            ("tenant", "string"),
            ("revision", "integer"),
            ("status", "string"),
            ("attempt", "integer"),
            ("detail", "string"),
        ]
    )
    catalog = DatasetCatalog(
        (
            DatasetDefinition(
                "jobs",
                "id",
                fields,
                frozenset({"runtime"}),
                frozenset({"runtime"}),
                tenant_field="tenant",
            ),
        )
    )

    def make(tenant):
        return SQLRecordStore(
            StorageScope("runtime", tenant, "actor", {"jobs"}),
            catalog,
            {"jobs": table},
            engine,
            revision_fields={"jobs": "revision"},
        )

    yield make("a"), make("b")
    engine.dispose()


def test_create_injects_scope_and_get_is_neutral(stores):
    a, b = stores
    row = a.create("jobs", {"id": "one", "status": "queued"}, context=context())
    assert row["tenant"] == "a" and row["revision"] == 1
    assert a.get("jobs", "one", fields=("id", "status"), context=context()) == {
        "id": "one",
        "status": "queued",
    }
    assert b.get("jobs", "one", context=context()) is None


def test_revision_cas_has_one_winner(stores):
    a, _ = stores
    a.create("jobs", {"id": "one", "status": "queued"}, context=context())
    result = a.patch(
        "jobs",
        "one",
        FieldPatch(set_values={"status": "running"}, increments={"attempt": 1}),
        expected=Revision("1"),
        context=context(),
    )
    assert result.matched and result.revision == Revision("2")
    assert not a.patch(
        "jobs",
        "one",
        FieldPatch(set_values={"status": "wrong"}),
        expected=Revision("1"),
        context=context(),
    ).matched
    row = a.get("jobs", "one", context=context())
    assert row["status"] == "running" and row["attempt"] == 1


def test_foreign_patch_and_delete_do_not_match(stores):
    a, b = stores
    a.create("jobs", {"id": "one", "status": "queued"}, context=context())
    assert not b.patch(
        "jobs", "one", FieldPatch(set_values={"status": "wrong"}), context=context()
    ).matched
    assert not b.delete("jobs", "one", context=context()).deleted
    assert a.get("jobs", "one", context=context())["status"] == "queued"


@pytest.mark.parametrize(
    "field,value", [("tenant", "b"), ("id", "two"), ("revision", 0)]
)
def test_patch_cannot_move_scope_or_rewind_revision(stores, field, value):
    with pytest.raises(ScopeDenied):
        stores[0].patch(
            "jobs", "one", FieldPatch(set_values={field: value}), context=context()
        )


@pytest.mark.parametrize(
    "values",
    [{"tenant": "b"}, {"unknown": "value"}, {"attempt": True}, {"revision": 5}],
)
def test_invalid_create_does_not_write(stores, values):
    with pytest.raises((ScopeDenied, InvalidInput)):
        stores[0].create(
            "jobs", {"id": "one", "status": "queued", **values}, context=context()
        )
    assert stores[0].get("jobs", "one", context=context()) is None


def test_transaction_rolls_back_and_cannot_escape(stores):
    a, _ = stores
    with pytest.raises(RuntimeError), a.transaction(context=context()) as tx:
        tx.create("jobs", {"id": "one", "status": "queued"}, context=context())
        raise RuntimeError("abort")
    assert a.get("jobs", "one", context=context()) is None
    with pytest.raises(ScopeDenied):
        tx.get("jobs", "one", context=context())


def test_transaction_commits_all_operations(stores):
    a, _ = stores
    with a.transaction(context=context()) as tx:
        tx.create("jobs", {"id": "one", "status": "queued"}, context=context())
        tx.patch(
            "jobs",
            "one",
            FieldPatch(set_values={"status": "running"}),
            context=context(),
        )
    assert a.get("jobs", "one", context=context())["revision"] == 2


def test_duplicate_key_conflict_and_conditional_delete(stores):
    a, _ = stores
    a.create("jobs", {"id": "one", "status": "queued"}, context=context())
    with pytest.raises(Conflict):
        a.create("jobs", {"id": "one", "status": "queued"}, context=context())
    assert not a.delete(
        "jobs", "one", expected=Revision("2"), context=context()
    ).deleted
    assert a.delete("jobs", "one", expected=Revision("1"), context=context()).deleted
    assert not a.delete("jobs", "one", context=context()).deleted


@pytest.mark.asyncio
async def test_event_loop_cannot_use_sync_driver(stores):
    with pytest.raises(CapabilityUnsupported):
        stores[0].get("jobs", "one", context=context())


def test_commit_failure_is_unknown_and_never_replayed(stores):
    from nexent.storage.errors import OutcomeUnknown
    from sqlalchemy.exc import OperationalError

    a, _ = stores
    calls = []

    def fail_commit(connection):
        calls.append(True)
        raise OperationalError("COMMIT", {}, OSError("private endpoint"))

    sa.event.listen(a._engine, "commit", fail_commit)
    try:
        with pytest.raises(OutcomeUnknown) as caught:
            a.create("jobs", {"id": "one", "status": "queued"}, context=context())
        assert len(calls) == 1
        assert "private" not in str(caught.value)
    finally:
        sa.event.remove(a._engine, "commit", fail_commit)


def test_required_value_error_is_invalid_input(stores):
    with pytest.raises(InvalidInput):
        stores[0].create("jobs", {"id": "one"}, context=context())


def test_transaction_parent_deadline_cannot_be_extended(stores, monkeypatch):
    from nexent.storage.errors import DeadlineExceeded

    from infrastructure.rdb import record_store

    a, _ = stores
    with pytest.raises(DeadlineExceeded), a.transaction(context=context()) as tx:
        tx.create("jobs", {"id": "one", "status": "queued"}, context=context())
        monkeypatch.setattr(record_store, "monotonic", lambda: 10**15)
        tx.get("jobs", "one", context=context())
    monkeypatch.undo()
    assert a.get("jobs", "one", context=context()) is None


def test_soft_records_remain_filtered_and_delete_is_not_emulated(stores):
    a, _ = stores
    metadata = sa.MetaData()
    table = sa.Table(
        "soft_jobs",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant", sa.String),
        sa.Column("revision", sa.Integer),
        sa.Column("deleted", sa.String),
    )
    metadata.create_all(a._engine)
    fields = tuple(
        FieldDefinition(name, kind)
        for name, kind in [
            ("id", "string"),
            ("tenant", "string"),
            ("revision", "integer"),
            ("deleted", "string"),
        ]
    )
    catalog = DatasetCatalog(
        (
            DatasetDefinition(
                "jobs",
                "id",
                fields,
                frozenset({"runtime"}),
                frozenset({"runtime"}),
                tenant_field="tenant",
                active_field="deleted",
            ),
        )
    )
    store = SQLRecordStore(
        a.scope,
        catalog,
        {"jobs": table},
        a._engine,
        revision_fields={"jobs": "revision"},
    )
    assert store.create("jobs", {"id": "active"}, context=context())["deleted"] == "N"
    with a._engine.begin() as connection:
        connection.execute(
            table.insert().values(id="hidden", tenant="a", revision=1, deleted="Y")
        )
    assert store.get("jobs", "hidden", context=context()) is None
    with pytest.raises(ScopeDenied):
        store.patch(
            "jobs", "active", FieldPatch(set_values={"deleted": "Y"}), context=context()
        )
    with pytest.raises(CapabilityUnsupported):
        store.delete("jobs", "active", context=context())


def test_transaction_has_one_commit(stores):
    a, _ = stores
    commits = []

    def committed(connection):
        commits.append(True)

    sa.event.listen(a._engine, "commit", committed)
    try:
        with a.transaction(context=context()) as tx:
            tx.create("jobs", {"id": "one", "status": "queued"}, context=context())
            tx.patch(
                "jobs",
                "one",
                FieldPatch(set_values={"status": "running"}),
                context=context(),
            )
        assert len(commits) == 1
    finally:
        sa.event.remove(a._engine, "commit", committed)
