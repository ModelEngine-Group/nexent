# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-KB-PARENT-01/02/03/04: durable parent ordering and no replay."""

import asyncio
from contextlib import contextmanager
from dataclasses import replace
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeUpstreamError
from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from contracts.knowledge_admission import UPLOAD_ADMISSION_DATASET as FILES
from contracts.knowledge_admission import KnowledgeBaseDeletionIntent
from contracts.knowledge_base_deletion import (
    KnowledgeBaseDeleteState,
    knowledge_base_deletion_id,
)
from contracts.knowledge_deletion import KnowledgeDeletionIntent
from management.services.knowledge_base.base_deletion import (
    KnowledgeBaseDeletionJournal,
    request_knowledge_base_deletion,
)
from management.services.knowledge_base.base_deletion_coordinator import (
    KnowledgeBaseDeletionCoordinator,
)
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import FieldPatch, Page, Revision, WriteOutcome, WriteReceipt

from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_coordinator import (
    sqlite_threads,  # noqa: F401
)
from test.backend.services.test_knowledge_upload_admission import (
    admission,  # noqa: F401
)


@pytest.fixture
def parent(sqlite_threads, admission, monkeypatch):  # noqa: F811
    s = admission

    @contextmanager
    def ports(actor, *, context):
        assert actor == s.actor
        context.remaining()
        yield s.records, s.authorized

    async def blocking(name, fn, *args, **kwargs):
        kwargs.pop('lane')
        kwargs.pop('owner')
        return await asyncio.to_thread(fn, *args, **kwargs)

    monkeypatch.setattr('management.services.knowledge_base.base_deletion_coordinator.run_blocking', blocking)
    client = SimpleNamespace(delete_knowledge_base=AsyncMock(), inspect_knowledge_base_deletion=AsyncMock())
    files = SimpleNamespace(request=AsyncMock())
    coordinator = KnowledgeBaseDeletionCoordinator(files, client, ports=ports)
    journal = KnowledgeBaseDeletionJournal(s.records, s.authorized, s.actor)

    def admit():
        return request_knowledge_base_deletion(s.records, s.authorized, 'kb-one', s.actor, context=context())

    def completed(payload):
        return KnowledgeBaseDeleteState(knowledge_id=1,
                                       job_id=knowledge_base_deletion_id(payload, 'tenant-a', 'user-a'),
                                       status='deleted', physical_cleanup_complete=True)

    async def delete(payload, **kwargs):
        # This is observed at the actual RPC boundary, before any reply.
        current = await asyncio.to_thread(s.records.get, KB, 1, context=context())
        assert current['deletion_request']['phase'] == 'collection_submitting'
        return completed(payload)

    client.delete_knowledge_base.side_effect = delete
    return SimpleNamespace(**locals())


def test_old_snapshot_defaults_to_files_and_phase_transition_is_cas(parent):
    p = parent
    row = p.admit()
    old = {key: value for key, value in row['deletion_request'].items() if key != 'phase'}
    assert KnowledgeBaseDeletionIntent.model_validate(old).phase == 'files'
    submitted, payload = p.journal.begin_collection(row, context=context())
    assert submitted['deletion_request']['phase'] == 'collection_submitting'
    assert submitted['version'] == row['version'] + 1
    assert p.journal.lookup(submitted).job_id == p.completed(payload).job_id
    with pytest.raises(Conflict):
        p.journal.begin_collection(row, context=context())
    ready = p.journal.observe_collection(submitted, p.completed(payload), context=context())
    assert ready['deletion_request']['phase'] == 'metadata_pending'
    assert ready['delete_flag'] == 'N'
    with pytest.raises(Conflict):
        p.journal.begin_collection(ready, context=context())


def test_collection_reservation_requires_every_full_file_terminal(parent):
    p, s = parent, parent.s
    s.service.admit([s.spec(object_name=None, bucket_name=None)], context=context())
    s.records.patch(FILES, 'a' * 32, FieldPatch(set_values={'status': 'FAILED'}), expected=None, context=context())
    row = p.admit()
    with pytest.raises(Conflict):
        p.journal.begin_collection(row, context=context())
    assert s.records.get(KB, 1, context=context()) == row


@pytest.mark.parametrize('field,value', [('knowledge_id', 2), ('job_id', 'f' * 32)])
def test_foreign_collection_reply_never_advances(parent, field, value):
    p = parent
    row, payload = p.journal.begin_collection(p.admit(), context=context())
    state = p.completed(payload).model_copy(update={field: value})
    with pytest.raises(ScopeDenied):
        p.journal.observe_collection(row, state, context=context())
    assert p.s.records.get(KB, 1, context=context()) == row


