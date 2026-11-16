# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Ledger business queries execute through real scoped record ports."""

from contextlib import contextmanager

import pytest
from management.db.knowledge_base import storage_object as storage_db
from nexent.storage.errors import OutcomeUnknown
from nexent.storage.models import Page, PageRequest, StorageScope, WriteReceipt

from infrastructure.rdb.knowledge_storage_record import KnowledgeStorageObject
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.rdb.storage_ledger import (
    HISTORY,
    LEDGER,
    bind_ledger_lookup,
    bind_ledger_records,
)
from test.backend.infrastructure import test_ledger_records as ledger_fixtures

ledger_engine = ledger_fixtures.ledger_engine


@pytest.fixture
def repository(ledger_engine, monkeypatch):
    calls = []

    @contextmanager
    def ports(tenant_id, actor_id, *, context, identity=None):
        calls.append((tenant_id, actor_id, context.operation_id, identity))
        store = (
            bind_ledger_lookup(
                identity[0], identity[1], ledger_engine, include_deleted=identity[2]
            )
            if identity is not None
            else bind_ledger_records(
                StorageScope("management", tenant_id, actor_id, {LEDGER, HISTORY}),
                ledger_engine,
            )
        )
        try:
            yield store
        finally:
            store.close()

    monkeypatch.setattr(storage_db, "ledger_record_ports", ports)
    return calls


def test_model_has_identity_constraint_and_active_indexes():
    table = KnowledgeStorageObject.__table__
    unique = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert table.schema == "nexent"
    assert unique["uq_knowledge_storage_object_bucket_object"] == (
        "bucket_name",
        "object_name",
    )
    assert {index.name for index in table.indexes} == {
        "idx_knowledge_storage_object_tenant_active",
        "idx_knowledge_storage_object_kb_active",
    }
    kb_index = next(
        index
        for index in table.indexes
        if index.name == "idx_knowledge_storage_object_kb_active"
    )
    assert [column.name for column in kb_index.columns] == ["tenant_id", "knowledge_id"]


def test_get_active_object_is_tenant_scoped(repository):
    assert (
        storage_db.get_storage_object("tenant-a", "files", "one.txt")["raw_bytes"] == 6
    )
    assert storage_db.get_storage_object("tenant-b", "files", "one.txt") is None
    assert storage_db.get_storage_object("tenant-a", "files", "deleted.txt") is None


def test_get_history_is_explicit_and_still_tenant_scoped(repository):
    assert (
        storage_db.get_storage_object(
            "tenant-a", "files", "deleted.txt", include_deleted=True
        )["delete_flag"]
        == "Y"
    )
    assert (
        storage_db.get_storage_object(
            "tenant-b", "files", "deleted.txt", include_deleted=True
        )
        is None
    )
    assert (
        storage_db.get_storage_object(
            "tenant-a", "files", "missing.txt", include_deleted=True
        )
        is None
    )


def test_exact_ownership_lookup_keeps_the_authoritative_owner(repository):
    assert (
        storage_db.get_storage_object_by_identity("files", "two.txt")["tenant_id"]
        == "tenant-b"
    )
    assert storage_db.get_storage_object_by_identity("files", "deleted.txt") is None
    assert (
        storage_db.get_storage_object_by_identity(
            "files", "deleted.txt", include_deleted=True
        )["status"]
        == "DELETED"
    )
    assert repository[0][0] is None and repository[0][3] == ("files", "two.txt", False)


def test_group_totals_keep_active_tenant_and_optional_kb_filter(repository):
    assert storage_db.aggregate_committed_bytes_by_kb("tenant-a") == {7: 6}
    assert storage_db.aggregate_committed_bytes_by_kb("tenant-a", [7, 8]) == {7: 6}
    assert storage_db.aggregate_committed_bytes_by_kb("tenant-a", [8]) == {}


def test_empty_inputs_do_not_open_storage(repository):
    assert storage_db.aggregate_committed_bytes_by_kb("tenant-a", []) == {}
    assert (
        storage_db.get_committed_source_bytes_by_object_names(
            "tenant-a", 7, "files", []
        )
        == {}
    )
    assert repository == []


def test_source_sizes_require_matching_kb_bucket_and_active_owner(repository):
    assert storage_db.get_committed_source_bytes_by_object_names(
        "tenant-a", 7, "files", ["one.txt", "two.txt", "deleted.txt"]
    ) == {"one.txt": 6}
    assert (
        storage_db.get_committed_source_bytes_by_object_names(
            "tenant-a", 8, "files", ["one.txt"]
        )
        == {}
    )
    assert (
        storage_db.get_committed_source_bytes_by_object_names(
            "tenant-a", 7, "other", ["one.txt"]
        )
        == {}
    )


def test_tenant_sum_is_zero_without_active_rows(repository):
    assert storage_db.get_tenant_committed_bytes("tenant-a") == 6
    assert storage_db.get_tenant_committed_bytes("empty") == 0


def test_listing_is_ordered_and_scoped(repository):
    assert [
        row["object_name"]
        for row in storage_db.list_committed_storage_objects("tenant-a")
    ] == ["one.txt"]
    assert storage_db.list_committed_storage_objects("tenant-a", knowledge_id=8) == []


