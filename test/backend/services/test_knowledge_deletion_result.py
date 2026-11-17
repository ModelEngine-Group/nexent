# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DELETE-RESULT-02: confirmed deletion counts never overwrite upload progress."""

import pytest
from contracts.agentos_knowledge import KnowledgeJobState
from nexent.storage.errors import InvalidInput

from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_deletion_journal import (
    setup as setup,  # noqa: PLC0414
)


def runtime(s, *, processed=7, total=7):
    return KnowledgeJobState(**s.intent.runtime_lookup('tenant-a').model_dump(), status='deleted',
                             physical_cleanup_complete=True, processed_chunks=processed, total_chunks=total)


def test_runtime_result_count_is_persisted_without_changing_original_progress(setup):
    s = setup
    with s.engine.begin() as connection:
        connection.execute(s.table.update().values(processed_chunks=4, total_chunks=5))
    admitted = s.journal.admit(s.intent, s.row(), context=context())
    assert admitted['deleted_vector_count'] is None
    row, _ = s.journal.begin_runtime(admitted, context=context())
    observed = s.journal.observe_runtime(row, runtime(s), context=context())
    assert observed['stage'] == 'DELETE_CLEANSE_PENDING' and observed['deleted_vector_count'] == 7
    assert (observed['processed_chunks'], observed['total_chunks']) == (4, 5)


@pytest.mark.parametrize('processed,total', [(None, None), (0, None), (None, 0), (2, 3)])
def test_missing_or_inconsistent_final_count_cannot_begin_source_cleanup(setup, processed, total):
    s = setup
    row = s.journal.admit(s.intent, s.row(), context=context())
    row, _ = s.journal.begin_runtime(row, context=context())
    with pytest.raises(InvalidInput):
        s.journal.observe_runtime(row, runtime(s, processed=processed, total=total), context=context())
    assert s.row()['stage'] == 'DELETE_RUNTIME_SUBMITTING'
    assert s.row()['deleted_vector_count'] is None


def test_only_source_does_not_create_a_vector_deletion_count(setup):
    s = setup
    value = s.intent.model_copy(update={'scope': 'source_only'})
    row = s.journal.admit(value, s.row(), context=context())
    assert row['deleted_vector_count'] is None
