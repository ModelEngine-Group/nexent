# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Source identity and retained-byte ledger share one scoped transaction domain."""

import pytest
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied
from nexent.storage.models import FieldPatch, Revision, StorageScope

from infrastructure.rdb.knowledge_storage_record import KnowledgeStorageObject
from infrastructure.rdb.source_binding import DATASET as SOURCE
from infrastructure.rdb.upload_records import LEDGER, bind_upload_records
from test.backend.infrastructure.test_record_store import context
from test.backend.services import test_source_publish as source_fixtures
from test.backend.services.test_source_publish import FILE_ID

publication = source_fixtures.publication


@pytest.fixture
def upload_records(publication):
    _, source, _, _ = publication
    engine = source._engine
    KnowledgeStorageObject.__table__.create(engine)
    records = bind_upload_records(
        StorageScope("management", "tenant-a", "accounting", {SOURCE, LEDGER}), engine
    )
    values = {
        "storage_object_id": 9001,
        "knowledge_id": 1,
        "index_name": "kb",
        "bucket_name": "files",
        "object_name": "planned/source.txt",
        "raw_bytes": 6,
        "status": "COMMITTED",
    }
    yield records, values, engine
    records.close()


def test_source_and_ledger_commit_in_one_audited_transaction(upload_records):
    records, values, _ = upload_records
    with records.transaction(context=context()) as tx:
        ledger = tx.create(LEDGER, values, context=context())
        assert tx.patch(
            SOURCE,
            FILE_ID,
            FieldPatch(
                set_values={
                    "storage_object_id": ledger["storage_object_id"],
                    "status": "UPLOADED",
                }
            ),
            expected=Revision("0"),
            context=context(),
        ).matched
    file = records.get(SOURCE, FILE_ID, context=context())
    assert file["status"] == "UPLOADED" and file["storage_object_id"] == 9001
    assert file["version"] == 1 and file["updated_by"] == "accounting"
    assert ledger["version"] == 1 and ledger["tenant_id"] == "tenant-a"
    assert ledger["created_by"] == ledger["updated_by"] == "accounting"
    assert file["created_by"] == "user-a"


def test_failure_rolls_back_both_logical_datasets(upload_records):
    records, values, _ = upload_records
    with pytest.raises(RuntimeError), records.transaction(context=context()) as tx:
        tx.create(LEDGER, values, context=context())
        tx.patch(
            SOURCE,
            FILE_ID,
            FieldPatch(set_values={"status": "UPLOADED"}),
            expected=Revision("0"),
            context=context(),
        )
        raise RuntimeError("controlled failure before commit")
    assert records.get(LEDGER, 9001, context=context()) is None
    assert records.get(SOURCE, FILE_ID, context=context())["status"] == "UPLOADING"


def test_duplicate_object_identity_conflicts_without_second_charge(upload_records):
    records, values, _ = upload_records
    records.create(LEDGER, values, context=context())
    with pytest.raises(Conflict):
        records.create(LEDGER, {**values, "storage_object_id": 9002}, context=context())
    assert records.get(LEDGER, 9002, context=context()) is None


def test_caller_aborts_ledger_charge_when_source_cas_is_stale(upload_records):
    records, values, _ = upload_records
    with pytest.raises(Conflict), records.transaction(context=context()) as tx:
        tx.create(LEDGER, values, context=context())
        receipt = tx.patch(
            SOURCE,
            FILE_ID,
            FieldPatch(set_values={"status": "UPLOADED"}),
            expected=Revision("9"),
            context=context(),
        )
        if not receipt.matched:
            raise Conflict()
    assert records.get(LEDGER, 9001, context=context()) is None
    assert records.get(SOURCE, FILE_ID, context=context())["version"] == 0


def test_cas_and_soft_deletion_preserve_audit_and_scope(upload_records):
    records, values, _ = upload_records
    records.create(LEDGER, values, context=context())
    assert not records.patch(
        LEDGER,
        9001,
        FieldPatch(set_values={"raw_bytes": 8}),
        expected=Revision("0"),
        context=context(),
    ).matched
    assert records.patch(
        LEDGER,
        9001,
        FieldPatch(set_values={"raw_bytes": 8}),
        expected=Revision("1"),
        context=context(),
    ).matched
    with pytest.raises(ScopeDenied):
        records.patch(
            LEDGER,
            9001,
            FieldPatch(set_values={"created_by": "other"}),
            context=context(),
        )
    records.delete(LEDGER, 9001, expected=Revision("2"), context=context())
    assert records.get(LEDGER, 9001, context=context()) is None


def test_cross_tenant_values_and_runtime_role_are_denied(upload_records):
    records, values, engine = upload_records
    with pytest.raises(ScopeDenied):
        records.create(LEDGER, {**values, "tenant_id": "other"}, context=context())
    with pytest.raises(ScopeDenied):
        bind_upload_records(
            StorageScope("runtime", "tenant-a", "actor", {SOURCE, LEDGER}), engine
        )


def test_explicit_version_and_negative_size_cannot_create_charge(upload_records):
    records, values, _ = upload_records
    with pytest.raises(InvalidInput):
        records.create(LEDGER, {**values, "version": 9}, context=context())
    with pytest.raises(InvalidInput):
        records.create(LEDGER, {**values, "raw_bytes": -1}, context=context())


def test_management_exports_the_infrastructure_owned_model():
    from management.db.knowledge_base.models import KnowledgeStorageObject as exported

    assert exported is KnowledgeStorageObject
    assert (
        KnowledgeStorageObject.__module__
        == "infrastructure.rdb.knowledge_storage_record"
    )