def test_listing_handles_an_empty_provider_page_with_a_continuation(
    repository, monkeypatch
):
    original, emitted = SQLRecordStore.query, []

    def sparse(self, dataset, query, page, *, context):
        if dataset == LEDGER and not emitted:
            emitted.append(True)
            return Page((), "controlled-continuation")
        if page.cursor == "controlled-continuation":
            page = PageRequest(limit=page.limit)
        return original(self, dataset, query, page, context=context)

    monkeypatch.setattr(SQLRecordStore, "query", sparse)
    assert [
        row["object_name"]
        for row in storage_db.list_committed_storage_objects("tenant-a")
    ] == ["one.txt"]


def test_release_is_audited_idempotent_and_cannot_cross_tenants(repository):
    assert not storage_db.mark_storage_object_deleted(
        "tenant-b", "files", "one.txt", updated_by="intruder"
    )
    assert storage_db.mark_storage_object_deleted(
        "tenant-a", "files", "one.txt", updated_by="user-a"
    )
    assert storage_db.get_tenant_committed_bytes("tenant-a") == 0
    row = storage_db.get_storage_object(
        "tenant-a", "files", "one.txt", include_deleted=True
    )
    assert row["status"] == "DELETED" and row["delete_flag"] == "Y"
    assert row["updated_by"] == "user-a" and row["version"] == 2
    assert storage_db.mark_storage_object_deleted("tenant-a", "files", "one.txt")
    assert (
        storage_db.get_storage_object(
            "tenant-a", "files", "one.txt", include_deleted=True
        )["version"]
        == 2
    )
    assert not storage_db.mark_storage_object_deleted(
        "tenant-a", "files", "missing.txt"
    )


@pytest.mark.parametrize("status,flag", [("COMMITTED", "Y"), ("DELETED", "N")])
def test_existing_deleted_ledger_states_replay_without_rewriting(
    repository, ledger_engine, status, flag
):
    table = KnowledgeStorageObject.__table__
    with ledger_engine.begin() as conn:
        conn.execute(
            table.update()
            .where(table.c.storage_object_id == 1)
            .values(status=status, delete_flag=flag)
        )
    assert storage_db.mark_storage_object_deleted(
        "tenant-a", "files", "one.txt", updated_by="user-a"
    )
    row = storage_db.get_storage_object(
        "tenant-a", "files", "one.txt", include_deleted=True
    )
    assert (
        row["version"] == 0 and row["status"] == status and row["delete_flag"] == flag
    )


def test_release_retries_a_known_cas_conflict_with_one_budget(repository, monkeypatch):
    original, attempted = SQLRecordStore.patch, []

    def contested(self, dataset, key, patch, *, expected=None, context):
        if not attempted:
            attempted.append(context.operation_id)
            return WriteReceipt(context.operation_id, False)
        attempted.append(context.operation_id)
        return original(self, dataset, key, patch, expected=expected, context=context)

    monkeypatch.setattr(SQLRecordStore, "patch", contested)
    assert storage_db.mark_storage_object_deleted("tenant-a", "files", "one.txt")
    assert len(attempted) == 2 and len(set(attempted)) == 1


def test_release_unknown_commit_is_not_blindly_replayed(repository, monkeypatch):
    original, lost = SQLRecordStore.transaction, []

    @contextmanager
    def lost_reply(self, *, context):
        fail = False
        with original(self, context=context) as bound:
            yield bound
            row = bound.get(HISTORY, 1, context=context)
            if row and row["delete_flag"] == "Y" and not lost:
                lost.append(True)
                fail = True
        if fail:
            raise OutcomeUnknown()

    monkeypatch.setattr(SQLRecordStore, "transaction", lost_reply)
    with pytest.raises(OutcomeUnknown):
        storage_db.mark_storage_object_deleted("tenant-a", "files", "one.txt")
    assert len(repository) == 1
    assert storage_db.mark_storage_object_deleted("tenant-a", "files", "one.txt")


def test_lists_and_filters_do_not_truncate_provider_pages(repository, ledger_engine):
    with ledger_engine.begin() as conn:
        conn.execute(
            KnowledgeStorageObject.__table__.insert(),
            [
                {
                    "storage_object_id": 1000 + i,
                    "tenant_id": "tenant-a",
                    "knowledge_id": 7,
                    "index_name": "kb",
                    "bucket_name": "files",
                    "object_name": f"page-{i}.txt",
                    "raw_bytes": 1,
                    "status": "COMMITTED",
                    "delete_flag": "N",
                    "version": 0,
                }
                for i in range(1005)
            ],
        )
    assert len(storage_db.list_committed_storage_objects("tenant-a")) == 1006
    names = [f"page-{i}.txt" for i in range(1005)]
    assert (
        len(
            storage_db.get_committed_source_bytes_by_object_names(
                "tenant-a", 7, "files", names
            )
        )
        == 1005
    )
    assert storage_db.aggregate_committed_bytes_by_kb(
        "tenant-a", list(range(1200))
    ) == {7: 1011}
