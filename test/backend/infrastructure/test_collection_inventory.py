# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""HEALTH-SI-01 proves scalar inventory, fixed scope and owned resources."""

from time import monotonic
from unittest.mock import Mock

import pytest
from elastic_transport import ConnectionError
from nexent.storage.errors import DeadlineExceeded, ScopeDenied, Unavailable
from nexent.storage.models import OperationContext, StorageScope


def context():
    return OperationContext('health-owned', monotonic() + 5)


def scope():
    return StorageScope('management', None, 'management.knowledge.health', {'vector_collections'}, system=True)


def test_inventory_counts_all_non_hidden_physical_collections_without_returning_names():
    from infrastructure.vdb.collection_inventory import ElasticsearchCollectionInventory

    client = Mock()
    client.options.return_value = client
    client.indices.get_alias.return_value = {'orphan': {}, 'si-kb-123': {}, '.internal': {}}
    inventory = ElasticsearchCollectionInventory(scope(), Mock(return_value=client))
    assert inventory.count(context=context()) == 2
    client.indices.get_alias.assert_called_once_with(index='*')
    assert client.options.call_args.kwargs['max_retries'] == 0
    client.close.assert_called_once()
    assert inventory.capabilities.supported == {'collection.count'}


@pytest.mark.parametrize('bad_scope', [
    StorageScope('runtime', None, 'management.knowledge.health', {'vector_collections'}, system=True),
    StorageScope('management', 'tenant', 'reader', {'vector_collections'}),
    StorageScope('management', None, 'other', {'vector_collections'}, system=True),
    StorageScope('management', None, 'management.knowledge.health', {'other'}, system=True),
])
def test_inventory_rejects_scope_before_provider(bad_scope):
    from infrastructure.vdb.collection_inventory import ElasticsearchCollectionInventory

    factory = Mock()
    with pytest.raises(ScopeDenied):
        ElasticsearchCollectionInventory(bad_scope, factory)
    factory.assert_not_called()


def test_provider_failure_is_explicit_and_closes_without_retry():
    from infrastructure.vdb.collection_inventory import ElasticsearchCollectionInventory

    client = Mock()
    client.options.return_value = client
    client.indices.get_alias.side_effect = ConnectionError('owned-fault')
    factory = Mock(return_value=client)
    inventory = ElasticsearchCollectionInventory(scope(), factory)
    with pytest.raises(Unavailable):
        inventory.count(context=context())
    assert client.indices.get_alias.call_count == factory.call_count == 1
    client.close.assert_called_once()


def test_deadline_after_response_does_not_turn_into_healthy_zero():
    from infrastructure.vdb.collection_inventory import ElasticsearchCollectionInventory

    client = Mock()
    client.options.return_value = client
    ctx = Mock(operation_id='owned')
    ctx.remaining.side_effect = [5, 5, DeadlineExceeded()]
    with pytest.raises(DeadlineExceeded):
        ElasticsearchCollectionInventory(scope(), Mock(return_value=client)).count(context=ctx)
    client.close.assert_called_once()
