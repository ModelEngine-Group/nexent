# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Release reserves a completed run job and never replays uncertain object writes."""

import hashlib
from contextlib import contextmanager
from io import BytesIO
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import (
    CleanseArtifact,
    CleanseBlock,
    FileCleanseLookup,
    ObjectReference,
)
from management.services.file import run_cleanse_service
from management.services.file.cleanse_jobs import DATASET
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import (
    DeleteReceipt,
    ObjectMetadata,
    ObjectRef,
    PageRequest,
    RecordQuery,
    Revision,
)

from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context, lookup
from test.backend.services.test_knowledge_cleanse_service import (
    admission as admission,  # noqa: PLC0414
)
from test.backend.services.test_run_cleanse_service import api as api  # noqa: PLC0414
from test.backend.services.test_run_cleanse_service import request


@pytest.fixture
def completed(api, mocker):
    service, update, _ = api
    state = service.submit(
        request(), tenant_id="tenant-a", user_id="user-a", context=context()
    )
    reference = lookup(state)
    prefix = f"run-cleanse/{reference.run_id}/{reference.job_id}/"
    image_bytes = b"image"
    image_digest = hashlib.sha256(image_bytes).hexdigest()
    image = ObjectReference(
        space="files",
        key=prefix + f"images/{request().source.sha256}/{image_digest}.png",
        version="etag:image",
        sha256=image_digest,
    )
    manifest = CleanseArtifact(
        source=request().source,
        parser_version="parser-v1",
        blocks=[
            CleanseBlock(ordinal=0, kind="image", sha256=image_digest, object_ref=image)
        ],
    )
    body = manifest.model_dump_json().encode()
    digest = hashlib.sha256(body).hexdigest()
    artifact = ObjectReference(
        space="files",
        key=prefix + f"artifacts/{request().source.sha256}/{digest}.json",
        version="etag:manifest",
        sha256=digest,
    )
    with service._jobs("tenant-a", "user-a", context()) as jobs:
        handle = jobs.claim(
            "worker", job_id=state.job_id, lease_seconds=60, context=context()
        )
        handle = jobs.record(reference, context=context())
        assert jobs.transition(
            handle, status="completed", artifact=artifact, context=context()
        )
    data = {image.key: image_bytes, artifact.key: body}
    refs = {image.key: image, artifact.key: artifact}
    deletes = []
    port = Mock()

    def stat(ref, *, context):
        current = refs[ref.key]
        return ObjectMetadata(
            ObjectRef(current.space, current.key, Revision(current.version)),
            len(data[ref.key]),
            "test",
            sha256=current.sha256,
        )

    @contextmanager
    def open_read(ref, *, context):
        with BytesIO(data[ref.key]) as stream:
            yield stream

    def delete(ref, *, context):
        deletes.append(ref.key)
        del data[ref.key]
        return DeleteReceipt(context.operation_id, True)

    port.stat.side_effect = stat
    port.open_read.side_effect = open_read
    port.delete.side_effect = delete
    factory = mocker.patch.object(
        run_cleanse_service, "bind_run_cleanse_artifacts", return_value=port
    )
    return service, reference, port, data, deletes, factory, update


def release(service, reference):
    return service.release(
        reference, tenant_id="tenant-a", user_id="user-a", context=context()
    )


def test_release_verifies_images_before_deleting_and_remains_idempotent(completed):
    service, reference, port, data, deletes, factory, _ = completed
    assert release(service, reference).released is True
    assert not data and len(deletes) == 2
    assert "/images/" in deletes[0] and "/artifacts/" in deletes[1]
    port.close.assert_called_once()
    assert release(service, reference).released is True
    factory.assert_called_once()
    assert (
        service.inspect(
            reference, tenant_id="tenant-a", user_id="user-a", context=context()
        ).status
        == "released"
    )


@pytest.mark.parametrize("failure", ["corrupt", "unknown", "unconfirmed"])
def test_failed_release_retains_marker_and_never_repeats_cleanup(completed, failure):
    service, reference, port, data, _, factory, _ = completed
    if failure == "corrupt":
        image_key = next(key for key in data if "/images/" in key)
        data[image_key] = b"corrupted"
    elif failure == "unknown":
        port.delete.side_effect = OutcomeUnknown()
    else:
        port.delete.side_effect = lambda *args, **kwargs: DeleteReceipt("test", False)
    with pytest.raises(InvalidInput if failure == "corrupt" else OutcomeUnknown):
        release(service, reference)
    previous = port.delete.call_count
    with pytest.raises(Conflict):
        release(service, reference)
    assert port.delete.call_count == previous
    factory.assert_called_once()
    with pytest.raises(Conflict):
        service.inspect(
            reference, tenant_id="tenant-a", user_id="user-a", context=context()
        )
    with service._jobs("tenant-a", "user-a", context()) as jobs:
        row = jobs.records.query(
            DATASET, RecordQuery(), PageRequest(), context=context()
        ).items[0]
        assert (
            row["reconcile_required"] and row["error_code"] == "FILE_CLEANSE_RELEASING"
        )


