# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Source recovery confirms identity while preserving ownership and cancellation."""

import hashlib
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from management.services.file.source_reconcile import SourceReconciler
from nexent.storage.errors import NotFound, ScopeDenied, Unavailable
from nexent.storage.models import FieldPatch, ObjectMetadata, ObjectRef, Revision

from infrastructure.rdb.source_binding import DATASET
from test.backend.infrastructure.test_record_store import context
from test.backend.services import test_source_publish as source_fixtures
from test.backend.services.test_source_publish import FILE_ID, publish

publication = source_fixtures.publication
NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


@pytest.fixture
def recovery(publication):
    _, records, objects, update = publication
    update(
        stage="SOURCE_UPLOAD",
        upload_owner_service="nexent-config",
        source_upload_sha256=hashlib.sha256(b"source").hexdigest(),
        file_size=6,
        source_upload_started_at=NOW - timedelta(minutes=10),
        version=1,
    )
    objects.put(
        ObjectRef("files", "planned/source.txt"),
        BytesIO(b"source"),
        size=6,
        content_type="text/plain",
        context=context(),
    )
    objects.put.reset_mock()
    reconciler = SourceReconciler(records, objects, clock=lambda: NOW)

    def run(**overrides):
        args = {
            "owner_service": "nexent-config",
            "owner_user_id": "user-a",
            "expected_version": 1,
            "cutoff": NOW - timedelta(minutes=5),
            "context": context(),
        }
        args.update(overrides)
        return reconciler.reconcile(FILE_ID, **args)

    return run, records, objects, update


def test_confirms_identity_without_upload_accounting_or_object_mutation(recovery):
    run, records, objects, _ = recovery
    assert run() == "confirmed"
    row = records.get(DATASET, FILE_ID, context=context())
    assert row["stage"] == "SOURCE_CONFIRMED" and row["status"] == "UPLOADING"
    assert row["source_revision"] == "etag:v1" and row["source_generation"] == 0
    assert row["version"] == 2 and row["error_code"] is None
    assert run() == "stale"
    objects.put.assert_not_called()
    objects.delete.assert_not_called()


def test_missing_object_delays_next_check_without_retransmission(recovery):
    run, records, objects, _ = recovery
    objects.stat.side_effect = NotFound()
    assert run() == "pending"
    row = records.get(DATASET, FILE_ID, context=context())
    assert row["error_code"] == "SOURCE_UPLOAD_PENDING"
    assert datetime.fromisoformat(row["source_reconcile_after"]) == NOW + timedelta(
        minutes=5
    )
    assert run(expected_version=2) == "waiting"
    objects.stat.assert_called_once()
    objects.put.assert_not_called()


def test_changed_object_requires_review_and_is_never_deleted(recovery):
    run, records, objects, _ = recovery
    original = objects.stat.return_value
    objects.stat.return_value = ObjectMetadata(
        original.ref, 6, "text/plain", sha256="0" * 64
    )
    assert run() == "review"
    row = records.get(DATASET, FILE_ID, context=context())
    assert row["stage"] == "SOURCE_REVIEW" and row["source_revision"] is None
    assert row["error_code"] == "SOURCE_IDENTITY_MISMATCH"
    assert run(expected_version=2) == "stale"
    objects.put.assert_not_called()
    objects.delete.assert_not_called()


@pytest.mark.parametrize(
    "changes", [{"owner_service": "other"}, {"owner_user_id": "other"}]
)
def test_original_upload_ownership_required_before_object_access(recovery, changes):
    run, _, objects, _ = recovery
    with pytest.raises(ScopeDenied):
        run(**changes)
    objects.stat.assert_not_called()


@pytest.mark.parametrize(
    "values",
    [{"status": "DELETE_REQUESTED"}, {"version": 2}, {"source_upload_started_at": NOW}],
)
def test_stale_or_young_upload_is_not_examined(recovery, values):
    run, _, objects, update = recovery
    update(**values)
    assert run() in {"stale", "waiting"}
    objects.stat.assert_not_called()


def test_cancel_during_object_stat_wins_over_source_binding(recovery):
    run, records, objects, update = recovery
    metadata = objects.stat.return_value

    def cancelled(*args, **kwargs):
        update(status="DELETE_REQUESTED", version=2)
        return metadata

    objects.stat.side_effect = cancelled
    assert run() == "stale"
    row = records.get(DATASET, FILE_ID, context=context())
    assert row["status"] == "DELETE_REQUESTED" and row["source_revision"] is None


def test_transport_failure_preserves_intent(recovery):
    run, records, objects, _ = recovery
    objects.stat.side_effect = Unavailable()
    with pytest.raises(Unavailable):
        run()
    row = records.get(DATASET, FILE_ID, context=context())
    assert row["stage"] == "SOURCE_UPLOAD" and row["version"] == 1


def test_uploader_converges_when_reconciler_pins_same_source_first(publication):
    publisher, records, objects, _ = publication
    original = objects.put.side_effect

    def recover_first(*args, **kwargs):
        metadata = original(*args, **kwargs)
        receipt = records.patch(
            DATASET,
            FILE_ID,
            FieldPatch(
                set_values={
                    "source_space": "files",
                    "source_key": metadata.ref.key,
                    "source_revision": metadata.ref.version.value,
                    "source_sha256": metadata.sha256,
                    "stage": "SOURCE_CONFIRMED",
                }
            ),
            expected=Revision("1"),
            context=context(),
        )
        assert receipt.matched
        return metadata

    objects.put.side_effect = recover_first
    assert publish(publisher).version == "etag:v1"
    objects.put.assert_called_once()
