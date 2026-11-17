# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Existing process acceptance creates new work only after live child inspection."""

import pytest
from contracts.errors.exceptions import RuntimeUpstreamError
from nexent.storage.errors import Conflict, ScopeDenied

from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_coordinator import (
    records,  # noqa: F401
    resources,  # noqa: F401
    setup,  # noqa: F401
    sqlite_threads,  # noqa: F401
)


@pytest.fixture(params=('cleanse', 'runtime'))
async def failed(setup, request):  # noqa: F811
    s = setup
    await s.coordinator.admit(s.value, s.actor, context=context())
    runtime_failure = request.param == 'runtime'
    s.cleanse.submit.side_effect = lambda *args, **kwargs: s.child(
        'completed' if runtime_failure else 'failed',
        **({'artifact': s.value.source} if runtime_failure else {}),
        execution_ended=True, reconcile_required=False, artifact_ownership_known=True)
    s.client.upload_knowledge_file.side_effect = lambda *args, **kwargs: s.runtime('failed').model_copy(
        update={'writer_ended': True, 'reconcile_required': False})
    row = await s.coordinator.advance(s.value.file_id, s.actor, context=context())
    assert row['status'] == 'FAILED'
    cleanse = s.child('completed' if runtime_failure else 'failed',
        **({'artifact': s.value.source} if runtime_failure else {}), execution_ended=True, reconcile_required=False,
        artifact_ownership_known=True)
    s.cleanse.inspect.return_value = cleanse
    if runtime_failure:
        s.client.inspect_knowledge_file.return_value = s.runtime('failed').model_copy(
            update={'writer_ended': True, 'reconcile_required': False})
    s.client.get_model.reset_mock()
    return s, row, runtime_failure


async def test_explicit_accept_inspects_old_children_then_admits_new_snapshot(failed):
    s, old, runtime_failure = failed
    updated = await s.coordinator.accept(s.value.file_id, s.actor, chunking_strategy='by_title', context=context())
    assert updated['processing_attempt'] == 2 and updated['process_task_id'] != old['process_task_id']
    assert updated['source_generation'] == old['source_generation']
    assert updated['stage'] == 'INGEST_ACCEPTED' and updated['status'] == 'UPLOADED'
    s.cleanse.inspect.assert_called_once()
    assert s.client.inspect_knowledge_file.await_count == int(runtime_failure)
    s.client.get_model.assert_awaited_once()
    assert s.cleanse.submit.call_count == 1
    assert s.client.upload_knowledge_file.await_count == int(runtime_failure)
    same = await s.coordinator.accept(s.value.file_id, s.actor, chunking_strategy='by_title', context=context())
    assert same['process_task_id'] == updated['process_task_id'] and same['processing_attempt'] == 2
    s.cleanse.inspect.assert_called_once()


async def test_unconfirmed_child_keeps_failed_intent_without_submitting_new_work(failed):
    s, old, _ = failed
    s.cleanse.inspect.return_value = s.cleanse.inspect.return_value.model_copy(update={'execution_ended': False})
    with pytest.raises(Conflict):
        await s.coordinator.accept(s.value.file_id, s.actor, context=context())
    assert s.row()['ingestion_request'] == old['ingestion_request']
    assert s.row()['processing_attempt'] == 1


async def test_unknown_runtime_inspection_is_not_replaced_by_an_upload(failed):
    s, old, runtime_failure = failed
    if runtime_failure:
        s.client.inspect_knowledge_file.side_effect = RuntimeUpstreamError(404, b'not found', {})
        expected = RuntimeUpstreamError
    else:
        s.cleanse.inspect.side_effect = Conflict()
        expected = Conflict
    with pytest.raises(expected):
        await s.coordinator.accept(s.value.file_id, s.actor, context=context())
    assert s.row()['ingestion_request'] == old['ingestion_request']
    assert s.cleanse.submit.call_count == 1


async def test_actor_revoked_between_inspection_and_admission_cannot_start_new_attempt(failed):
    s, old, _ = failed
    metadata = s.client.get_model.return_value

    async def revoke(*args, **kwargs):
        s.update('cleanse_memberships', delete_flag='Y')
        return metadata

    s.client.get_model.side_effect = revoke
    with pytest.raises(ScopeDenied):
        await s.coordinator.accept(s.value.file_id, s.actor, context=context())
    assert s.row()['ingestion_request'] == old['ingestion_request']


async def test_concurrent_revision_change_is_rejected_without_cas_retry(failed):
    s, old, _ = failed
    metadata = s.client.get_model.return_value

    async def change(*args, **kwargs):
        with s.engine.begin() as connection:
            connection.execute(s.table.update().values(version=old['version'] + 1))
        return metadata

    s.client.get_model.side_effect = change
    with pytest.raises(Conflict):
        await s.coordinator.accept(s.value.file_id, s.actor, context=context())
    assert s.row()['processing_attempt'] == 1 and s.cleanse.submit.call_count == 1
    s.client.get_model.assert_awaited_once()
