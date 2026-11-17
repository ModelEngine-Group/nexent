# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Manual summaries read authorized AgentOS samples and preserve Management orchestration."""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest
from contracts.agentos_knowledge import KnowledgeSampleResult
from management.services.knowledge_base.summary_service import KnowledgeSummaryService
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, NotFound, ScopeDenied
from nexent.storage.models import PageRequest, RecordQuery, StorageScope

from infrastructure.knowledge_search import knowledge_search_revision
from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_coordinator import (
    sqlite_threads,  # noqa: F401
)


@pytest.fixture
def setup(resources, sqlite_threads):  # noqa: F811
    authorize, update, engine, _tables = resources
    update('cleanse_knowledge', embedding_model_id=2)
    actor = SimpleNamespace(user_id='user-a', tenant_id='tenant-a')
    closed = []
    @contextmanager
    def ports(tenant_id, user_id, *, context):
        records = bind_cleanse_resources(StorageScope('management', tenant_id, user_id, set(TABLES)), engine)
        try:
            yield records
        finally:
            records.close()
            closed.append(True)
    records = authorize().records
    try:
        row = records.query('cleanse_knowledge', RecordQuery(), PageRequest(), context=context()).items[0]
    finally:
        records.close()
    result = KnowledgeSampleResult(knowledge_id=1, knowledge_revision=knowledge_search_revision(row), data_revision='b'*64,
        embedding_model={'model_id': 2, 'revision': 'v1'}, documents=[{
            'file_ref': {'knowledge_id': 1, 'file_id': 'c'*32, 'file_version': 0}, 'filename': 'source.txt',
            'chunks': [{'chunk_index': 0, 'content': 'one', 'embedding': [1.0, 0.0]},
                       {'chunk_index': 1, 'content': 'three!', 'embedding': [0.0, 1.0]}],
        }])
    client = SimpleNamespace(sample_knowledge=AsyncMock(return_value=result))
    return SimpleNamespace(service=KnowledgeSummaryService(client=client, resources=ports), actor=actor, client=client,
                           result=result, update=update, closed=closed)


@pytest.fixture(autouse=True)
async def manager(sqlite_threads):  # noqa: F811
    value = ThreadManager(service_name='summary-ut', lane_policies={name: LanePolicy(name=name, max_workers=1,
        max_queue_size=4, queue_timeout_seconds=1, cancel_grace_seconds=1, shutdown_grace_seconds=3)
        for name in ('control-io', 'model-tool-io')})
    value.start(); set_default_thread_manager(value)
    try:
        yield value
    finally:
        clear_default_thread_manager(value)
        assert not (await value.shutdown(timeout=3)).stuck_execution_ids


async def test_sample_uses_exact_current_resource_and_actual_actor(setup):
    s = setup
    result = await s.service.sample('kb-one', batch_size=50, user_id=s.actor.user_id, tenant_id=s.actor.tenant_id)
    assert result == s.result and len(s.closed) == 2
    request, user_id, tenant_id = s.client.sample_knowledge.call_args.args
    assert request.knowledge_id == 1 and request.document_limit == 10
    assert request.expected_revision == s.result.knowledge_revision and (user_id, tenant_id) == ('user-a', 'tenant-a')


@pytest.mark.parametrize('dataset,change', [
    ('cleanse_knowledge', {'created_by': 'other', 'ingroup_permission': 'READ_ONLY'}),
    ('cleanse_knowledge', {'knowledge_sources': 'datamate'}),
    ('cleanse_knowledge', {'deletion_request': {'pending': True}}),
    ('cleanse_memberships', {'delete_flag': 'Y'}),
])
async def test_forbidden_resource_never_reaches_runtime(setup, dataset, change):
    s = setup; s.update(dataset, **change)
    with pytest.raises(ScopeDenied):
        await s.service.sample('kb-one', user_id='user-a', tenant_id='tenant-a')
    s.client.sample_knowledge.assert_not_awaited()


async def test_missing_or_foreign_index_is_not_found_without_sample(setup):
    s = setup
    for name, tenant in [('missing', 'tenant-a'), ('kb-one', 'tenant-b')]:
        with pytest.raises(NotFound):
            await s.service.sample(name, user_id='user-a', tenant_id=tenant)
    s.client.sample_knowledge.assert_not_awaited()


@pytest.mark.parametrize('change', ['resource', 'membership'])
async def test_late_revision_or_authorization_change_discards_sample(setup, change):
    s = setup
    async def reply(*args):
        s.update('cleanse_knowledge', index_name='changed') if change == 'resource' else s.update('cleanse_memberships', delete_flag='Y')
        return s.result
    s.client.sample_knowledge.side_effect = reply
    with pytest.raises((ScopeDenied, Conflict, NotFound)):
        await s.service.sample('kb-one', user_id='user-a', tenant_id='tenant-a')
    s.client.sample_knowledge.assert_awaited_once()


@pytest.mark.parametrize('change', ['knowledge', 'revision', 'model', 'foreign-file', 'duplicate', 'chunk-order', 'dimensions'])
async def test_invalid_response_does_not_reach_summary(setup, change):
    s = setup
    data = s.result.model_dump()
    if change == 'knowledge': data['knowledge_id'] = 2
    elif change == 'revision': data['knowledge_revision'] = 'd'*64
    elif change == 'model': data['embedding_model']['model_id'] = 3
    elif change == 'foreign-file': data['documents'][0]['file_ref']['knowledge_id'] = 2
    elif change == 'duplicate': data['documents'] *= 2
    elif change == 'chunk-order': data['documents'][0]['chunks'].reverse()
    else: data['documents'][0]['chunks'][1]['embedding'] = [1.0]
    s.client.sample_knowledge.return_value = KnowledgeSampleResult.model_validate(data)
    with pytest.raises((ScopeDenied, Conflict)):
        await s.service.sample('kb-one', user_id='user-a', tenant_id='tenant-a')


