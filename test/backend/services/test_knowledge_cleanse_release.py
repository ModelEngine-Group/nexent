# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB-RELEASE-01/02: real durable jobs gate one-shot private output cleanup."""

import hashlib
import io
from types import SimpleNamespace

import pytest
from contracts.agentos_knowledge import (
    CleanseArtifact,
    CleanseBlock,
    ObjectReference,
    cleanse_output_prefix,
)
from contracts.knowledge_cleanse import cleanse_lookup
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import (
    DeleteReceipt,
    FieldPatch,
    ObjectMetadata,
    ObjectRef,
    Page,
    PageRequest,
    RecordQuery,
    Revision,
)

from infrastructure.file_processing.artifacts import CleanseArtifacts
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context, setup  # noqa: F401
from test.backend.services.test_knowledge_cleanse_cancellation import (
    prepared,  # noqa: F401
)
from test.backend.services.test_knowledge_cleanse_jobs import knowledge_request


class Objects:
    def __init__(self):
        self.data, self.deleted, self.listed = {}, [], []
        self.closed = 0
        self.unknown = False

    def metadata(self, key):
        if key not in self.data:
            raise NotFound()
        digest = hashlib.sha256(self.data[key]).hexdigest()
        return ObjectMetadata(ObjectRef('files', key, Revision('etag:' + digest)), len(self.data[key]),
                              'application/octet-stream', digest, digest)

    def stat(self, ref, *, context):
        context.remaining()
        return self.metadata(ref.key)

    def open_read(self, ref, *, context):
        context.remaining()
        return io.BytesIO(self.data[ref.key])

    def list(self, prefix, page, *, context):
        context.remaining()
        self.listed.append(prefix)
        keys = sorted(key for key in self.data if key.startswith(prefix))
        start = int(page.cursor or 0)
        selected = keys[start:start + page.limit]
        return Page(tuple(self.metadata(key) for key in selected),
                    str(start + page.limit) if start + page.limit < len(keys) else None)

    def delete(self, ref, *, context):
        context.remaining()
        self.deleted.append(ref.key)
        self.data.pop(ref.key)
        if self.unknown:
            raise OutcomeUnknown()
        return DeleteReceipt(context.operation_id, True)

    def close(self):
        self.closed += 1


@pytest.fixture
def release(prepared, monkeypatch):  # noqa: F811
    p = prepared
    p.update('cleanse_files', stage='DELETE_CLEANSE_PENDING')
    objects, opened = Objects(), []

    def factory(tenant, user, selected, source, *, context):
        assert tenant == 'tenant-a' and user == 'user-b'
        opened.append(selected)
        return CleanseArtifacts(objects, selected, source)

    monkeypatch.setattr('management.services.file.knowledge_cleanse_release.bind_knowledge_cleanse_artifacts', factory)

    def completed(*, status='completed', version=0, key='job', file_id='b' * 32):
        public, worker = p.make(), p.make('worker')
        request = knowledge_request(file_version=version, idempotency_key=key, file_id=file_id)
        state = public.submit(request, context=context())
        handle = worker.claim('worker', job_id=state.job_id, lease_seconds=60, context=context())
        assert worker.begin_execution(handle, context=context())
        prefix = cleanse_output_prefix(cleanse_lookup(handle, request))
        raw = b'private image'
        digest = hashlib.sha256(raw).hexdigest()
        image_key = prefix + 'images/' + request.source.sha256 + '/' + digest + '.png'
        objects.data[image_key] = raw
        metadata = objects.metadata(image_key)
        image = ObjectReference(space='files', key=image_key, version=metadata.ref.version.value, sha256=digest)
        artifact = CleanseArtifact(source=request.source, parser_version='parser-v1', blocks=[
            CleanseBlock(ordinal=0, kind='image', sha256=digest, object_ref=image),
        ])
        body = artifact.model_dump_json().encode()
        artifact_key = prefix + 'artifacts/' + request.source.sha256 + '/' + hashlib.sha256(body).hexdigest() + '.json'
        objects.data[artifact_key] = body
        metadata = objects.metadata(artifact_key)
        reference = ObjectReference(space='files', key=artifact_key, version=metadata.ref.version.value, sha256=metadata.sha256)
        assert worker.finish_execution(handle, context=context())
        assert worker.transition(handle, status=status, artifact=reference if status == 'completed' else None, context=context())
        return public, state, prefix

    def cleanup():
        return p.service.cleanup_file(p.reference, tenant_id='tenant-a', user_id='user-b', context=context())

    return SimpleNamespace(**locals())


