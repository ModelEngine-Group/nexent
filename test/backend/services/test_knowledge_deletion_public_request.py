# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""DELETE-PUBLIC-02: admission, bounded HTTP lifetime and no resubmission."""

import asyncio
from dataclasses import replace
from time import monotonic

import pytest
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from nexent.storage.errors import DeadlineExceeded, ScopeDenied

from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_deletion_coordinator import (
    setup,  # noqa: F401
)
from test.backend.services.test_knowledge_deletion_journal import (
    setup as journal_setup,  # noqa: F401
)
from test.backend.services.test_knowledge_ingestion_contract import intent
from test.backend.services.test_knowledge_ingestion_coordinator import (
    sqlite_threads,  # noqa: F401
)


@pytest.fixture
def ready(setup):  # noqa: F811
    s = setup
    with s.s.engine.begin() as connection:
        connection.execute(s.s.table.update().values(
            bucket_name='bucket', source_revision='etag:v1', source_upload_sha256='a' * 64,
            upload_owner_service='management', ingestion_request=intent(source={
                'space': 'files', 'key': 'source.txt', 'version': 'etag:v1', 'sha256': 'a' * 64,
            }).model_dump(mode='json'),
        ))
    return s


async def test_admitted_request_uses_persisted_actor_and_submits_only_once(ready):
    s = ready
    s.client.delete_knowledge_file.return_value = s.child()
    row = await s.coordinator.request('kb-one', 'source.txt', 'full', s.actor)
    assert row['stage'] == 'DELETE_RUNTIME_PENDING'
    s.client.inspect_knowledge_file.return_value = s.child()
    await s.coordinator.request('kb-one', 'source.txt', 'full', s.actor)
    assert s.client.delete_knowledge_file.await_count == s.client.inspect_knowledge_file.await_count == 1


async def test_uncertain_submit_returns_admitted_pending_and_next_request_only_inspects(ready):
    s = ready
    s.client.delete_knowledge_file.side_effect = RuntimeServiceTimeoutError('unknown')
    row = await s.coordinator.request('kb-one', None, 'full', s.actor, file_id=s.s.intent.file_id)
    assert row['deletion_request'] and row['stage'] == 'DELETE_ACCEPTED'
    assert s.row()['stage'] == 'DELETE_RUNTIME_SUBMITTING'
    s.client.inspect_knowledge_file.return_value = s.child()
    await s.coordinator.request('kb-one', None, 'full', s.actor, file_id=s.s.intent.file_id)
    assert s.client.delete_knowledge_file.await_count == 1
    assert s.client.inspect_knowledge_file.await_count == 1


async def test_deadline_before_admission_propagates_without_writes_or_runtime(ready):
    s = ready
    with pytest.raises(DeadlineExceeded):
        await s.coordinator.request('kb-one', 'source.txt', 'full', s.actor,
                                    context=replace(context(), deadline=monotonic() - 1))
    assert s.row()['deletion_request'] is None
    s.client.delete_knowledge_file.assert_not_called()


async def test_one_total_budget_cancels_blocked_http_after_admission(ready):
    s = ready
    closed = asyncio.Event()

    async def hang(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    s.client.delete_knowledge_file.side_effect = hang
    started = monotonic()
    row = await s.coordinator.request('kb-one', 'source.txt', 'full', s.actor,
                                      context=replace(context(), deadline=started + .1))
    assert monotonic() - started < 1 and closed.is_set()
    assert row['stage'] == 'DELETE_ACCEPTED'
    assert s.row()['stage'] == 'DELETE_RUNTIME_SUBMITTING'
    s.source.assert_not_called()


async def test_current_permission_denial_is_never_returned_as_pending(ready):
    s = ready
    s.update('cleanse_memberships', delete_flag='Y')
    with pytest.raises(ScopeDenied):
        await s.coordinator.request('kb-one', 'source.txt', 'full', s.actor)
    assert s.row()['deletion_request'] is None
    s.client.delete_knowledge_file.assert_not_called()


async def test_ordinary_full_uses_canonical_record_key_for_tag_cleanup(ready, monkeypatch):
    from unittest.mock import Mock

    from management.services.tag.library import TagManagementService

    s = ready
    cleanup = Mock()
    monkeypatch.setattr(TagManagementService, 'cleanup_document_assignments', cleanup)
    s.client.delete_knowledge_file.return_value = s.child()
    await s.coordinator.request('kb-one', 'wrong-alias', 'full', s.actor,
                                file_id=s.s.intent.file_id, remove_tags=True)
    cleanup.assert_called_once_with('tenant-a', 'local', 'kb-one', 'source.txt', 'user-a')


async def test_northbound_and_source_only_do_not_remove_tags(ready, monkeypatch):
    from unittest.mock import Mock

    from management.services.tag.library import TagManagementService

    s = ready
    cleanup = Mock(side_effect=AssertionError('Unexpected tag mutation'))
    monkeypatch.setattr(TagManagementService, 'cleanup_document_assignments', cleanup)
    s.source.return_value = {'status': 'COMPLETED', 'stage': 'SOURCE_DELETED'}
    await s.coordinator.request('kb-one', 'source.txt', 'source_only', s.actor, remove_tags=True)
    cleanup.assert_not_called()


async def test_other_editor_acknowledges_pending_without_borrowing_runtime_identity(ready, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from management.services.tag.library import TagManagementService

    s = ready
    s.client.delete_knowledge_file.return_value = s.child()
    await s.coordinator.request('kb-one', 'source.txt', 'full', s.actor)
    for dataset in ('cleanse_memberships', 'cleanse_accounts', 'cleanse_group_memberships'):
        s.update(dataset, user_id='editor-b')
    cleanup = Mock()
    monkeypatch.setattr(TagManagementService, 'cleanup_document_assignments', cleanup)
    row = await s.coordinator.request('kb-one', 'source.txt', 'full',
                                      SimpleNamespace(user_id='editor-b', tenant_id='tenant-a'), remove_tags=True)
    assert row['deletion_request']['user_id'] == 'user-a'
    s.client.delete_knowledge_file.assert_awaited_once()
    s.client.inspect_knowledge_file.assert_not_called()
    cleanup.assert_called_once_with('tenant-a', 'local', 'kb-one', 'source.txt', 'editor-b')
