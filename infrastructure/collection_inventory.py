# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind a fixed Management technical reader for global collection health counts."""

from contextlib import contextmanager

from contracts.constants import environment
from nexent.storage.models import StorageScope

from infrastructure.knowledge_vectors import _configured_client
from infrastructure.rdb.composition import close_owned
from infrastructure.vdb.collection_inventory import (
    NAMESPACE,
    READER,
    ElasticsearchCollectionInventory,
)


@contextmanager
def collection_inventory_ports(*, context):
    if not environment.ES_HOST:
        raise ValueError('Elasticsearch host is not configured')
    inventory = ElasticsearchCollectionInventory(StorageScope('management', None, READER, {NAMESPACE}, system=True),
                                                _configured_client)
    try:
        context.remaining()
        yield inventory
    finally:
        close_owned(context, [inventory.close])