def test_current_editor_releases_another_uploaders_private_job_without_impersonation(release):
    s = release
    public, _state, prefix = s.completed()
    result = s.cleanup()
    assert result['execution_drained'] and result['artifacts_released']
    row = public.records.query('file_cleanse_jobs', RecordQuery(), PageRequest(limit=1), context=context()).items[0]
    assert row['status'] == 'released' and row['artifact'] is None and not row['reconcile_required']
    assert row['user_id'] == 'user-a' and row['updated_by'] == 'user-b'
    assert row['artifact_prefix'] == prefix and len(s.objects.deleted) == 2
    assert '/images/' in s.objects.deleted[0] and '/artifacts/' in s.objects.deleted[1]
    assert public.state(row).status == 'released'
    assert s.cleanup()['artifacts_released'] and len(s.objects.deleted) == 2


def test_unknown_delete_is_never_replayed_and_only_absence_can_finalize(release):
    s = release
    s.completed()
    s.objects.unknown = True
    with pytest.raises(OutcomeUnknown):
        s.cleanup()
    assert len(s.objects.deleted) == 1
    assert not s.cleanup()['artifacts_released']
    assert len(s.objects.deleted) == 1
    s.objects.data.clear()
    assert s.cleanup()['artifacts_released']
    assert len(s.objects.deleted) == 1


@pytest.mark.parametrize('changed', [{'artifact_prefix': None}, {'execution_ended': None}, {'execution_ended': False}])
def test_unknown_history_or_live_writer_does_not_get_cleanup_power(release, changed):
    s = release
    public, _state, _prefix = s.completed()
    row = public.records.query('file_cleanse_jobs', RecordQuery(), PageRequest(limit=1), context=context()).items[0]
    public.records.patch('file_cleanse_jobs', row['id'], FieldPatch(set_values=changed), context=context())
    assert not s.cleanup()['artifacts_released']
    assert not s.opened and not s.objects.deleted


@pytest.mark.parametrize('dataset,changed', [('cleanse_memberships', {'delete_flag': 'Y'}),
                                           ('cleanse_files', {'stage': 'DELETE_ACCEPTED'})])
def test_revocation_or_runtime_not_yet_confirmed_blocks_release(release, dataset, changed):
    s = release
    s.completed()
    s.p.update(dataset, **changed)
    with pytest.raises(ScopeDenied):
        s.cleanup()
    assert not s.opened


def test_closed_failed_job_partial_outputs_are_cleaned_only_in_its_attested_directory(release):
    s = release
    public, _state, _prefix = s.completed(status='failed')
    s.objects.data['images/shared-must-remain.png'] = b'not owned'
    assert not s.cleanup()['artifacts_released']
    assert not s.opened
    # Explicit maintenance reconciliation is a separate prerequisite, never an automatic retry.
    row = public.records.query('file_cleanse_jobs', RecordQuery(), PageRequest(limit=1), context=context()).items[0]
    public.records.patch('file_cleanse_jobs', row['id'], FieldPatch(set_values={'reconcile_required': False}), context=context())
    assert s.cleanup()['artifacts_released']
    assert s.objects.data == {'images/shared-must-remain.png': b'not owned'}


def test_wrong_hash_preserves_all_objects_before_the_first_delete(release):
    s = release
    s.completed()
    key = next(key for key in s.objects.data if '/images/' in key)
    s.objects.data[key] = b'corrupted'
    with pytest.raises(Conflict):
        s.cleanup()
    assert not s.objects.deleted


def test_unstarted_job_is_released_without_any_object_capability(release):
    s = release
    public = s.p.make()
    public.submit(knowledge_request(), context=context())
    assert s.cleanup()['artifacts_released']
    assert not s.opened
    row = public.records.query('file_cleanse_jobs', RecordQuery(), PageRequest(limit=1), context=context()).items[0]
    assert row['status'] == 'released' and row['user_id'] == 'user-a'


def test_job_and_object_pagination_cannot_skip_later_private_outputs(release):
    s = release
    for number in range(101):
        s.completed(key=f'job-{number}')
    assert s.cleanup()['artifacts_released']
    assert len(s.objects.deleted) == 202 and not s.objects.data
    assert len(s.opened) == 101


