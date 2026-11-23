# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-COL-META-02 describe a batch with two grants and no model calls."""

import asyncio
from contextlib import contextmanager
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.knowledge_collections import (
    KnowledgeCollectionGrant,
    KnowledgeCollectionsDescribe,
    KnowledgeCollectionsGrant,
    KnowledgeModelDisplay,
    KnowledgeVectorMedia,
)
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    OperationContext,
    VectorCollectionInfo,
    VectorCollectionStatistics,
    VectorFieldStatistics,
)
from runtime.knowledge_base import collection_metadata as module

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def boundary(mocker):
    actor = ServicePrincipal('reader', 'tenant-a')
    grants = KnowledgeCollectionsGrant(knowledge_bases=[
        KnowledgeCollectionGrant(knowledge_id=1, collection='one', resource_tenant_id='tenant-a', revision='a' * 64),
        KnowledgeCollectionGrant(knowledge_id=2, collection='two', resource_tenant_id='tenant-b', revision='b' * 64)])
    client = SimpleNamespace(authorize_collection_metadata=AsyncMock(return_value=grants))
    opened, closed, contexts = [], [], []
    vectors = {}
    for grant in grants.knowledge_bases:
        vectors[grant.knowledge_id] = SimpleNamespace(
            scope=SimpleNamespace(service_role='runtime', tenant_id=grant.resource_tenant_id,
                actor_id=actor.user_id, system=False, resource_prefix='', namespaces={grant.collection}),
            collection_exists=Mock(return_value=True),
            describe_collection=Mock(return_value=VectorCollectionInfo(grant.collection, None, 'cosine')),
            statistics=Mock(return_value=VectorCollectionStatistics(grant.collection, 4, 10, 100, 0, 0, (
                VectorFieldStatistics('source', 2, ('a', 'b')), VectorFieldStatistics('processor', 1, ('Clean',)),
                VectorFieldStatistics('model', 1, ('repo/model',))))))

    @contextmanager
    def ports(principal, grant, *, context):
        assert principal == actor
        opened.append(grant.knowledge_id); contexts.append(context)
        try:
            yield vectors[grant.knowledge_id]
        finally:
            closed.append(grant.knowledge_id)

    async def blocking(name, action, *args, **kwargs):
        assert name == 'knowledge-collection-describe'
        assert kwargs.pop('lane') == 'control-io' and kwargs.pop('owner') == 'runtime.knowledge_base'
        return action(*args, **kwargs)

    worker = mocker.patch.object(module, 'run_blocking', side_effect=blocking)
    display = Mock(return_value=KnowledgeModelDisplay(display_name='Authorized', is_multimodal=True))
    service = module.KnowledgeCollectionMetadataService(client, ports=ports, display=display)
    request = KnowledgeCollectionsDescribe(knowledge_ids=[2, 1], expected_revisions={1: 'a' * 64, 2: 'b' * 64})
    return SimpleNamespace(**locals())


async def invoke(s):
    return await s.service.describe(s.request, s.actor)


@pytest.mark.asyncio
async def test_batch_preserves_order_empty_model_and_only_two_authorization_roundtrips(boundary):
    s = boundary
    result = await invoke(s)
    assert [item.knowledge_id for item in result.items] == [2, 1]
    assert all(item.present and item.dimensions is None and item.metric == 'cosine' and item.statistics is None
               for item in result.items)
    assert s.client.authorize_collection_metadata.await_count == 2
    assert s.opened == s.closed == [2, 1] and len(s.contexts) == 2
    assert s.contexts[0] is s.contexts[1] and s.contexts[0].cancelled.is_set()
    assert s.worker.await_count == 1
    for port in s.vectors.values():
        port.statistics.assert_not_called()
    s.display.assert_not_called()


async def test_vector_media_inventory_only_counts_physical_embeddings_for_selected_kb(boundary):
    s = boundary
    for port in s.vectors.values():
        port.count = Mock(side_effect=[6, 3, 2])
    s.request.include_vector_media = True
    result = await invoke(s)
    assert [item.vector_media.model_dump() for item in result.items] == [
        {"text": 3, "image": 2, "unclassified": 1}, {"text": 3, "image": 2, "unclassified": 1},
    ]
    for key, port in s.vectors.items():
        total, text, image = port.count.call_args_list
        assert total.args[1].value == key
        assert [query.args[1].terms[-1].value for query in (text, image)] == ["text", "image"]
        assert all(query.kwargs["vectors_only"] for query in (total, text, image))
        port.statistics.assert_not_called()
    s.display.assert_not_called()


@pytest.mark.asyncio
async def test_statistics_uses_finite_neutral_summaries(boundary):
    s = boundary
    s.request.include_statistics = True
    result = await invoke(s)
    stats = result.items[0].statistics
    assert (stats.record_count, stats.source_count, stats.process_source, stats.embedding_model_name) == (4, 2, 'Clean', 'repo/model')
    assert stats.size_bytes == 10 and stats.query_count == stats.cache_hit_count == 0
    fields = s.vectors[2].statistics.call_args.args[1]
    assert [field.name for field in fields] == ['source', 'processor', 'model']
    assert fields[0].paths == (('location', 'nexent_public_chunk_v1', 'path_or_url'), ('location', 'path_or_url'))
    assert result.items[0].model_display.display_name == 'Authorized'
    assert s.display.call_count == 2
    assert s.display.call_args_list[0].args == (s.actor, s.grants.knowledge_bases[1])
    assert s.display.call_args_list[0].kwargs['context'] is s.contexts[0]