def test_pending_collection_does_not_advance_and_revocation_blocks_terminal(parent):
    p = parent
    row, payload = p.journal.begin_collection(p.admit(), context=context())
    state = p.completed(payload)
    pending = state.model_copy(update={'status': 'cleanup_pending', 'physical_cleanup_complete': False})
    assert p.journal.observe_collection(row, pending, context=context()) == row
    p.s.update('cleanse_memberships', delete_flag='Y')
    with pytest.raises(ScopeDenied):
        p.journal.observe_collection(row, state, context=context())
    assert p.s.records.get(KB, 1, context=context()) == row


def test_empty_kb_persists_submission_before_one_standard_rpc(parent):
    p = parent
    result = asyncio.run(p.coordinator.request('kb-one', p.s.actor))
    assert result['deletion_request']['phase'] == 'metadata_pending'
    assert result['delete_flag'] == 'N'
    p.client.delete_knowledge_base.assert_awaited_once()
    p.client.inspect_knowledge_base_deletion.assert_not_awaited()
    again = asyncio.run(p.coordinator.request('kb-one', p.s.actor))
    assert again == result
    p.client.delete_knowledge_base.assert_awaited_once()


def test_pending_file_prevents_collection_and_shares_parent_deadline(parent):
    p, s = parent, parent.s
    s.service.admit([s.spec(object_name=None, bucket_name=None)], context=context())
    s.records.patch(FILES, 'a' * 32, FieldPatch(set_values={'status': 'FAILED'}), expected=None, context=context())
    p.files.request.return_value = {'status': 'DELETE_REQUESTED', 'stage': 'DELETE_RUNTIME_PENDING'}
    outer = context()
    row = asyncio.run(p.coordinator.request('kb-one', s.actor, context=outer))
    assert row['deletion_request']['phase'] == 'files'
    args, kwargs = p.files.request.call_args
    assert args == ('kb-one', None, 'full', s.actor)
    assert kwargs['file_id'] == 'a' * 32 and kwargs['remove_tags'] is True
    assert kwargs['context'].deadline <= outer.deadline
    assert kwargs['context'].cancelled.is_set()
    p.client.delete_knowledge_base.assert_not_awaited()


def test_completed_files_are_revalidated_before_collection(parent):
    p, s = parent, parent.s
    s.service.admit([s.spec(object_name=None, bucket_name=None)], context=context())
    s.records.patch(FILES, 'a' * 32, FieldPatch(set_values={'status': 'FAILED'}), expected=None, context=context())

    def finish_sync(**kwargs):
        intent = KnowledgeDeletionIntent(knowledge_id=1, file_id='a' * 32, file_version=0,
                                         user_id='user-a', scope='full', index_name='kb-one',
                                         filename='a' * 32 + '.txt', object_name=None, source=None)
        s.records.patch(FILES, 'a' * 32, FieldPatch(set_values={
            'status': 'DELETED', 'stage': 'DELETE_DONE', 'deleted_vector_count': 0,
            'deletion_request': intent.model_dump(mode='json'),
        }), expected=None, context=kwargs['context'])
        return s.records.get(FILES, 'a' * 32, context=kwargs['context'])

    async def finish(index, path, scope, actor, **kwargs):
        return await asyncio.to_thread(finish_sync, **kwargs)

    p.files.request.side_effect = finish
    result = asyncio.run(p.coordinator.request('kb-one', s.actor))
    assert result['deletion_request']['phase'] == 'metadata_pending'
    p.client.delete_knowledge_base.assert_awaited_once()


def test_unknown_rpc_is_inspected_later_without_resubmission(parent):
    p = parent
    p.client.delete_knowledge_base.side_effect = RuntimeServiceTimeoutError('slow')
    row = asyncio.run(p.coordinator.request('kb-one', p.s.actor))
    assert row['deletion_request']['phase'] == 'collection_submitting'
    lookup = p.journal.lookup(row)
    p.client.inspect_knowledge_base_deletion.side_effect = RuntimeUpstreamError(404, b'missing', {})
    assert asyncio.run(p.coordinator.request('kb-one', p.s.actor))['deletion_request']['phase'] == 'collection_submitting'
    p.client.inspect_knowledge_base_deletion.side_effect = None
    p.client.inspect_knowledge_base_deletion.return_value = KnowledgeBaseDeleteState(
        **lookup.model_dump(), status='deleted', physical_cleanup_complete=True,
    )
    assert asyncio.run(p.coordinator.request('kb-one', p.s.actor))['deletion_request']['phase'] == 'metadata_pending'
    p.client.delete_knowledge_base.assert_awaited_once()
    assert p.client.inspect_knowledge_base_deletion.await_count == 2