def test_inventory_reads_every_object_page_before_deleting(release):
    s = release
    _public, _state, prefix = s.completed()
    for number in range(101):
        body = f'orphan image {number}'.encode()
        digest = hashlib.sha256(body).hexdigest()
        s.objects.data[prefix + 'images/' + knowledge_request().source.sha256 + '/' + digest + '.png'] = body
    assert s.cleanup()['artifacts_released']
    assert len(s.objects.deleted) == 103 and '/artifacts/' in s.objects.deleted[-1]


def test_read_timeout_does_not_reserve_or_send_a_delete(release, monkeypatch):
    s = release
    public, _state, _prefix = s.completed()

    def timeout(*args, **kwargs):
        raise DeadlineExceeded()

    monkeypatch.setattr(s.objects, 'list', timeout)
    with pytest.raises(DeadlineExceeded):
        s.cleanup()
    row = public.records.query('file_cleanse_jobs', RecordQuery(), PageRequest(limit=1), context=context()).items[0]
    assert row['status'] == 'completed' and not row['reconcile_required']
    assert not s.objects.deleted and s.objects.closed == 1


def test_revision_change_during_inventory_prevents_all_deletes(release, monkeypatch):
    s = release
    public, _state, _prefix = s.completed()
    opened = s.objects.open_read
    changed = []

    def change(ref, *, context):
        if not changed:
            row = public.records.query('file_cleanse_jobs', RecordQuery(), PageRequest(limit=1), context=context).items[0]
            public.records.patch('file_cleanse_jobs', row['id'], FieldPatch(set_values={'error_code': 'changed'}), context=context)
            changed.append(True)
        return opened(ref, context=context)

    monkeypatch.setattr(s.objects, 'open_read', change)
    with pytest.raises(Conflict):
        s.cleanup()
    assert not s.objects.deleted and s.objects.closed == 1


def test_other_file_and_newer_generation_keep_all_their_outputs(release):
    s = release
    s.completed()
    _public, _state, newer = s.completed(version=1)
    _public, _state, other = s.completed(file_id='c' * 32)
    assert s.cleanup()['artifacts_released']
    assert len(s.objects.data) == 4 and len(s.objects.deleted) == 2
    assert all(key.startswith((newer, other)) for key in s.objects.data)


def test_empty_first_listing_page_is_not_physical_absence():
    from unittest.mock import Mock

    from management.services.file.knowledge_artifact_cleanup import (
        private_directory_absent,
    )

    objects = Mock()
    objects.list.side_effect = [Page((), 'next'), Page(('remaining',))]
    assert not private_directory_absent(objects, 'known/', context=context())
    assert objects.list.call_count == 2


def test_old_queued_job_gets_its_prefix_attested_before_any_execution(release):
    s = release
    public, worker = s.p.make(), s.p.make('worker')
    request = knowledge_request()
    state = public.submit(request, context=context())
    row = public.records.query('file_cleanse_jobs', RecordQuery(), PageRequest(limit=1), context=context()).items[0]
    assert row['artifact_prefix'] == cleanse_output_prefix(cleanse_lookup(row, request))
    public.records.patch('file_cleanse_jobs', row['id'], FieldPatch(set_values={'artifact_prefix': None}), context=context())
    handle = worker.claim('worker', job_id=state.job_id, lease_seconds=60, context=context())
    assert handle['artifact_prefix'] is None
    assert worker.begin_execution(handle, context=context())
    actual = public.records.get('file_cleanse_jobs', row['id'], context=context())
    assert actual['artifact_prefix'] == row['artifact_prefix'] and actual['reconcile_required']
    assert actual['execution_ended'] is False


@pytest.mark.parametrize('target', ['shared', 'other-job', 'other-source', 'other-space'])
def test_private_prefix_cannot_confirm_cleanup_of_an_unowned_artifact(release, target):
    s = release
    public, _state, _prefix = s.completed()
    row = public.records.query('file_cleanse_jobs', RecordQuery(), PageRequest(limit=1), context=context()).items[0]
    reference = dict(row['artifact'])
    if target == 'shared':
        reference['key'] = 'artifacts/shared/' + reference['sha256'] + '.json'
    elif target == 'other-job':
        reference['key'] = reference['key'].replace(row['job_id'], 'e' * 32)
    elif target == 'other-source':
        reference['key'] = reference['key'].replace(knowledge_request().source.sha256, 'e' * 64)
    else:
        reference['space'] = 'other'
    public.records.patch('file_cleanse_jobs', row['id'], FieldPatch(set_values={'artifact': reference}), context=context())
    with pytest.raises(Conflict):
        s.cleanup()
    assert not s.opened and not s.objects.deleted
