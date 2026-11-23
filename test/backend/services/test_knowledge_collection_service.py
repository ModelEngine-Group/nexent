# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Collection ensure uses real SI fencing with isolated vector/model boundaries."""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.agentos import ModelMetadata
from contracts.knowledge_collections import (
    KnowledgeCollectionEnsure,
    KnowledgeCollectionGrant,
    KnowledgeCollectionLookup,
    KnowledgeUntrackedSourceDelete,
)
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import VectorCollectionInfo
from runtime.knowledge_base.collection_journal import KnowledgeCollectionJournal
from runtime.knowledge_base.collection_service import KnowledgeCollectionService

from test.backend.services.test_knowledge_chunk_creation import context
from test.backend.services.test_knowledge_chunk_creation import (
    creation as creation,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_creation import (
    lifecycle as lifecycle,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_creation import (
    sqlite_threads as sqlite_threads,  # noqa: PLC0414
)


@pytest.fixture
def setup(creation):
    s = creation
    opened = []

    @contextmanager
    def records(actor, *, context, **namespace):
        assert actor == s.s.actor and not namespace
        opened.append(True)
        yield s.s.mutation_records

    grant = KnowledgeCollectionGrant(knowledge_id=1, collection='collection', resource_tenant_id=s.s.actor.tenant_id,
                                     revision='a' * 64, embedding_model_id=2)
    client = SimpleNamespace(authorize_knowledge_collection=AsyncMock(return_value=grant))
    s.models.get = AsyncMock(return_value=ModelMetadata(model_id=2, model_type='embedding', display_name=None, revision='r1'))
    s.vectors.ensure_collection.return_value = VectorCollectionInfo('collection', 3, 'cosine')
    service = KnowledgeCollectionService(client, s.models, records=records, ports=s.ports)
    request = KnowledgeCollectionEnsure(knowledge_id=1, expected_revision='a' * 64, dimensions=3,
                                        model_binding={'model_id': 2, 'revision': 'r1'})
    journal = KnowledgeCollectionJournal(s.s.mutation_records, 1)
    return SimpleNamespace(**locals())


async def test_empty_collection_is_confirmed_without_model_inference_or_fake_chunk(setup):
    a = setup
    result = await a.service.ensure(a.request, a.s.s.actor, context=context())
    assert result.present and result.dimensions == 3 and result.expected_revision == a.request.expected_revision
    assert await a.s.db(a.journal.inspect, context=context()) is None
    assert await a.s.db(a.s.s.mutation.revision, context=context()) == 1
    assert await a.s.db(a.s.s.mutation.standalone_count, context=context()) == 0
    assert a.s.vectors.ensure_collection.call_count == 1 and a.s.models.invoke.await_count == 0


async def test_unknown_provider_result_blocks_automatic_replay_and_remains_inspectable(setup):
    a = setup
    a.s.vectors.ensure_collection.side_effect = OutcomeUnknown()
    with pytest.raises(OutcomeUnknown):
        await a.service.ensure(a.request, a.s.s.actor, context=context())
    state = await a.s.db(a.journal.inspect, context=context())
    assert state.phase == 'unknown' and state.writer_ended
    with pytest.raises(Conflict):
        await a.service.ensure(a.request, a.s.s.actor, context=context())
    assert a.s.vectors.ensure_collection.call_count == 1
    result = await a.service.inspect(KnowledgeCollectionLookup(knowledge_id=1, expected_revision='a' * 64),
                                     a.s.s.actor, context=context())
    assert result.setup == state


@pytest.mark.parametrize('failure', [InvalidInput, ScopeDenied, Conflict, Unavailable])
async def test_definitive_provider_rejection_releases_without_fake_unknown_or_retry(setup, failure):
    a = setup
    a.s.vectors.ensure_collection.side_effect = failure()
    with pytest.raises(failure):
        await a.service.ensure(a.request, a.s.s.actor, context=context())
    assert await a.s.db(a.journal.inspect, context=context()) is None
    assert await a.s.db(a.s.s.mutation.revision, context=context()) == 0
    assert a.s.vectors.ensure_collection.call_count == 1


async def test_model_version_change_rejected_before_admission_and_vector_io(setup):
    a = setup
    a.s.models.get.return_value = a.s.models.get.return_value.model_copy(update={'revision': 'r2'})
    with pytest.raises(Conflict):
        await a.service.ensure(a.request, a.s.s.actor, context=context())
    assert not a.opened
    a.s.vectors.ensure_collection.assert_not_called()


async def test_confirm_commit_ack_loss_is_reported_unknown_without_replaying_provider(setup, mocker):
    a = setup
    original = KnowledgeCollectionJournal.finish

    def commit_then_lose_ack(journal, *args, **kwargs):
        original(journal, *args, **kwargs)
        raise OutcomeUnknown()

    mocker.patch.object(KnowledgeCollectionJournal, 'finish', side_effect=commit_then_lose_ack, autospec=True)
    with pytest.raises(OutcomeUnknown):
        await a.service.ensure(a.request, a.s.s.actor, context=context())
    assert a.s.vectors.ensure_collection.call_count == 1
    assert await a.s.db(a.journal.inspect, context=context()) is None


async def test_authorization_timeout_is_bounded_without_admission_or_retry(setup):
    from time import monotonic

    from nexent.storage.models import OperationContext

    a = setup
    ended = asyncio.Event()

    async def waiting(*args):
        try:
            await asyncio.Event().wait()
        finally:
            ended.set()

    a.client.authorize_knowledge_collection.side_effect = waiting
    with pytest.raises(DeadlineExceeded):
        await a.service.ensure(a.request, a.s.s.actor, context=OperationContext('ensure-timeout', monotonic() + .05))
    assert ended.is_set() and a.client.authorize_knowledge_collection.await_count == 1 and not a.opened


async def test_timeout_during_provider_keeps_fence_until_explicit_reconciliation(setup):
    from threading import Event
    from time import monotonic

    from nexent.storage.models import OperationContext

    a = setup
    entered, release = Event(), Event()

    def stalled(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return VectorCollectionInfo('collection', 3, 'cosine')

    a.s.vectors.ensure_collection.side_effect = stalled
    task = asyncio.create_task(a.service.ensure(a.request, a.s.s.actor,
        context=OperationContext('owned-provider-timeout', monotonic() + .5)))
    try:
        async with asyncio.timeout(.4):
            while not entered.is_set():
                await asyncio.sleep(.01)
        with pytest.raises(DeadlineExceeded):
            await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    marker = await a.s.db(a.journal.inspect, context=context())
    assert marker.phase == 'writing' and not marker.writer_ended
    assert a.s.vectors.ensure_collection.call_count == 1
    with pytest.raises(Conflict):
        await a.s.db(a.s.s.mutation.revision, context=context())


@pytest.mark.parametrize('uncertain', [False, True])
async def test_untracked_source_delete_reserves_collection_without_model_invocation(setup, mocker, uncertain):
    a = setup
    path = 'files/untracked.txt'
    a.client.authorize_knowledge_collection.return_value = a.grant.model_copy(update={'untracked_source': path})
    request = KnowledgeUntrackedSourceDelete(knowledge_id=1, expected_revision='a' * 64, untracked_source=path)
    a.service.source_delete = mocker.Mock(return_value=3, side_effect=OutcomeUnknown() if uncertain else None)
    if uncertain:
        with pytest.raises(OutcomeUnknown):
            await a.service.delete_untracked_source(request, a.s.s.actor, context=context())
        state = await a.s.db(a.journal.inspect, context=context())
        assert state.operation == 'delete_source' and state.phase == 'unknown'
        with pytest.raises(Conflict):
            await a.service.delete_untracked_source(request, a.s.s.actor, context=context())
    else:
        deleted = await a.service.delete_untracked_source(request, a.s.s.actor, context=context())
        assert deleted.deleted_count == 3 and deleted.untracked_source == path
        assert await a.s.db(a.journal.inspect, context=context()) is None
        assert await a.s.db(a.s.s.mutation.revision, context=context()) == 1
    assert a.service.source_delete.call_count == 1
    assert a.client.authorize_knowledge_collection.call_args.args[0].untracked_source == path
    a.s.models.get.assert_not_awaited()
    a.s.vectors.ensure_collection.assert_not_called()