def test_total_deadline_keeps_reserved_phase_and_closes_cancellation(parent):
    p = parent
    reserved, _ = p.journal.begin_collection(p.admit(), context=context())
    operation = context()
    operation = replace(operation, deadline=monotonic() + .2)

    async def stall(*args, **kwargs):
        await asyncio.sleep(1)

    p.client.inspect_knowledge_base_deletion.side_effect = stall
    row = asyncio.run(p.coordinator.request('kb-one', p.s.actor, context=operation))
    assert row == reserved
    p.client.delete_knowledge_base.assert_not_awaited()
    p.client.inspect_knowledge_base_deletion.assert_awaited_once()


def test_unexpected_rpc_error_propagates_with_reserved_state(parent):
    p = parent
    p.client.delete_knowledge_base.side_effect = ValueError('invalid reply')
    with pytest.raises(ValueError, match='invalid reply'):
        asyncio.run(p.coordinator.request('kb-one', p.s.actor))
    row = p.s.records.get(KB, 1, context=context())
    assert row['deletion_request']['phase'] == 'collection_submitting'


def test_stale_revision_never_changes_reserved_phase(parent):
    p = parent
    row = p.admit()
    p.s.records.patch(KB, 1, FieldPatch(set_values={}), expected=Revision(str(row['version'])), context=context())
    with pytest.raises(Conflict):
        p.journal.begin_collection(row, context=context())
    assert p.s.records.get(KB, 1, context=context())['deletion_request']['phase'] == 'files'


def test_different_current_editor_only_acknowledges_original_intent(parent):
    p = parent
    row = p.admit()
    original = {**row['deletion_request'], 'user_id': 'original-editor'}
    p.s.records.patch(KB, 1, FieldPatch(set_values={'deletion_request': original}), expected=None, context=context())
    result = asyncio.run(p.coordinator.request('kb-one', p.s.actor))
    assert result['deletion_request'] == original
    p.client.delete_knowledge_base.assert_not_awaited()
    p.client.inspect_knowledge_base_deletion.assert_not_awaited()
    p.files.request.assert_not_awaited()
    with pytest.raises(ScopeDenied):
        p.journal.begin_collection(result, context=context())


def test_lost_reservation_receipt_is_not_followed_by_delete(parent, monkeypatch):
    p = parent
    p.admit()
    patch = type(p.s.records).patch

    def lose(self, dataset, key, fields, **kwargs):
        result = patch(self, dataset, key, fields, **kwargs)
        if dataset == KB:
            return WriteReceipt(result.operation_id, matched=False, outcome=WriteOutcome.UNKNOWN)
        return result

    with monkeypatch.context() as local:
        local.setattr(type(p.s.records), 'patch', lose)
        result = asyncio.run(p.coordinator.request('kb-one', p.s.actor))
    assert result['deletion_request']['phase'] == 'files'
    # An unknown transaction is rolled back by this controlled fault; neither outcome allows replay here.
    p.client.delete_knowledge_base.assert_not_awaited()


def test_every_page_is_considered_before_collection_reservation(parent, monkeypatch):
    p = parent
    pages = []

    def page(row, actor, operation, cursor):
        pages.append(cursor)
        if cursor is None:
            return Page(({'file_id': 'b' * 32, 'status': 'DELETED', 'stage': 'DELETE_DONE'},), 'next')
        return Page(({'file_id': 'c' * 32, 'status': 'COMPLETED', 'stage': 'SOURCE_DELETED'},))

    monkeypatch.setattr(p.coordinator, '_page', page)
    p.files.request.return_value = {'status': 'DELETE_REQUESTED', 'stage': 'DELETE_ACCEPTED'}
    row = asyncio.run(p.coordinator.request('kb-one', p.s.actor))
    assert pages == [None, 'next']
    assert row['deletion_request']['phase'] == 'files'
    assert p.files.request.call_args.kwargs['file_id'] == 'c' * 32
    assert p.files.request.call_args.args[2] == 'full'
    p.client.delete_knowledge_base.assert_not_awaited()


def test_caller_cancellation_preserves_reserved_phase_and_cancels_rpc(parent):
    p = parent
    reserved, _ = p.journal.begin_collection(p.admit(), context=context())
    seen = []

    async def cancel_rpc(*args, **kwargs):
        seen.append(True)
        raise asyncio.CancelledError()

    p.client.inspect_knowledge_base_deletion.side_effect = cancel_rpc
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(p.coordinator.request('kb-one', p.s.actor))
    assert seen == [True]
    assert p.s.records.get(KB, 1, context=context()) == reserved
    p.client.delete_knowledge_base.assert_not_awaited()


def test_expired_context_prevents_late_terminal_commit(parent):
    p = parent
    reserved, payload = p.journal.begin_collection(p.admit(), context=context())
    expired = replace(context(), deadline=monotonic() - 1)
    from nexent.storage.errors import DeadlineExceeded

    with pytest.raises(DeadlineExceeded):
        p.journal.observe_collection(reserved, p.completed(payload), context=expired)
    assert p.s.records.get(KB, 1, context=context()) == reserved
