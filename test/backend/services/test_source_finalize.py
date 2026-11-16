# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Recovery commits retained-byte accounting before authoritative quota admission."""

from contextlib import contextmanager

import pytest
from management.services.file.source_finalize import SourceFinalizer
from nexent.storage.errors import Conflict, OutcomeUnknown, ScopeDenied
from nexent.storage.models import ObjectMetadata, RecordQuery, Revision, StorageScope

from infrastructure.rdb.knowledge_storage_record import KnowledgeStorageObject
from infrastructure.rdb.source_binding import DATASET as SOURCE
from infrastructure.rdb.tenant_config_record import TenantConfig
from infrastructure.rdb.upload_records import LEDGER, QUOTA, bind_upload_records
from test.backend.infrastructure.test_record_store import context
from test.backend.services import test_source_publish as source_fixtures
from test.backend.services.test_source_publish import FILE_ID, publish

publication = source_fixtures.publication


@pytest.fixture
def finalization(publication, monkeypatch, request):
    publisher, source, objects, update = publication
    publish(publisher, getattr(request, "param", b"source"))
    update(upload_owner_service="nexent-config")
    engine = source._engine
    # SQLite needs INTEGER for automatic IDs; PostgreSQL sequence behavior is proved in D3.
    monkeypatch.setattr(
        engine.dialect.type_compiler_instance,
        "visit_BIGINT",
        lambda *_a, **_k: "INTEGER",
    )
    KnowledgeStorageObject.__table__.create(engine)
    TenantConfig.__table__.create(engine)
    records = bind_upload_records(
        StorageScope("management", "tenant-a", "recovery", {SOURCE, LEDGER, QUOTA}),
        engine,
        with_policy=True,
    )
    objects.scope = StorageScope("management", "tenant-a", "recovery", {"files"})

    def configure(value, *, tenant="tenant-a", key="KB_QUOTA_TENANT_HARD_LIMIT_BYTES"):
        with engine.begin() as conn:
            conn.execute(
                TenantConfig.__table__.insert().values(
                    tenant_id=tenant,
                    config_key=key,
                    config_value=value,
                    delete_flag="N",
                )
            )

    def finish(**overrides):
        arguments = {
            "owner_user_id": "user-a",
            "owner_service": "nexent-config",
            "context": context(),
        }
        arguments.update(overrides)
        return SourceFinalizer(records, objects).finish(FILE_ID, **arguments)

    yield finish, records, objects, update, configure
    records.close()


def test_success_and_replay_preserve_one_charge(finalization):
    finish, records, objects, _, _ = finalization
    assert finish() == "uploaded"
    row = records.get(SOURCE, FILE_ID, context=context())
    assert row["status"] == "UPLOADED" and row["stage"] == "UPLOAD"
    assert row["created_by"] == "user-a" and row["updated_by"] == "recovery"
    assert row["uploaded_at"] and row["storage_object_id"]
    assert records.sum(LEDGER, "raw_bytes", RecordQuery(), context=context()) == 6
    assert finish() == "uploaded"
    objects.put.assert_called_once()
    objects.delete.assert_not_called()


@pytest.mark.parametrize(
    "limit,expected",
    [
        ("6", "uploaded"),
        ("5", "quota_review"),
        ("0", "quota_review"),
        ("invalid", "uploaded"),
    ],
)
def test_quota_matches_existing_limit_parsing_and_boundary(
    finalization, limit, expected
):
    finish, records, _, _, configure = finalization
    configure(limit)
    assert finish() == expected
    row = records.get(SOURCE, FILE_ID, context=context())
    ledger = records.get(LEDGER, row["storage_object_id"], context=context())
    assert ledger["raw_bytes"] == 6 and ledger["status"] == "COMMITTED"
    if expected == "quota_review":
        assert row["status"] == "UPLOADING" and row["stage"] == "SOURCE_REVIEW"
        assert row["error_code"] == "STORAGE_QUOTA_EXCEEDED"


def test_foreign_and_unrelated_configuration_cannot_limit_upload(finalization):
    finish, _, _, _, configure = finalization
    configure("0", tenant="tenant-b")
    configure("0", key="unrelated")
    assert finish() == "uploaded"


def test_ambiguous_config_preserves_accounted_intent_without_success(finalization):
    finish, records, _, _, configure = finalization
    configure("6")
    configure("60")
    with pytest.raises(ScopeDenied):
        finish()
    row = records.get(SOURCE, FILE_ID, context=context())
    assert row["status"] == "UPLOADING" and row["stage"] == "SOURCE_ACCOUNTED"