@pytest.mark.asyncio
async def test_absence_is_an_actual_false_without_describe_statistics_or_ensure(boundary):
    s = boundary
    s.request.include_statistics = True
    s.vectors[1].collection_exists.return_value = False
    result = await invoke(s)
    missing = result.items[1]
    assert not missing.present and missing.dimensions is missing.metric is missing.statistics is None
    s.vectors[1].describe_collection.assert_not_called(); s.vectors[1].statistics.assert_not_called()


@pytest.mark.asyncio
async def test_stale_revision_fails_before_opening_any_provider(boundary):
    s = boundary
    s.request.expected_revisions[1] = 'c' * 64
    with pytest.raises(Conflict):
        await invoke(s)
    assert not s.opened and s.worker.await_count == 0


@pytest.mark.asyncio
async def test_reauthorization_failure_never_returns_partial_results(boundary):
    s = boundary
    s.client.authorize_collection_metadata.side_effect = [s.grants, ScopeDenied()]
    with pytest.raises(ScopeDenied):
        await invoke(s)
    assert s.opened == s.closed == [2, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['exists', 'scope', 'describe'])
async def test_invalid_or_unavailable_provider_response_stops_the_batch(boundary, phase):
    s = boundary
    if phase == 'exists':
        s.vectors[2].collection_exists.side_effect = Unavailable()
    elif phase == 'scope':
        s.vectors[2].scope.actor_id = 'other'
    elif phase == 'describe':
        s.vectors[2].describe_collection.return_value = VectorCollectionInfo('wrong', 3, 'cosine')
    with pytest.raises(ScopeDenied if phase == 'scope' else Unavailable):
        await invoke(s)
    assert s.opened == s.closed == [2] and s.client.authorize_collection_metadata.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('error,code', [(Unavailable(), 'unavailable'), (Conflict(), 'conflict'),
    (NotFound(), 'not_found'), (CapabilityUnsupported(), 'unsupported'), (InvalidInput(), 'invalid_input')])
async def test_optional_statistics_failure_preserves_each_item_and_model_display(boundary, error, code):
    s = boundary
    s.request.include_statistics = True
    s.vectors[2].statistics.side_effect = error
    result = await invoke(s)
    failed, healthy = result.items
    assert failed.present and failed.statistics is None and failed.statistics_error == code
    assert failed.model_display.display_name == 'Authorized'
    assert healthy.statistics.record_count == 4 and healthy.statistics_error is None
    assert s.opened == s.closed == [2, 1] and s.client.authorize_collection_metadata.await_count == 2
    assert s.vectors[2].statistics.call_count == 1 and s.display.call_count == 2


@pytest.mark.asyncio
async def test_invalid_statistics_is_reported_without_zero_values(boundary):
    s = boundary
    s.request.include_statistics = True
    s.vectors[2].statistics.return_value = VectorCollectionStatistics('two', -1, 0, 0, 0, 0, ())
    result = await invoke(s)
    assert result.items[0].statistics is None and result.items[0].statistics_error == 'unavailable'


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [DeadlineExceeded(), ScopeDenied(), asyncio.CancelledError()])
async def test_optional_statistics_never_hides_deadline_scope_or_cancellation(boundary, error):
    s = boundary
    s.request.include_statistics = True
    s.vectors[2].statistics.side_effect = error
    with pytest.raises(type(error)):
        await invoke(s)
    assert s.opened == s.closed == [2]
    s.display.assert_not_called()


@pytest.mark.asyncio
async def test_revocation_after_optional_statistics_error_still_rejects_everything(boundary):
    s = boundary
    s.request.include_statistics = True
    s.vectors[2].statistics.side_effect = Unavailable()
    s.client.authorize_collection_metadata.side_effect = [s.grants, ScopeDenied()]
    with pytest.raises(ScopeDenied):
        await invoke(s)
    assert s.opened == s.closed == [2, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['timeout', 'cancel'])
async def test_timeout_or_cancellation_stops_before_provider_and_sets_cancellation(boundary, outcome, caplog):
    s = boundary
    s.service.seconds = 0.02
    if outcome == 'timeout':
        async def never(*args, **kwargs):
            await asyncio.Event().wait()
        s.client.authorize_collection_metadata.side_effect = never
    else:
        s.client.authorize_collection_metadata.side_effect = asyncio.CancelledError()
    with pytest.raises(DeadlineExceeded if outcome == 'timeout' else asyncio.CancelledError):
        await invoke(s)
    assert not s.opened and s.client.authorize_collection_metadata.await_count == 1
    assert ('knowledge_collection_describe_timeout' in caplog.text) == (outcome == 'timeout')


@pytest.mark.asyncio
async def test_expired_parent_never_starts_authorization(boundary):
    s = boundary
    with pytest.raises(DeadlineExceeded):
        await s.service.describe(s.request, s.actor, context=OperationContext('expired', monotonic() - 1))
    s.client.authorize_collection_metadata.assert_not_awaited()


async def test_native_metadata_selects_original_index_ports(boundary, monkeypatch):
    s = boundary
    native = Mock(side_effect=s.ports)
    monkeypatch.setattr(module, "native_collection_analytics", native)
    s.service.ports = Mock(side_effect=AssertionError("Managed collection should not be consulted"))
    for port in s.vectors.values():
        port.vector_media = Mock(return_value=KnowledgeVectorMedia(text=2, image=1, unclassified=0))
    s.request = s.request.model_copy(update={"native_documents": True, "include_vector_media": True,
                                           "include_statistics": True})
    result = await invoke(s)
    assert native.call_count == 2 and [row.statistics.record_count for row in result.items] == [4, 4]
    assert all(row.vector_media.image == 1 for row in result.items)
    s.service.ports.assert_not_called()
