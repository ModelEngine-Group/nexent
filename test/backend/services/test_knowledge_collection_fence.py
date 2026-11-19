# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-COLLECTION-FENCE-01/02/03 share real lifecycle locks, not fake files."""

import pytest
from contracts.knowledge_base_deletion import KnowledgeBaseDelete
from contracts.knowledge_collections import CollectionSetup
from nexent.storage.errors import Conflict, ScopeDenied
from runtime.knowledge_base.collection_journal import KnowledgeCollectionJournal

from test.backend.services.test_knowledge_chunk_fencing import context, lookup
from test.backend.services.test_knowledge_chunk_fencing import (
    lifecycle as lifecycle,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_journal import intent


@pytest.fixture
def collection(lifecycle):
    s = lifecycle
    journal = KnowledgeCollectionJournal(s.mutation_records, 1)
    setup = CollectionSetup(operation_id='ensure-one', actor_id=s.actor.user_id, resource_revision='a' * 64,
                             dimensions=3, model_binding={'model_id': 2, 'revision': 'r1'},
                             phase='reserved', writer_ended=False)
    return s, journal, setup


def test_confirmation_clears_setup_and_advances_epoch_without_chunk_receipts(collection):
    s, journal, setup = collection
    journal.reserve(setup, context=context())
    assert journal.inspect(context=context()) == setup
    journal.begin(setup.operation_id, context=context())
    journal.finish(setup.operation_id, confirmed=True, context=context())
    assert journal.inspect(context=context()) is None
    assert s.mutation.revision(context=context()) == 1
    assert s.mutation.standalone_count(context=context()) == 0


def test_no_provider_attempt_releases_without_epoch_or_fake_chunk(collection):
    s, journal, setup = collection
    journal.reserve(setup, context=context())
    journal.finish(setup.operation_id, confirmed=False, context=context())
    assert journal.inspect(context=context()) is None and s.mutation.revision(context=context()) == 0


def test_active_collection_setup_fences_file_chunk_read_and_base_delete(collection):
    s, journal, setup = collection
    journal.reserve(setup, context=context())
    with pytest.raises(Conflict):
        s.policy.submit(s.request, context=context())
    with pytest.raises(Conflict):
        s.mutation.reserve(intent(file=False), context=context())
    with pytest.raises(Conflict):
        s.mutation.revision(context=context())
    with pytest.raises(Conflict):
        s.base.reserve(KnowledgeBaseDelete(knowledge_id=1, idempotency_key='delete'), context=context())
    with pytest.raises(Conflict):
        journal.reserve(setup, context=context())


def test_unknown_result_keeps_persistent_fence_and_cannot_be_released(collection):
    s, journal, setup = collection
    journal.reserve(setup, context=context())
    journal.begin(setup.operation_id, context=context())
    journal.unknown(setup.operation_id, writer_ended=True, context=context())
    current = journal.inspect(context=context())
    assert current.phase == 'unknown' and current.writer_ended
    for action in (lambda: journal.finish(setup.operation_id, confirmed=True, context=context()),
                   lambda: journal.finish(setup.operation_id, confirmed=False, context=context()),
                   lambda: s.mutation.assert_drained(context=context())):
        with pytest.raises(Conflict):
            action()
    assert journal.inspect(context=context()) == current


@pytest.mark.parametrize('state', ['file_writer', 'chunk_writer', 'deleted_base'])
def test_existing_writers_or_deletion_prevent_collection_admission(collection, state):
    from contracts.knowledge_base_deletion import KnowledgeBaseDelete

    s, journal, setup = collection
    if state == 'file_writer':
        admitted = s.policy.submit(s.request, context=context())
        handle = s.policy.claim(lookup(admitted), owner_id='file-owner', lease_seconds=30, context=context())
        assert s.policy.begin_execution(handle, context=context())
    elif state == 'chunk_writer':
        s.mutation.reserve(intent(file=False), context=context())
    else:
        s.base.reserve(KnowledgeBaseDelete(knowledge_id=1, idempotency_key='delete'), context=context())
    with pytest.raises(Conflict):
        journal.reserve(setup, context=context())
    assert journal.inspect(context=context()) is None


def test_wrong_operation_or_actor_cannot_mutate_reserved_snapshot(collection):
    _, journal, setup = collection
    with pytest.raises(ScopeDenied):
        journal.reserve(setup.model_copy(update={'actor_id': 'other'}), context=context())
    journal.reserve(setup, context=context())
    with pytest.raises(Conflict):
        journal.begin('other-operation', context=context())
    assert journal.inspect(context=context()) == setup


def test_corrupt_snapshot_blocks_inspection_read_and_deletion(collection):
    from contracts.knowledge_chunk_mutation import STATES

    s, journal, _ = collection
    with s.mutation_records.transaction(context=context()) as tx:
        row = s.mutation._locked_state(tx, context())
        s.mutation._patch(tx, STATES, row, {'collection_setup': {'phase': 'broken'}}, context())
    for action in (lambda: journal.inspect(context=context()),
                   lambda: s.mutation.revision(context=context()),
                   lambda: s.base.reserve(KnowledgeBaseDelete(knowledge_id=1, idempotency_key='blocked'), context=context())):
        with pytest.raises(Conflict):
            action()


def test_another_editor_cannot_take_over_owner_transition_or_audit(collection):
    from contracts.knowledge_chunk_mutation import CHANGES, STATES
    from nexent.storage.models import StorageScope

    from infrastructure.rdb.knowledge_lifecycle import bind_knowledge_lifecycle

    s, journal, setup = collection
    journal.reserve(setup, context=context())
    records = bind_knowledge_lifecycle(StorageScope('runtime', s.actor.tenant_id, 'other-editor', {CHANGES, STATES}),
                                      s.engine, mode='mutation')
    try:
        other = KnowledgeCollectionJournal(records, 1)
        with pytest.raises(ScopeDenied):
            other.begin(setup.operation_id, context=context())
    finally:
        records.close()
    row = s.mutation._state(s.mutation_records, context())
    assert row['created_by'] == row['updated_by'] == s.actor.user_id
    assert journal.inspect(context=context()) == setup


def test_reserved_setup_cannot_be_falsely_confirmed(collection):
    _, journal, setup = collection
    journal.reserve(setup, context=context())
    with pytest.raises(Conflict):
        journal.finish(setup.operation_id, confirmed=True, context=context())
    assert journal.inspect(context=context()) == setup