def test_unknown_account_commit_replays_without_second_charge(finalization, mocker):
    finish, records, _, _, _ = finalization
    original, lost = records.transaction, []

    @contextmanager
    def lost_reply(**kwargs):
        fail = False
        with original(**kwargs) as tx:
            yield tx
            row = tx.get(SOURCE, FILE_ID, context=context())
            if row["stage"] == "SOURCE_ACCOUNTED" and not lost:
                lost.append(True)
                fail = True
        if fail:
            raise OutcomeUnknown()

    mocker.patch.object(records, "transaction", side_effect=lost_reply)
    from management.services.knowledge_base.usage_cache import _usage_cache

    _usage_cache["tenant-a"] = (0, {"total_bytes": 0})
    with pytest.raises(OutcomeUnknown):
        finish()
    assert "tenant-a" not in _usage_cache
    before = records.get(SOURCE, FILE_ID, context=context())
    assert before["stage"] == "SOURCE_ACCOUNTED"
    assert finish() == "uploaded"
    after = records.get(SOURCE, FILE_ID, context=context())
    assert after["storage_object_id"] == before["storage_object_id"]


def test_unknown_final_publish_commit_replays_without_reaccounting(
    finalization, mocker
):
    finish, records, _, _, _ = finalization
    original, lost = records.transaction, []

    @contextmanager
    def lost_reply(**kwargs):
        fail = False
        with original(**kwargs) as tx:
            yield tx
            row = tx.get(SOURCE, FILE_ID, context=context())
            if row["status"] == "UPLOADED" and not lost:
                lost.append(True)
                fail = True
        if fail:
            raise OutcomeUnknown()

    mocker.patch.object(records, "transaction", side_effect=lost_reply)
    with pytest.raises(OutcomeUnknown):
        finish()
    assert records.get(SOURCE, FILE_ID, context=context())["status"] == "UPLOADED"
    assert finish() == "uploaded"
    assert records.sum(LEDGER, "raw_bytes", RecordQuery(), context=context()) == 6


def test_cancellation_after_stat_prevents_accounting(finalization):
    finish, records, objects, update, _ = finalization
    metadata = objects.stat.return_value

    def cancel(*args, **kwargs):
        update(status="DELETE_REQUESTED", version=3)
        return metadata

    objects.stat.side_effect = cancel
    with pytest.raises(Conflict):
        finish()
    assert records.get(SOURCE, FILE_ID, context=context())["storage_object_id"] is None


@pytest.mark.parametrize(
    "overrides", [{"owner_user_id": "other"}, {"owner_service": "other"}]
)
def test_original_owner_is_required_before_object_access(finalization, overrides):
    finish, _, objects, _, _ = finalization
    with pytest.raises(ScopeDenied):
        finish(**overrides)
    objects.stat.assert_not_called()


def test_changed_source_does_not_create_ledger(finalization):
    finish, records, objects, _, _ = finalization
    original = objects.stat.return_value
    objects.stat.return_value = ObjectMetadata(
        original.ref, 6, "text/plain", sha256="0" * 64
    )
    with pytest.raises(OutcomeUnknown):
        finish()
    assert records.get(SOURCE, FILE_ID, context=context())["storage_object_id"] is None


@pytest.mark.parametrize(
    "deleted,expected", [(False, "quota_review"), (True, "uploaded")]
)
def test_quota_includes_orphan_charges_and_excludes_deleted_rows(
    finalization, deleted, expected
):
    finish, records, _, _, configure = finalization
    other = records.create(
        LEDGER,
        {
            "knowledge_id": 999,
            "index_name": "orphan",
            "bucket_name": "files",
            "object_name": "orphan.txt",
            "raw_bytes": 4,
            "status": "COMMITTED",
        },
        context=context(),
    )
    if deleted:
        records.delete(
            LEDGER,
            other["storage_object_id"],
            expected=Revision("1"),
            context=context(),
        )
    configure("6")
    assert finish() == expected


def test_mismatched_existing_charge_is_not_adopted(finalization):
    finish, records, _, _, _ = finalization
    records.create(
        LEDGER,
        {
            "knowledge_id": 1,
            "index_name": "kb",
            "bucket_name": "files",
            "object_name": "planned/source.txt",
            "raw_bytes": 7,
            "status": "COMMITTED",
        },
        context=context(),
    )
    with pytest.raises(Conflict):
        finish()
    assert records.get(SOURCE, FILE_ID, context=context())["storage_object_id"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "DELETE_REQUESTED", "version": 4},
        {"source_generation": 1, "version": 4},
    ],
)
def test_cancel_or_generation_change_between_phases_wins(finalization, mocker, changes):
    finish, records, _, update, _ = finalization
    original, changed = records.transaction, []

    @contextmanager
    def concurrent_update(**kwargs):
        modify = False
        with original(**kwargs) as tx:
            yield tx
            row = tx.get(SOURCE, FILE_ID, context=context())
            if row["stage"] == "SOURCE_ACCOUNTED" and not changed:
                changed.append(True)
                modify = True
        if modify:
            update(**changes)

    mocker.patch.object(records, "transaction", side_effect=concurrent_update)
    with pytest.raises(Conflict):
        finish()
    assert records.get(SOURCE, FILE_ID, context=context())["status"] != "UPLOADED"


def test_stale_candidate_version_is_rejected_before_object_access(finalization):
    finish, _, objects, _, _ = finalization
    with pytest.raises(Conflict):
        finish(expected_version=1)
    objects.stat.assert_not_called()
