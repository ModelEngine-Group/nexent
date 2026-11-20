# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Legacy vector inventory uses one exact read-only collection and scoped snapshot cursors."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from contracts.knowledge_maintenance import LEGACY_DOCUMENTS, LEGACY_VECTOR_METADATA
from nexent.core.concurrency import RunCancellationScope
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    InvalidInput,
    OperationCancelled,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    Comparison,
    PageRequest,
    RecordQuery,
    Sort,
    StorageScope,
)

from infrastructure.vdb.legacy_records import LegacyVectorRecords
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def store():
    client = Mock()
    client.options.return_value = client
    client.indices.get_mapping.return_value = {'old-kb': {'mappings': {'properties': {
        'embedding': {'type': 'dense_vector', 'dims': 2, 'similarity': 'cosine'}}}}}
    client.indices.get_settings.return_value = {'old-kb': {'settings': {'index': {'uuid': 'uuid-one'}}}}
    client.open_point_in_time.return_value = {'id': 'owned-pit'}
    client.close_point_in_time.return_value = {'succeeded': True, 'num_freed': 1}
    value = LegacyVectorRecords(StorageScope('management', 'tenant-a', 'operator',
        {LEGACY_DOCUMENTS, LEGACY_VECTOR_METADATA}), 'old-kb', Mock(return_value=client))
    return value, client


def hits(*positions, total=3):
    return {'pit_id': 'owned-pit', 'timed_out': False, '_shards': {'failed': 0},
        'hits': {'total': {'value': total, 'relation': 'eq'}, 'hits': [{'_id': str(i), '_seq_no': i,
            '_primary_term': 1, 'sort': [i], '_source': {'path_or_url': 'private://url', 'embedding': [1., 0.],
                'index': i, 'content': 'must not escape'}} for i in positions]}}


def test_scoped_pit_pages_and_metadata_never_expose_content_or_driver(store):
    port, client = store
    client.search.side_effect = [hits(1, 2, 3), hits(3)]
    metadata = port.get(LEGACY_VECTOR_METADATA, 'old-kb', context=context())
    assert metadata['dimensions'] == 2 and metadata['metric'] == 'cosine'
    first = port.query(LEGACY_DOCUMENTS, RecordQuery(), PageRequest(limit=2), context=context())
    assert [row['document_id'] for row in first.items] == ['1', '2'] and first.next_cursor
    assert 'content' not in first.items[0]['properties']
    last = port.query(LEGACY_DOCUMENTS, RecordQuery(), PageRequest(limit=2, cursor=first.next_cursor), context=context())
    assert [row['document_id'] for row in last.items] == ['3'] and last.next_cursor is None
    assert client.search.call_args.kwargs['body']['search_after'] == [2]
    port.close(); port.close()
    client.close_point_in_time.assert_called_once_with(id='owned-pit')
    assert all(call.kwargs['max_retries'] == 0 for call in client.options.call_args_list)


@pytest.mark.parametrize('operation', ['create', 'patch', 'delete', 'claim', 'increment'])
def test_writes_are_always_denied_without_requests(store, operation):
    port, client = store
    with pytest.raises(ScopeDenied): getattr(port, operation)(LEGACY_DOCUMENTS, {}, context=context())
    client.options.assert_not_called()


@pytest.mark.parametrize('change', ['timeout', 'partial', 'unordered', 'total', 'alias'])
def test_partial_or_ambiguous_reads_are_not_reported_as_complete(store, change):
    port, client = store
    response = hits(1, 2)
    if change == 'timeout': response['timed_out'] = True
    elif change == 'partial': response['_shards']['failed'] = 1
    elif change == 'unordered': response['hits']['hits'].reverse()
    elif change == 'total': response['hits']['total']['relation'] = 'gte'
    else: client.indices.get_mapping.return_value = {'other-index': {'mappings': {}}}
    client.search.return_value = response
    try:
        with pytest.raises((ScopeDenied, Unavailable)):
            port.query(LEGACY_DOCUMENTS, RecordQuery(), PageRequest(), context=context())
    finally: port.close()


