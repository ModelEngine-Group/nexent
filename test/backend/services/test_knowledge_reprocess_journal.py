# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""An explicit new attempt needs closed children and leaves the source unchanged."""

import pytest
from contracts.agentos_knowledge import KnowledgeJobState
from contracts.knowledge_cleanse import KnowledgeCleanseState, cleanse_job_id
from nexent.storage.errors import Conflict, ScopeDenied

from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_journal import (
    records,  # noqa: F401
    setup,  # noqa: F401
)


@pytest.fixture(params=('cleanse', 'runtime'))
def failed(setup, request):  # noqa: F811
    journal, intent, initial, _engine, _table = setup
    admitted = journal.admit(intent, initial, context=context())
    started = journal.begin_cleanse(admitted, context=context())
    cleanse = KnowledgeCleanseState(**intent._reference(), job_id=started['process_task_id'],
        status='failed', execution_ended=True, reconcile_required=False, artifact_ownership_known=True)
    runtime = None
    if request.param == 'runtime':
        cleanse = cleanse.model_copy(update={'status': 'completed', 'artifact': intent.source})
        forwarding, _ = journal.begin_runtime(started, cleanse, context=context())
        runtime = KnowledgeJobState(**intent._reference(), job_id=forwarding['forward_task_id'],
            status='failed', writer_ended=True, reconcile_required=False)
        row = journal.observe_runtime(forwarding, runtime, context=context())
    else:
        row = journal.observe_cleanse(started, cleanse, context=context())
    return journal, intent, row, cleanse, runtime


def restart(failed, **changes):
    journal, intent, row, cleanse, runtime = failed
    next_intent = intent.model_copy(update={'attempt': 2, **changes})
    return journal.reprocess(row, next_intent, cleanse, runtime, context=context())


def test_new_attempt_preserves_source_and_has_distinct_child_identity(failed):
    journal, intent, row, _, _ = failed
    updated = restart(failed, chunking_strategy='by_title')
    assert updated['processing_attempt'] == 2 and updated['source_generation'] == row['source_generation']
    assert updated['process_task_id'] != row['process_task_id']
    assert updated['process_task_id'] == cleanse_job_id(journal.request(updated).cleanse_request(), 'tenant-a', 'user-a')
    assert updated['stage'] == 'INGEST_ACCEPTED' and updated['status'] == 'UPLOADED'
    assert updated['forward_task_id'] is None
    assert all(updated[name] is None for name in ('error_code', 'failed_at', 'completed_at', 'cleanse_status',
                                                  'runtime_status', 'processed_chunks', 'total_chunks'))
    assert journal.request(updated).source == intent.source
    with pytest.raises(Conflict):
        restart(failed)


@pytest.mark.parametrize('change', [{'execution_ended': False}, {'execution_ended': None},
                                    {'reconcile_required': True}, {'reconcile_required': None}, {'status': 'running'},
                                    {'artifact_ownership_known': False}, {'artifact_ownership_known': None}])
def test_unsettled_cleanse_cannot_be_restarted(failed, change):
    journal, intent, row, cleanse, runtime = failed
    with pytest.raises(Conflict):
        journal.reprocess(row, intent.model_copy(update={'attempt': 2}), cleanse.model_copy(update=change),
                          runtime, context=context())


@pytest.mark.parametrize('change', [{'attempt': 1}, {'attempt': 3}, {'file_version': 1}, {'user_id': 'other'}])
def test_wrong_attempt_source_or_actor_cannot_replace_intent(failed, change):
    with pytest.raises((Conflict, ScopeDenied)):
        restart(failed, **change)


def test_old_child_result_cannot_advance_new_attempt(failed):
    journal, _, _, old_cleanse, _ = failed
    updated = restart(failed)
    started = journal.begin_cleanse(updated, context=context())
    with pytest.raises(ScopeDenied):
        journal.observe_cleanse(started, old_cleanse, context=context())


@pytest.mark.parametrize('change', [{'writer_ended': False}, {'writer_ended': None}, {'reconcile_required': True},
                                    {'reconcile_required': None}, {'status': 'running'}, {'status': 'completed'}])
def test_unsettled_or_wrong_runtime_terminal_cannot_be_restarted(failed, change):
    journal, intent, row, cleanse, runtime = failed
    runtime = runtime or KnowledgeJobState(**intent._reference(), job_id='c' * 32, status='failed')
    with pytest.raises((Conflict, ScopeDenied)):
        journal.reprocess(row, intent.model_copy(update={'attempt': 2}), cleanse, runtime.model_copy(update=change),
                          context=context())