@pytest.mark.parametrize('batch_size,limit', [(1000, 200), (50, 10), (5000, 200)])
async def test_existing_batch_sampling_rule(setup, batch_size, limit):
    s = setup
    await s.service.sample('kb-one', batch_size=batch_size, user_id='user-a', tenant_id='tenant-a')
    assert s.client.sample_knowledge.call_args.args[0].document_limit == limit


@pytest.mark.parametrize('batch_size', [0, 1, 4, -1])
async def test_empty_sampling_budget_preserves_no_documents_error(setup, batch_size):
    with pytest.raises(ValueError, match='No documents found'):
        await setup.service.generate(index_name='kb-one', batch_size=batch_size, user_id='user-a', tenant_id='tenant-a')
    setup.client.sample_knowledge.assert_not_awaited()


async def test_actual_map_reduce_keeps_embeddings_and_model_identity(setup, monkeypatch):
    from management.services.knowledge_base import summary as summary_module

    s = setup
    invoke = Mock(side_effect=['document summary', 'cluster summary'])
    monkeypatch.setattr('management.services.knowledge_base.summary.invoke_chat_prompt_in_worker', invoke)
    orchestration = Mock(wraps=summary_module.summarize_clusters_map_reduce)
    monkeypatch.setattr(summary_module, 'summarize_clusters_map_reduce', orchestration)
    summary = await s.service.generate(index_name='kb-one', user_id='user-a', tenant_id='tenant-a', language='en', model_id=5)
    assert 'cluster summary' in summary and invoke.call_count == 2
    assert all(call.kwargs['user_id'] == 'user-a' and call.kwargs['tenant_id'] == 'tenant-a'
               and call.kwargs['model_id'] == 5 for call in invoke.call_args_list)
    assert 'one' in invoke.call_args_list[0].kwargs['user_prompt']
    assert orchestration.call_args.kwargs['doc_max_words'] == 100
    assert orchestration.call_args.kwargs['cluster_max_words'] == 150


async def test_sample_deadline_cancels_one_request_without_retry(setup):
    s = setup; cancelled = []
    async def hanging(*args):
        try: await asyncio.Event().wait()
        finally: cancelled.append(True)
    s.client.sample_knowledge.side_effect = hanging
    s.service.operation_seconds = .1
    with pytest.raises(DeadlineExceeded):
        await s.service.sample('kb-one', user_id='user-a', tenant_id='tenant-a')
    assert cancelled == [True]
    s.client.sample_knowledge.assert_awaited_once()


def test_neutral_adapter_keeps_weighted_document_embeddings(setup):
    from management.services.knowledge_base.summary import (
        sample_documents_for_clustering,
    )
    documents, embeddings = sample_documents_for_clustering(setup.result)
    assert documents['doc_0000']['filename'] == 'source.txt'
    assert documents['doc_0000']['path_or_url'] == 'c'*32
    np.testing.assert_allclose(embeddings['doc_0000'], [1/3, 2/3])


async def test_revocation_during_model_work_prevents_returning_summary(setup, monkeypatch):
    s = setup
    def invoke(**kwargs):
        s.update('cleanse_memberships', delete_flag='Y')
        return 'controlled model reply'
    monkeypatch.setattr('management.services.knowledge_base.summary.invoke_chat_prompt_in_worker', invoke)
    with pytest.raises(ScopeDenied):
        await s.service.generate(index_name='kb-one', user_id='user-a', tenant_id='tenant-a', model_id=5)
    s.client.sample_knowledge.assert_awaited_once()


async def test_model_work_runs_once_in_managed_model_lane(setup, monkeypatch):
    from management.services.knowledge_base import summary_service as module
    original = module.run_blocking
    calls = []
    async def observed(name, function, *args, **kwargs):
        calls.append((name, kwargs.get('lane'), kwargs.get('owner')))
        return await original(name, function, *args, **kwargs)
    monkeypatch.setattr(module, 'run_blocking', observed)
    monkeypatch.setattr('management.services.knowledge_base.summary.invoke_chat_prompt_in_worker', lambda **kwargs: 'summary')
    await setup.service.generate(index_name='kb-one', user_id='user-a', tenant_id='tenant-a', model_id=5)
    assert calls.count(('knowledge-summary', 'model-tool-io', 'management.knowledge.summary')) == 1
    assert sum(name == 'knowledge-summary-authorize' and lane == 'control-io' for name, lane, owner in calls) == 3


async def test_empty_runtime_sample_keeps_no_documents_error_without_model(setup, monkeypatch):
    s = setup
    s.client.sample_knowledge.return_value = s.result.model_copy(update={'documents': []})
    invoke = Mock()
    monkeypatch.setattr('management.services.knowledge_base.summary.invoke_chat_prompt_in_worker', invoke)
    with pytest.raises(ValueError, match='No documents found'):
        await s.service.generate(index_name='kb-one', user_id='user-a', tenant_id='tenant-a', model_id=5)
    invoke.assert_not_called()
    s.client.sample_knowledge.assert_awaited_once()


@pytest.mark.parametrize('user_id,tenant_id', [(None, 'tenant-a'), ('user-a', None)])
async def test_missing_identity_is_refused_without_runtime(setup, user_id, tenant_id):
    with pytest.raises(ScopeDenied):
        await setup.service.generate(index_name='kb-one', user_id=user_id, tenant_id=tenant_id)
    setup.client.sample_knowledge.assert_not_awaited()