def test_wrong_run_release_does_not_open_objects(completed):
    service, reference, _, data, deletes, factory, _ = completed
    with pytest.raises(NotFound):
        release(service, reference.model_copy(update={"run_id": "b" * 32}))
    factory.assert_not_called()
    assert len(data) == 2 and not deletes


@pytest.mark.parametrize("status", ["queued", "running", "cancelled", "failed"])
def test_unconfirmed_terminal_or_live_job_cannot_release(api, mocker, status):
    service, _, _ = api
    state = service.submit(
        request(), tenant_id="tenant-a", user_id="user-a", context=context()
    )
    with service._jobs("tenant-a", "user-a", context()) as jobs:
        row = jobs.record(lookup(state), context=context())
        from nexent.storage.models import FieldPatch

        jobs.records.patch(
            DATASET,
            row["id"],
            FieldPatch(set_values={"status": status}),
            expected=Revision(str(row["revision"])),
            context=context(),
        )
    factory = mocker.patch.object(run_cleanse_service, "bind_run_cleanse_artifacts")
    with pytest.raises(Conflict):
        release(service, lookup(state))
    factory.assert_not_called()


@pytest.mark.parametrize("revoked", ["cleanse_memberships", "cleanse_accounts"])
def test_release_rechecks_live_identity_before_opening_objects(completed, revoked):
    service, reference, _, data, deletes, factory, update = completed
    update(revoked, delete_flag="Y")
    with pytest.raises(ScopeDenied):
        release(service, reference)
    factory.assert_not_called()
    assert len(data) == 2 and not deletes


def test_reservation_cas_rejects_stale_revision_before_any_object_access(completed):
    service, reference, _, _, _, factory, _ = completed
    with service._jobs("tenant-a", "user-a", context()) as jobs:
        row = jobs.record(reference, context=context())
        handle = jobs.begin_release(
            reference, revision=row["revision"], context=context()
        )
        with pytest.raises(Conflict):
            jobs.begin_release(reference, revision=row["revision"], context=context())
        assert handle["revision"] > row["revision"]
    with pytest.raises(Conflict):
        release(service, reference)
    factory.assert_not_called()


def test_lost_final_commit_does_not_repeat_object_deletion(completed, mocker):
    from management.services.file.cleanse_jobs import CleanseJobs

    service, reference, port, data, deletes, factory, _ = completed
    mocker.patch.object(CleanseJobs, "finish_release", side_effect=Conflict())
    with pytest.raises(Conflict):
        release(service, reference)
    assert not data and len(deletes) == 2
    with pytest.raises(Conflict):
        release(service, reference)
    factory.assert_called_once()
    assert port.delete.call_count == 2


@pytest.mark.parametrize("changed", ["source", "parser"])
def test_manifest_identity_is_verified_before_deleting_anything(changed):
    from management.services.file.cleanse_release import release_artifacts

    reference = request()
    scope = FileCleanseLookup(run_id=reference.run_id, job_id="c" * 32)
    manifest = CleanseArtifact(
        source=reference.source
        if changed != "source"
        else reference.source.model_copy(update={"key": "other.txt"}),
        parser_version="wrong" if changed == "parser" else "v1",
        blocks=[],
    )
    body = manifest.model_dump_json().encode()
    digest = hashlib.sha256(body).hexdigest()
    artifact = ObjectReference(
        space="files",
        key=f"run-cleanse/{scope.run_id}/{scope.job_id}/artifacts/{reference.source.sha256}/{digest}.json",
        version="etag:1",
        sha256=digest,
    )
    ref = ObjectRef(artifact.space, artifact.key, Revision(artifact.version))

    @contextmanager
    def open_read(*args, **kwargs):
        with BytesIO(body) as stream:
            yield stream

    objects = Mock()
    objects.stat.return_value = ObjectMetadata(
        ref, len(body), "application/json", sha256=digest
    )
    objects.open_read.side_effect = open_read
    row = {
        "scope_kind": "run",
        "run_id": reference.run_id,
        "request_payload": reference.model_dump(mode="json"),
        "parser_version": "v1",
        "artifact": artifact.model_dump(mode="json"),
    }
    with pytest.raises(InvalidInput):
        release_artifacts(objects, row, scope, limit=10000, context=context())
    objects.delete.assert_not_called()
