# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Source CAS and replay policy with real records and a controlled object provider."""

import hashlib
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from management.services.file.source_publish import SourcePublisher
from nexent.storage.errors import Conflict, OutcomeUnknown, ScopeDenied
from nexent.storage.models import ObjectMetadata, ObjectRef, Revision, StorageScope

from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.source_binding import DATASET, bind_source_records
from test.backend.infrastructure.test_record_store import context

FILE_ID = "a" * 32


@pytest.fixture
def publication():
    engine = sa.create_engine(
        "sqlite://", execution_options={"schema_translate_map": {"nexent": None}}
    )
    table = KnowledgeFileLifecycle.__table__
    table.create(engine)
    with engine.begin() as conn:
        conn.execute(
            table.insert().values(
                file_id=FILE_ID,
                tenant_id="tenant-a",
                knowledge_id=1,
                index_name="kb",
                original_filename="source.txt",
                bucket_name="files",
                object_name="planned/source.txt",
                status="UPLOADING",
                stage="UPLOAD",
                version=0,
                delete_flag="N",
                created_by="user-a",
                updated_by="user-a",
            )
        )
    scope = StorageScope("management", "tenant-a", "user-a", {DATASET})
    records = bind_source_records(scope, engine)
    objects = Mock()
    objects.scope = StorageScope("management", "tenant-a", "user-a", {"files"})

    def put(ref, stream, *, size, content_type, context):
        data = stream.read()
        assert len(data) == size
        result = ObjectMetadata(
            ObjectRef(ref.space, ref.key, Revision("etag:v1")),
            size,
            content_type,
            sha256=hashlib.sha256(data).hexdigest(),
        )
        objects.stat.return_value = result
        return result

    objects.put.side_effect = put

    def update(**values):
        with engine.begin() as conn:
            conn.execute(table.update().values(**values))

    yield SourcePublisher(records, objects), records, objects, update
    records.close()
    engine.dispose()


def publish(publisher, content=b"source"):
    return publisher.publish(
        FILE_ID,
        content,
        content_type="text/plain",
        expected_version=0,
        context=context(),
    )


def test_upload_pins_confirmed_source_and_preserves_generation(publication):
    publisher, records, objects, _ = publication
    result = publish(publisher)
    row = records.get(DATASET, FILE_ID, context=context())
    assert (
        row["source_sha256"] == result.sha256 == hashlib.sha256(b"source").hexdigest()
    )
    assert row["source_generation"] == 0 and row["version"] == 2
    assert row["source_upload_sha256"] == result.sha256
    assert row["status"] == "UPLOADING"
    assert publish(publisher) == result
    objects.put.assert_called_once()
    objects.stat.assert_called_once()


def test_committed_binding_lost_response_reconciles_without_reupload(
    publication, mocker
):
    publisher, records, objects, _ = publication
    original = records.patch

    def committed(*args, **kwargs):
        result = original(*args, **kwargs)
        if "source_revision" in args[2].set_values:
            raise OutcomeUnknown()
        return result

    mocker.patch.object(records, "patch", side_effect=committed)
    with pytest.raises(OutcomeUnknown):
        publish(publisher)
    assert publish(publisher).version == "etag:v1"
    objects.put.assert_called_once()


def test_stale_cas_after_object_write_is_unknown(publication):
    publisher, _, objects, update = publication
    original = objects.put.side_effect

    def write_then_cancel(*args, **kwargs):
        result = original(*args, **kwargs)
        update(status="DELETE_REQUESTED", version=2)
        return result

    objects.put.side_effect = write_then_cancel
    with pytest.raises(OutcomeUnknown):
        publish(publisher)


def test_changed_bytes_never_overwrite_pinned_source(publication):
    publisher, _, objects, _ = publication
    publish(publisher)
    with pytest.raises(Conflict):
        publish(publisher, b"changed")
    objects.put.assert_called_once()


def test_unknown_object_reply_reconciles_existing_version_without_reupload(publication):
    publisher, _, objects, _ = publication
    original = objects.put.side_effect

    def lost_reply(*args, **kwargs):
        original(*args, **kwargs)
        raise OutcomeUnknown()

    objects.put.side_effect = lost_reply
    with pytest.raises(OutcomeUnknown):
        publish(publisher)
    assert publish(publisher).version == "etag:v1"
    objects.put.assert_called_once()


def test_pending_intent_with_different_input_never_reuploads(publication):
    publisher, _, objects, update = publication
    update(
        stage="SOURCE_UPLOAD",
        source_upload_sha256=hashlib.sha256(b"source").hexdigest(),
        file_size=6,
        version=1,
    )
    with pytest.raises(OutcomeUnknown):
        publish(publisher, b"different")
    objects.put.assert_not_called()


@pytest.mark.parametrize(
    "changes", [{"created_by": "other"}, {"status": "DELETE_REQUESTED"}, {"version": 2}]
)
def test_refused_record_never_writes(publication, changes):
    publisher, _, objects, update = publication
    update(**changes)
    with pytest.raises((ScopeDenied, Conflict)):
        publish(publisher)
    objects.put.assert_not_called()