def test_cursor_cannot_cross_actor_or_port_instance(store):
    port, client = store
    client.search.return_value = hits(1, 2, 3)
    cursor = port.query(LEGACY_DOCUMENTS, RecordQuery(), PageRequest(limit=2), context=context()).next_cursor
    other = LegacyVectorRecords(StorageScope('management', 'tenant-a', 'other', {LEGACY_DOCUMENTS, LEGACY_VECTOR_METADATA}),
        'old-kb', lambda remaining: client)
    try:
        with pytest.raises(InvalidInput): other.query(LEGACY_DOCUMENTS, RecordQuery(), PageRequest(cursor=cursor), context=context())
    finally: port.close(); other.close()


def test_count_and_pages_use_the_same_snapshot(store):
    port, client = store
    client.search.side_effect = [hits(total=2), hits(1, 2, total=2)]
    try:
        assert port.count(LEGACY_DOCUMENTS, RecordQuery(), context=context()) == 2
        assert len(port.query(LEGACY_DOCUMENTS, RecordQuery(), PageRequest(), context=context()).items) == 2
        client.open_point_in_time.assert_called_once()
    finally: port.close()


@pytest.mark.parametrize('query', [RecordQuery(where=Comparison('tenant_id', 'eq', 'foreign')),
                                RecordQuery(order_by=(Sort('document_id'),))])
def test_unsupported_predicates_or_order_cannot_bypass_bound_index(store, query):
    port, client = store
    with pytest.raises(CapabilityUnsupported): port.query(LEGACY_DOCUMENTS, query, PageRequest(), context=context())
    client.options.assert_not_called()


def test_cancel_closes_active_client_before_provider_call_returns(store):
    original, client = store
    scope = RunCancellationScope()
    port = LegacyVectorRecords(original.scope, 'old-kb', lambda remaining: client, cancellation_scope=scope)
    mapping = client.indices.get_mapping.return_value
    def cancelled(**kwargs):
        scope.cancel()
        client.close.assert_called_once()
        return mapping
    client.indices.get_mapping.side_effect = cancelled
    try:
        with pytest.raises(OperationCancelled): port.get(LEGACY_VECTOR_METADATA, 'old-kb', context=replace(context(), cancelled=scope.stop_event))
        client.close.assert_called_once()
    finally: port.close()


def test_index_recreated_between_metadata_and_pit_never_reads_documents(store):
    from nexent.storage.errors import Conflict

    port, client = store
    client.indices.get_settings.side_effect = [
        {'old-kb': {'settings': {'index': {'uuid': 'uuid-one'}}}},
        {'old-kb': {'settings': {'index': {'uuid': 'uuid-two'}}}},
    ]
    client.search.return_value = hits(1, 2, 3)
    try:
        with pytest.raises(Conflict): port.query(LEGACY_DOCUMENTS, RecordQuery(), PageRequest(), context=context())
        client.search.assert_not_called()
    finally: port.close()
    client.close_point_in_time.assert_called_once()


def test_exact_document_read_is_bound_to_the_physical_index_and_revision(store):
    port, client = store
    document = {'id': 'display-alias', 'content': 'original text', 'embedding': [1.0, 0.0]}
    client.get.return_value = {'_index': 'old-kb', '_id': 'native-key', '_source': document,
                               '_seq_no': 3, '_primary_term': 2, 'found': True}
    assert port.get(LEGACY_DOCUMENTS, 'native-key', context=context()) == {
        'document_id': 'native-key', 'tenant_id': 'tenant-a', 'revision': '3:2', 'properties': document,
    }
    client.get.assert_called_once_with(index='old-kb', id='native-key')
    client.search.assert_not_called()
    client.indices.get_settings.return_value = {'old-kb': {'settings': {'index': {'uuid': 'replacement'}}}}
    with pytest.raises(Conflict):
        port.get(LEGACY_DOCUMENTS, 'native-key', context=context())
