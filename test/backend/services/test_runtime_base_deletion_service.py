# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB-COLLECTION-03: real journal/managed workers never replay an uncertain drop."""

import asyncio
from contextlib import contextmanager
from dataclasses import replace
from threading import Event
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.knowledge_base_deletion import KnowledgeBaseDeleteLookup
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, OutcomeUnknown
from nexent.storage.models import DeleteReceipt
from runtime.knowledge_base.base_deletion_service import KnowledgeBaseDeletionService

from infrastructure.rdb.knowledge_base_deletions import bind_base_deletion_records
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_coordinator import (
    sqlite_threads,  # noqa: F401
)
from test.backend.services.test_runtime_knowledge_base_deletion import (
    journal,  # noqa: F401
)


@pytest.fixture
async def setup(sqlite_threads, journal):  # noqa: F811
    s = journal
    manager = ThreadManager(service_name='collection-ut', lane_policies={
        'control-io': LanePolicy(name='control-io', max_workers=1, max_queue_size=8,
                                queue_timeout_seconds=1, cancel_grace_seconds=1, shutdown_grace_seconds=2),
    })
    manager.start()
    set_default_thread_manager(manager)
    client = SimpleNamespace(authorize_knowledge_base_deletion=AsyncMock(return_value=s.grant))
    vectors = Mock()
    vectors.delete_empty_collection.return_value = DeleteReceipt('drop', True)
    vectors.collection_exists.return_value = False
    counts = {'open': 0, 'close': 0}
    contexts = []

    @contextmanager
    def ports(actor, grant, *, context):
        assert actor == s.actor and grant == s.grant
        context.remaining()
        contexts.append(context)
        records = bind_base_deletion_records(s.records.scope, s.engine)
        counts['open'] += 1
        try:
            yield records, vectors
        finally:
            records.close()
            counts['close'] += 1

    service = KnowledgeBaseDeletionService(client, ports=ports)
    try:
        yield SimpleNamespace(**locals())
    finally:
        clear_default_thread_manager(manager)
        assert not (await manager.shutdown(timeout=2)).stuck_execution_ids
        assert counts['open'] == counts['close']


async def test_success_is_durable_and_repeated_delete_does_not_touch_vectors(setup):
    s = setup
    state = await s.service.delete(s.s.request, s.s.actor)
    assert state.status == 'deleted' and state.physical_cleanup_complete
    assert await s.service.delete(s.s.request, s.s.actor) == state
    lookup = KnowledgeBaseDeleteLookup(knowledge_id=1, job_id=state.job_id)
    assert await s.service.inspect(lookup, s.s.actor) == state
    s.vectors.delete_empty_collection.assert_called_once()
    s.vectors.collection_exists.assert_not_called()


async def test_uncertain_drop_only_observes_and_never_replays(setup):
    s = setup
    s.vectors.delete_empty_collection.side_effect = OutcomeUnknown()
    with pytest.raises(OutcomeUnknown):
        await s.service.delete(s.s.request, s.s.actor)
    s.vectors.collection_exists.return_value = True
    pending = await s.service.delete(s.s.request, s.s.actor)
    assert pending.status == 'cleanup_pending' and not pending.physical_cleanup_complete
    s.vectors.collection_exists.return_value = False
    state = await s.service.inspect(KnowledgeBaseDeleteLookup(knowledge_id=1, job_id=pending.job_id), s.s.actor)
    assert state.status == 'deleted'
    assert s.vectors.delete_empty_collection.call_count == 1
    assert s.vectors.collection_exists.call_count == 2


async def test_changed_grant_cannot_commit_terminal(setup):
    s = setup
    s.client.authorize_knowledge_base_deletion.side_effect = [s.s.grant, s.s.grant.model_copy(update={'collection': 'other'})]
    with pytest.raises(Conflict):
        await s.service.delete(s.s.request, s.s.actor)
    assert s.vectors.delete_empty_collection.call_count == 1


async def test_parent_deadline_cancels_http_before_any_storage_work(setup, caplog):
    s = setup
    ended = []

    async def hanging(*args):
        try:
            await asyncio.Event().wait()
        finally:
            ended.append(True)

    s.client.authorize_knowledge_base_deletion.side_effect = hanging
    with pytest.raises(DeadlineExceeded):
        await s.service.delete(s.s.request, s.s.actor, context=replace(context(), deadline=monotonic() + .05))
    assert ended == [True] and s.counts['open'] == 0
    assert len(caplog.records) == 1 and caplog.records[0].levelname == 'WARNING'
    s.vectors.delete_empty_collection.assert_not_called()


async def test_late_physical_return_cannot_commit_after_timeout(setup):
    s = setup
    started, released = Event(), Event()

    def slow(*args, **kwargs):
        started.set()
        assert released.wait(2)
        kwargs['context'].remaining()
        return DeleteReceipt('drop', True)

    s.vectors.delete_empty_collection.side_effect = slow
    try:
        with pytest.raises(DeadlineExceeded):
            await s.service.delete(s.s.request, s.s.actor, context=replace(context(), deadline=monotonic() + .1))
        assert started.is_set()
    finally:
        released.set()
    s.vectors.collection_exists.return_value = True
    pending = await s.service.delete(s.s.request, s.s.actor)
    assert pending.status == 'cleanup_pending' and not pending.physical_cleanup_complete
    assert s.vectors.delete_empty_collection.call_count == 1
