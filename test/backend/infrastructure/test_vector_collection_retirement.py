# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB-COLLECTION-04: only explicitly owned, physically empty collections retire."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from nexent.storage.errors import (
    Conflict,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import StorageScope, WriteOutcome

from infrastructure.vdb.vector_store import ElasticsearchVectorStore
from test.backend.infrastructure.test_vector_store import context, store  # noqa: F401


@pytest.fixture
def owned(store):  # noqa: F811
    port, client, _ = store
    binding = replace(port._bindings['kb'], dimensions=None, owns_collection=True)
    factory = Mock(return_value=client)
    return ElasticsearchVectorStore(StorageScope('runtime', 'tenant-a', 'user', {'kb'}), (binding,), factory), client, factory


def test_normal_file_port_cannot_remove_a_collection(store):  # noqa: F811
    port, _client, factory = store
    with pytest.raises(ScopeDenied):
        port.delete_empty_collection('kb', context=context())
    factory.assert_not_called()


def test_maintenance_existence_does_not_need_model_dimensions(owned):
    port, client, _ = owned
    client.indices.exists.return_value = False
    assert port.collection_exists('kb', context=context()) is False
    client.indices.get_mapping.assert_not_called()


def test_empty_collection_is_dropped_once_and_absence_is_confirmed(owned):
    port, client, _ = owned
    client.count.return_value = {'count': 0}
    client.indices.delete.return_value = {'acknowledged': True}
    client.indices.exists.return_value = False
    receipt = port.delete_empty_collection('kb', context=context())
    assert receipt.outcome is WriteOutcome.CONFIRMED and receipt.deleted
    client.count.assert_called_once_with(index='proof-index', query={'match_all': {}})
    client.indices.delete.assert_called_once_with(index='proof-index')


def test_unexpected_foreign_documents_block_whole_index_deletion(owned):
    port, client, _ = owned
    client.count.return_value = {'count': 1}
    with pytest.raises(Conflict):
        port.delete_empty_collection('kb', context=context())
    client.indices.delete.assert_not_called()


@pytest.mark.parametrize('ack,exists', [(False, False), (True, True)])
def test_unconfirmed_or_still_existing_collection_is_not_success(owned, ack, exists):
    port, client, _ = owned
    client.count.return_value = {'count': 0}
    client.indices.delete.return_value = {'acknowledged': ack}
    client.indices.exists.return_value = exists
    with pytest.raises(OutcomeUnknown):
        port.delete_empty_collection('kb', context=context())
    assert client.indices.delete.call_count == 1


def test_absent_collection_requires_no_delete(owned, monkeypatch):
    port, client, _ = owned
    original = port._call

    def missing(target, method, *args, **kwargs):
        if method == 'count':
            raise NotFound()
        return original(target, method, *args, **kwargs)

    monkeypatch.setattr(port, '_call', missing)
    assert port.delete_empty_collection('kb', context=context()).deleted is False
    client.indices.delete.assert_not_called()


@pytest.mark.parametrize('count', [True, -1, '0', None])
def test_malformed_count_does_not_authorize_deletion(owned, count):
    port, client, _ = owned
    client.count.return_value = {'count': count}
    with pytest.raises(Unavailable):
        port.delete_empty_collection('kb', context=context())
    client.indices.delete.assert_not_called()


def test_even_owned_collection_requires_write_authority(owned):
    port, client, factory = owned
    readonly = ElasticsearchVectorStore(port.scope, (replace(port._bindings['kb'], writable=False),), factory)
    with pytest.raises(ScopeDenied):
        readonly.delete_empty_collection('kb', context=context())
    factory.assert_not_called()
    client.count.assert_not_called()
