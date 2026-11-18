# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Neutral vector scans preserve scope, stored embeddings and keyset progress."""

from dataclasses import replace

import pytest
from nexent.storage.errors import InvalidInput, ScopeDenied, Unavailable
from nexent.storage.models import Comparison, PageRequest, StorageScope

from infrastructure.vdb.vector_store import ElasticsearchVectorStore
from test.backend.infrastructure.test_vector_store import context, store  # noqa: F401


def hit(key, *, tenant='tenant-a', collection='kb'):
    return {'_source': {'_si_tenant': tenant, '_si_collection': collection, '_si_key': key,
        '_si_generation': 'generation-1', 'embedding': [1.0, 0.0], 'payload': {'content': key, 'file_id': 'file'}}}


def test_scan_preserves_vector_generation_and_mandatory_scope(store):  # noqa: F811
    port, client, _ = store
    client.search.return_value = {'hits': {'hits': [hit('a'), hit('b'), hit('c')]}}
    page = port.scan('kb', Comparison('file_id', 'eq', 'file'), PageRequest(limit=2), context=context())
    assert [r.key.key for r in page.items] == ['a', 'b'] and page.next_cursor
    assert page.items[0].vector == (1.0, 0.0) and page.items[0].generation.value == 'generation-1'
    options = client.search.call_args.kwargs
    assert options['size'] == 3 and options['sort'] == [{'_si_key': 'asc'}]
    assert {'term': {'_si_tenant': 'tenant-a'}} in options['query']['bool']['filter']
    assert {'term': {'_si_collection': 'kb'}} in options['query']['bool']['filter']
    assert 'embedding' in options['source']
    client.close.assert_called_once()


def test_payload_only_scan_needs_no_model_dimensions_or_embedding(store):  # noqa: F811
    original, client, factory = store
    binding = replace(original._bindings['kb'], dimensions=None)
    port = ElasticsearchVectorStore(original.scope, (binding,), factory)
    row = hit('a')
    del row['_source']['embedding']
    client.search.return_value = {'hits': {'hits': [row]}}
    result = port.scan('kb', None, PageRequest(), context=context(), include_vector=False)
    assert result.items[0].vector == () and result.items[0].payload['content'] == 'a'
    assert 'embedding' not in client.search.call_args.kwargs['source']


def test_vector_cursor_cannot_be_reused_for_payload_only_scan(store):  # noqa: F811
    port, client, factory = store
    client.search.return_value = {'hits': {'hits': [hit('a'), hit('b')]}}
    first = port.scan('kb', None, PageRequest(limit=1), context=context())
    factory.reset_mock()
    with pytest.raises(InvalidInput):
        port.scan('kb', None, PageRequest(limit=1, cursor=first.next_cursor), context=context(), include_vector=False)
    factory.assert_not_called()


def test_cursor_resumes_by_key_after_previous_rows_disappear(store):  # noqa: F811
    port, client, _ = store
    client.search.return_value = {'hits': {'hits': [hit('a'), hit('b'), hit('c')]}}
    first = port.scan('kb', None, PageRequest(limit=2), context=context())
    client.search.return_value = {'hits': {'hits': [hit('c'), hit('d')]}}
    second = port.scan('kb', None, PageRequest(limit=2, cursor=first.next_cursor), context=context())
    assert client.search.call_args.kwargs['search_after'] == ['b']
    assert [r.key.key for r in second.items] == ['c', 'd'] and second.next_cursor is None


@pytest.mark.parametrize('change', ['actor', 'tenant', 'where', 'schema'])
def test_cursor_cannot_escape_original_scope_or_query(store, change):  # noqa: F811
    port, client, factory = store
    client.search.return_value = {'hits': {'hits': [hit('a'), hit('b')]}}
    first = port.scan('kb', None, PageRequest(limit=1), context=context())
    scope, binding = port.scope, port._bindings['kb']
    if change == 'actor':
        scope = StorageScope('runtime', 'tenant-a', 'other', {'kb'})
    elif change == 'tenant':
        scope = StorageScope('runtime', 'other', 'user', {'kb'})
    elif change == 'schema':
        binding = replace(binding, dimensions=3)
    another = ElasticsearchVectorStore(scope, (binding,), factory)
    factory.reset_mock()
    with pytest.raises(InvalidInput):
        another.scan('kb', Comparison('file_id', 'eq', 'different') if change == 'where' else None,
                     PageRequest(limit=1, cursor=first.next_cursor), context=context())
    factory.assert_not_called()


@pytest.mark.parametrize('cursor', ['not a cursor', '', 'e30=', 'x' * 17000],
                         ids=['invalid-base64', 'empty', 'missing-fields', 'oversized'])
def test_invalid_cursor_rejected_before_provider_call(store, cursor):  # noqa: F811
    port, _, factory = store
    with pytest.raises(InvalidInput):
        port.scan('kb', None, PageRequest(cursor=cursor), context=context())
    factory.assert_not_called()


@pytest.mark.parametrize('reply', [
    {'timed_out': True, 'hits': {'hits': []}}, {'_shards': {'failed': 1}, 'hits': {'hits': []}},
    {'hits': {'hits': [hit('b'), hit('a')]}}, {'hits': {'hits': [hit('a'), hit('a')]}},
    None, {'hits': None}, {'_shards': None, 'hits': {'hits': []}},
    {'hits': {'hits': [{'not_source': True}]}},
])
def test_partial_or_unordered_provider_result_is_not_success(store, reply):  # noqa: F811
    port, client, _ = store
    client.search.return_value = reply
    with pytest.raises(Unavailable):
        port.scan('kb', None, PageRequest(), context=context())
    client.search.assert_called_once()
    client.close.assert_called_once()


@pytest.mark.parametrize('changes', [{'tenant': 'other'}, {'collection': 'other'}])
def test_foreign_records_are_never_returned(store, changes):  # noqa: F811
    port, client, _ = store
    client.search.return_value = {'hits': {'hits': [hit('a', **changes)]}}
    with pytest.raises(ScopeDenied):
        port.scan('kb', None, PageRequest(), context=context())


def test_read_only_vector_binding_can_scan_without_gaining_write_access(store):  # noqa: F811
    port, client, factory = store
    readonly = ElasticsearchVectorStore(port.scope, (replace(port._bindings['kb'], writable=False),), factory)
    client.search.return_value = {'hits': {'hits': []}}
    assert not readonly.scan('kb', None, PageRequest(), context=context()).items
    readonly.capabilities.require('vector.scan')
