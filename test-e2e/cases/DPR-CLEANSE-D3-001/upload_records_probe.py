# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real PostgreSQL source/ledger transaction commit and controlled rollback."""

from nexent.storage.models import FieldPatch, Revision, StorageScope

from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.knowledge_storage_record import KnowledgeStorageObject
from infrastructure.rdb.source_binding import DATASET as SOURCE
from infrastructure.rdb.upload_records import LEDGER, bind_upload_records


def check_upload_transactions(engine, context):
    KnowledgeStorageObject.__table__.create(engine, checkfirst=True)
    file_id = "8" * 32
    with engine.begin() as connection:
        connection.execute(
            KnowledgeFileLifecycle.__table__.insert().values(
                file_id=file_id,
                tenant_id="tenant-a",
                knowledge_id=1,
                index_name="kb-one",
                original_filename="atomic.txt",
                bucket_name="source-proof",
                object_name="atomic.txt",
                status="UPLOADING",
                stage="UPLOAD",
                version=0,
                created_by="user-a",
                updated_by="user-a",
                delete_flag="N",
            )
        )
    records = bind_upload_records(
        StorageScope("management", "tenant-a", "accounting", {SOURCE, LEDGER}), engine
    )
    other = None
    values = {
        "knowledge_id": 1,
        "index_name": "kb-one",
        "bucket_name": "source-proof",
        "object_name": "atomic.txt",
        "raw_bytes": 6,
        "status": "COMMITTED",
    }
    try:
        try:
            with records.transaction(context=context()) as tx:
                rolled_back = tx.create(LEDGER, values, context=context())
                assert tx.patch(
                    SOURCE,
                    file_id,
                    FieldPatch(
                        set_values={
                            "storage_object_id": rolled_back["storage_object_id"],
                            "status": "UPLOADED",
                        }
                    ),
                    expected=Revision("0"),
                    context=context(),
                ).matched
                raise RuntimeError("controlled rollback before commit")
        except RuntimeError as error:
            assert str(error) == "controlled rollback before commit"
        else:
            raise AssertionError("controlled rollback did not propagate")
        assert (
            records.get(LEDGER, rolled_back["storage_object_id"], context=context())
            is None
        )
        assert records.get(SOURCE, file_id, context=context())["status"] == "UPLOADING"
        with records.transaction(context=context()) as tx:
            ledger = tx.create(LEDGER, values, context=context())
            assert tx.patch(
                SOURCE,
                file_id,
                FieldPatch(
                    set_values={
                        "storage_object_id": ledger["storage_object_id"],
                        "status": "UPLOADED",
                    }
                ),
                expected=Revision("0"),
                context=context(),
            ).matched
        row = records.get(SOURCE, file_id, context=context())
        assert (
            row["status"] == "UPLOADED"
            and row["storage_object_id"] == ledger["storage_object_id"]
        )
        assert ledger["version"] == row["version"] == 1
        assert ledger["created_by"] == row["updated_by"] == "accounting"
        other = bind_upload_records(
            StorageScope("management", "tenant-b", "accounting", {SOURCE, LEDGER}),
            engine,
        )
        assert other.get(SOURCE, file_id, context=context()) is None
        assert other.get(LEDGER, ledger["storage_object_id"], context=context()) is None
    finally:
        if other is not None:
            other.close()
        records.close()
