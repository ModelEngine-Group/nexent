# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read scalar collection inventory without exposing physical names or clients."""

import asyncio
from collections.abc import Mapping

from nexent.storage.errors import CapabilityUnsupported, ScopeDenied, Unavailable
from nexent.storage.models import CapabilitySet

from infrastructure.vdb.vector_store import ElasticsearchVectorStore

NAMESPACE = 'vector_collections'
READER = 'management.knowledge.health'


class ElasticsearchCollectionInventory:
    capabilities = CapabilitySet(frozenset({'collection.count'}))

    def __init__(self, scope, client_factory):
        if (scope.service_role != 'management' or not scope.system or scope.tenant_id is not None
            or scope.actor_id != READER or scope.namespaces != {NAMESPACE} or scope.resource_prefix):
            raise ScopeDenied()
        self.scope, self._factory, self._closed = scope, client_factory, False

    def count(self, *, context):
        if self._closed:
            raise ScopeDenied()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise CapabilityUnsupported()
        client = self._factory(context.remaining())
        try:
            result = ElasticsearchVectorStore._call(client, 'indices.get_alias', context, index='*')
            body = getattr(result, 'body', result)
            if not isinstance(body, Mapping) or not all(isinstance(key, str) for key in body):
                raise Unavailable(operation_id=context.operation_id)
            return sum(not name.startswith('.') for name in body)
        finally:
            client.close()

    def close(self):
        self._closed = True
