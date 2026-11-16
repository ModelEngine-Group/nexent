# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Production ledger facades, snapshot isolation and confirmed physical-source release."""

from management.db.knowledge_base import storage_object as ledger
from nexent.storage.errors import Conflict, NotFound
from nexent.storage.models import FieldPatch, ObjectRef, Revision, StorageScope

from infrastructure.rdb.storage_ledger import HISTORY, LEDGER, bind_ledger_records
from infrastructure.storage_ledger import ledger_record_ports


def check_ledger_access(engine, objects, source, size, context):
    tenant, bucket, key = "tenant-a", source["bucket_name"], source["object_name"]
    total = size * 3
    actual_total = ledger.get_tenant_committed_bytes(tenant)
    grouped = ledger.aggregate_committed_bytes_by_kb(tenant, [1])
    assert type(actual_total) is int and actual_total == total
    assert grouped == {1: total}
    assert all(
        type(key) is int and type(value) is int for key, value in grouped.items()
    )
    assert len(ledger.list_committed_storage_objects(tenant, 1)) == 3
    assert ledger.get_committed_source_bytes_by_object_names(
        tenant, 1, bucket, [key, "missing"]
    ) == {key: size}
    assert ledger.get_storage_object("tenant-b", bucket, key) is None
    assert ledger.get_storage_object_by_identity(bucket, key)["tenant_id"] == tenant
    writer = bind_ledger_records(
        StorageScope("management", tenant, "concurrent", {LEDGER, HISTORY}), engine
    )
    try:
        with ledger_record_ports(tenant, "snapshot", context=context()) as snapshot:
            try:
                with snapshot.transaction(context=context()) as tx:
                    before = tx.get(
                        LEDGER, source["storage_object_id"], context=context()
                    )
                    writer.patch(
                        LEDGER,
                        before["storage_object_id"],
                        FieldPatch(set_values={"status": "COMMITTED"}),
                        expected=Revision(str(before["version"])),
                        context=context(),
                    )
                    assert (
                        tx.get(LEDGER, before["storage_object_id"], context=context())[
                            "version"
                        ]
                        == before["version"]
                    )
                    tx.patch(
                        LEDGER,
                        before["storage_object_id"],
                        FieldPatch(set_values={"status": "COMMITTED"}),
                        expected=Revision(str(before["version"])),
                        context=context(),
                    )
            except Conflict:
                pass
            else:
                raise AssertionError(
                    "repeatable-read concurrent update did not produce a known conflict"
                )
    finally:
        writer.close()
    # This fixture's sole writer has returned and its managed work has drained.
    # Do not claim atomic ETag deletion: the generic adapter intentionally refuses it.
    assert objects.delete(ObjectRef("files", key), context=context()).deleted
    try:
        objects.stat(ObjectRef("files", key), context=context())
    except NotFound:
        pass
    else:
        raise AssertionError("source is still present before charge release")
    assert ledger.mark_storage_object_deleted(
        tenant, bucket, key, updated_by="source-cleanup"
    )
    assert ledger.mark_storage_object_deleted(
        tenant, bucket, key, updated_by="source-cleanup"
    )
    assert ledger.get_storage_object_by_identity(bucket, key) is None
    history = ledger.get_storage_object_by_identity(bucket, key, include_deleted=True)
    assert history["delete_flag"] == "Y" and history["status"] == "DELETED"
    assert history["updated_by"] == "source-cleanup"
    assert ledger.get_tenant_committed_bytes(tenant) == size * 2
