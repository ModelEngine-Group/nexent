# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Normal upload accounting shares recovery policy without applying batch quota early."""

import pytest
from management.services.file.source_finalize import SourceFinalizer
from nexent.storage.errors import Conflict, NotFound, OutcomeUnknown
from nexent.storage.models import ObjectMetadata, RecordQuery, Revision

from test.backend.infrastructure.test_record_store import context
from test.backend.services import test_source_finalize as finalize_fixtures
from test.backend.services.test_source_publish import FILE_ID

finalization = finalize_fixtures.finalization
publication = finalize_fixtures.publication
SOURCE, LEDGER = finalize_fixtures.SOURCE, finalize_fixtures.LEDGER


def account(records, objects):
    return SourceFinalizer(records, objects).account(
        FILE_ID,
        owner_user_id="user-a",
        owner_service="nexent-config",
        context=context(),
    )


def test_account_is_idempotent_and_defers_batch_quota(finalization):
    finish, records, objects, _, configure = finalization
    configure("0")
    row = account(records, objects)
    assert row["status"] == "UPLOADING" and row["stage"] == "SOURCE_ACCOUNTED"
    assert row["storage_object_id"] and row["created_by"] == "user-a"
    assert account(records, objects)["storage_object_id"] == row["storage_object_id"]
    assert records.sum(LEDGER, "raw_bytes", RecordQuery(), context=context()) == 6
    assert finish() == "quota_review"


@pytest.mark.parametrize("size", [-1, True, False, "6", None])
def test_invalid_authoritative_sizes_do_not_create_charge(finalization, size):
    _, records, objects, _, _ = finalization
    original = objects.stat.return_value
    objects.stat.return_value = ObjectMetadata(
        original.ref, size, "text/plain", sha256=original.sha256
    )
    with pytest.raises(OutcomeUnknown):
        account(records, objects)
    assert records.sum(LEDGER, "raw_bytes", RecordQuery(), context=context()) == 0


def test_missing_source_does_not_create_charge(finalization):
    _, records, objects, _, _ = finalization
    objects.stat.side_effect = NotFound()
    with pytest.raises(NotFound):
        account(records, objects)
    assert records.sum(LEDGER, "raw_bytes", RecordQuery(), context=context()) == 0


@pytest.mark.parametrize("inactive", [False, True])
def test_deleted_charge_is_not_reactivated(finalization, inactive):
    _, records, objects, _, _ = finalization
    row = records.create(
        LEDGER,
        {
            "knowledge_id": 1,
            "index_name": "kb",
            "bucket_name": "files",
            "object_name": "planned/source.txt",
            "raw_bytes": 6,
            "status": "DELETED",
        },
        context=context(),
    )
    if inactive:
        records.delete(
            LEDGER, row["storage_object_id"], expected=Revision("1"), context=context()
        )
    with pytest.raises(Conflict):
        account(records, objects)
    assert records.get(SOURCE, FILE_ID, context=context())["storage_object_id"] is None


@pytest.mark.parametrize("finalization", [b""], indirect=True)
def test_empty_source_keeps_a_valid_zero_byte_charge(finalization):
    finish, records, objects, _, configure = finalization
    configure("0")
    row = account(records, objects)
    assert row["file_size"] == 0 and row["storage_object_id"]
    assert records.sum(LEDGER, "raw_bytes", RecordQuery(), context=context()) == 0
    assert finish() == "uploaded"


@pytest.mark.parametrize("finalization", [b"", b"x"], indirect=True)
def test_boolean_size_is_rejected_even_when_it_equals_byte_count(finalization):
    _, records, objects, _, _ = finalization
    original = objects.stat.return_value
    objects.stat.return_value = ObjectMetadata(
        original.ref, bool(original.size), "text/plain", sha256=original.sha256
    )
    with pytest.raises(OutcomeUnknown):
        account(records, objects)
    assert records.get(SOURCE, FILE_ID, context=context())["storage_object_id"] is None
