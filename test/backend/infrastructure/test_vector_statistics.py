# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-INFRA-DPR-VECTOR-STATS-01/02 keep collection summaries inside scoped SI."""

from threading import Event
from time import monotonic
from unittest.mock import Mock

import pytest
from elasticsearch import NotFoundError
from nexent.storage.errors import (
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    OperationCancelled,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import OperationContext, StorageScope, VectorSummaryField

from infrastructure.storage.catalog import FieldDefinition
from infrastructure.vdb.vector_schema import VectorBinding
from infrastructure.vdb.vector_store import ElasticsearchVectorStore


def context():
    return OperationContext('statistics', monotonic() + 5)


@pytest.fixture
def boundary():
    client = Mock()
    client.options.return_value = client
    client.indices.stats.return_value = {'_shards': {'failed': 0}, 'indices': {'owned-index': {'primaries': {
        'docs': {'count': 3}, 'store': {'size_in_bytes': 1024}, 'search': {'query_total': 8},
        'request_cache': {'hit_count': 2}}}}}
    client.indices.get_settings.return_value = {'owned-index': {'settings': {'index': {'creation_date': '1700000000000'}}}}
    client.search.return_value = {'timed_out': False, '_shards': {'failed': 0}, 'aggregations': {'s0': {'value': 2.0}, 't0': {'buckets': [
        {'key': 'a.txt', 'doc_count': 2}, {'key': 'b.txt', 'doc_count': 1}]}}}
    binding = VectorBinding('kb', 'owned-index', None, (
        FieldDefinition('content', 'string'), FieldDefinition('location', 'object'),
        FieldDefinition('filename', 'string')), allow_unembedded=True, owns_collection=True)
    factory = Mock(return_value=client)
    port = ElasticsearchVectorStore(StorageScope('runtime', 'tenant-a', 'operator', {'kb'}), (binding,), factory)
    return port, client, factory


def summary():
    return VectorSummaryField('source', (('location', 'nexent_public_chunk_v1', 'path_or_url'),
                                          ('location', 'path_or_url')))


def test_statistics_returns_neutral_metrics_and_bounded_source_backed_summary(boundary):
    port, client, _ = boundary
    result = port.statistics('kb', (summary(),), context=context())
    assert result.collection == 'kb'
    assert (result.record_count, result.size_bytes, result.created_at_ms, result.query_count,
            result.cache_hit_count) == (3, 1024, 1700000000000, 8, 2)
    assert len(result.summaries) == 1
    assert result.summaries[0].name == 'source' and result.summaries[0].distinct_count == 2
    assert result.summaries[0].top_values == ('a.txt', 'b.txt')
    assert 'vector.collection.statistics' in port.capabilities.supported
    client.indices.stats.assert_called_once_with(index='owned-index')
    client.indices.get_settings.assert_called_once_with(index='owned-index')
    call = client.search.call_args.kwargs
    assert call['index'] == 'owned-index' and call['body']['size'] == 0
    assert call['body']['query']['bool']['filter'][:2] == [
        {'term': {'_si_tenant': 'tenant-a'}}, {'term': {'_si_collection': 'kb'}}]
    assert call['allow_partial_search_results'] is False
    field = call['body']['runtime_mappings']['si_summary_0']
    assert field['type'] == 'keyword'
    assert field['script']['params']['paths'] == [['payload', *path] for path in summary().paths]
    assert 'path_or_url' not in field['script']['source']
    assert call['body']['aggs']['s0'] == {'cardinality': {'field': 'si_summary_0'}}
    assert call['body']['aggs']['t0']['terms']['size'] == 10
    assert client.options.call_count == 3
    assert all(c.kwargs['max_retries'] == 0 and c.kwargs['retry_on_timeout'] is False
               and 0 < c.kwargs['request_timeout'] <= 5 for c in client.options.call_args_list)
    client.close.assert_called_once()
    client.indices.create.assert_not_called(); client.indices.put_mapping.assert_not_called(); client.bulk.assert_not_called()


def test_metadata_only_statistics_does_not_search_or_read_vectors(boundary):
    port, client, _ = boundary
    result = port.statistics('kb', context=context())
    assert result.summaries == () and result.record_count == 3
    client.search.assert_not_called()
    client.indices.get_mapping.assert_not_called()
    client.close.assert_called_once()


@pytest.mark.parametrize('field', [
    VectorSummaryField('wrong', (('unknown',),)), VectorSummaryField('text', (('content',),)),
    VectorSummaryField('nested', (('filename', 'child'),)),
])
def test_invalid_or_unindexed_scalar_paths_never_open_provider(boundary, field):
    port, _, factory = boundary
    with pytest.raises(InvalidInput):
        port.statistics('kb', (field,), context=context())
    factory.assert_not_called()


@pytest.mark.parametrize('fields', [(summary(), summary()), (summary(),) * 11, [summary()], ('source',)])
def test_field_list_must_be_finite_distinct_and_typed(boundary, fields):
    port, _, factory = boundary
    with pytest.raises(InvalidInput):
        port.statistics('kb', fields, context=context())
    factory.assert_not_called()


@pytest.mark.parametrize('name,paths', [('', (('location',),)), ('x', ()), ('x', (('location', 'a.b'),)),
    ('x', (('location', 'x;emit(secret)'),)), ('x', (('location',) * 9,)),
    ('x', (('location',),) * 5), ('x', (('location',), ('location',)))])
def test_invalid_neutral_summary_field_is_rejected(name, paths):
    with pytest.raises(InvalidInput):
        VectorSummaryField(name, paths)


@pytest.mark.parametrize('closed', [False, True])
def test_missing_namespace_or_closed_port_never_opens_provider(boundary, closed):
    port, _, factory = boundary
    if closed:
        port.close()
    with pytest.raises(ScopeDenied):
        port.statistics('kb' if closed else 'other', context=context())
    factory.assert_not_called()


def test_collection_wide_metrics_require_trusted_exclusive_ownership(boundary):
    from dataclasses import replace

    port, _, factory = boundary
    shared = ElasticsearchVectorStore(port.scope, (replace(port._bindings['kb'], owns_collection=False),), factory)
    with pytest.raises(ScopeDenied):
        shared.statistics('kb', context=context())
    assert 'vector.collection.statistics' not in shared.capabilities.supported
    factory.assert_not_called()


@pytest.mark.parametrize('metric,value', [('count', -1), ('count', True), ('size_in_bytes', None),
    ('query_total', 1.5), ('hit_count', float('nan'))])
def test_malformed_physical_metrics_never_default_to_zero(boundary, metric, value):
    port, client, _ = boundary
    primaries = client.indices.stats.return_value['indices']['owned-index']['primaries']
    owner = {'count': 'docs', 'size_in_bytes': 'store', 'query_total': 'search', 'hit_count': 'request_cache'}[metric]
    primaries[owner][metric] = value
    with pytest.raises(Unavailable):
        port.statistics('kb', context=context())
    client.close.assert_called_once()


@pytest.mark.parametrize('response', [{}, {'aggregations': {'s0': {'value': -1}, 't0': {'buckets': []}}},
    {'aggregations': {'s0': {'value': 1}, 't0': {'buckets': [{'key': {}, 'doc_count': 1}]}}},
    {'aggregations': {'s0': {'value': 2}, 't0': {'buckets': [{'key': 'a', 'doc_count': 1}] * 2}}}])
def test_invalid_summary_response_is_an_error_without_reissue(boundary, response):
    port, client, _ = boundary
    client.search.return_value = response
    with pytest.raises(Unavailable):
        port.statistics('kb', (summary(),), context=context())
    assert client.search.call_count == 1
    client.close.assert_called_once()


@pytest.mark.parametrize('error,expected', [(OSError('private provider address'), Unavailable),
    (NotFoundError('missing', meta=Mock(status=404), body={}), NotFound)])
def test_provider_failure_is_neutral_and_never_retried(boundary, error, expected):
    port, client, _ = boundary
    client.indices.stats.side_effect = error
    with pytest.raises(expected) as caught:
        port.statistics('kb', context=context())
    assert 'private provider address' not in str(caught.value)
    assert client.indices.stats.call_count == 1
    client.close.assert_called_once()


@pytest.mark.parametrize('phase,partial', [('stats', 'shards'), ('search', 'shards'), ('search', 'timeout')])
def test_partial_or_timed_out_provider_results_cannot_be_reported_as_complete(boundary, phase, partial):
    port, client, _ = boundary
    response = client.indices.stats.return_value if phase == 'stats' else client.search.return_value
    if partial == 'shards':
        response['_shards']['failed'] = 1
    else:
        response['timed_out'] = True
    with pytest.raises(Unavailable):
        port.statistics('kb', (summary(),), context=context())
    assert client.indices.stats.call_count == 1
    if phase == 'stats':
        client.indices.get_settings.assert_not_called(); client.search.assert_not_called()
    else:
        assert client.search.call_count == 1
    client.close.assert_called_once()


def test_cancellation_after_first_response_closes_and_stops_remaining_requests(boundary):
    port, client, _ = boundary
    signal = Event()
    parent = OperationContext('cancel-after-response', monotonic() + 5, cancelled=signal)
    def cancel(**kwargs):
        signal.set()
        return client.indices.stats.return_value
    client.indices.stats.side_effect = cancel
    with pytest.raises(OperationCancelled):
        port.statistics('kb', (summary(),), context=parent)
    client.indices.stats.assert_called_once()
    client.indices.get_settings.assert_not_called(); client.search.assert_not_called()
    client.close.assert_called_once()


@pytest.mark.parametrize('cancelled', [False, True])
def test_cancelled_or_expired_request_never_opens_provider(boundary, cancelled):
    port, _, factory = boundary
    signal = Event()
    if cancelled:
        signal.set()
    parent = OperationContext('expired', monotonic() - 1, cancelled=signal)
    with pytest.raises(OperationCancelled if cancelled else DeadlineExceeded):
        port.statistics('kb', context=parent)
    factory.assert_not_called()
