# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Trusted KB vector layout; legacy indexes remain intact during the migration."""

import hashlib
import json
from dataclasses import replace

from elasticsearch import Elasticsearch
from nexent.storage.errors import InvalidInput
from nexent.storage.models import StorageScope

from infrastructure.storage.catalog import FieldDefinition
from infrastructure.vdb.vector_schema import VectorBinding
from infrastructure.vdb.vector_store import ElasticsearchVectorStore


def knowledge_index(tenant_id, collection):
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (tenant_id, collection)
    ):
        raise InvalidInput()
    identity = json.dumps(
        [tenant_id, collection], separators=(",", ":"), ensure_ascii=True
    )
    return "si-kb-" + hashlib.sha256(identity.encode()).hexdigest()


def vector_binding(tenant_id, collection, dimensions, *, writable=True, allow_unembedded=False):
    fields = tuple(
        FieldDefinition(name, kind, nullable=name in {"file_id", "file_version", "chunk_index", "embedding_model_id", "embedding_revision", "parser_version", "filename", "media_kind"})
        for name, kind in (
            ("knowledge_id", "integer"),
            ("file_id", "string"),
            ("file_version", "integer"),
            ("chunk_index", "integer"),
            ("embedding_model_id", "integer"),
            ("embedding_revision", "string"),
            ("parser_version", "string"),
            ("media_kind", "string"),
            ("content", "string"),
            ("filename", "string"),
            ("location", "object"),
        )
    )
    return VectorBinding(
        collection,
        knowledge_index(tenant_id, collection),
        dimensions,
        fields,
        writable=writable,
        allow_unembedded=allow_unembedded,
        additive_fields=frozenset({"media_kind"}),
    )


def _configured_client(remaining):
    from contracts.constants import environment

    if not environment.ES_HOST:
        raise InvalidInput()
    return Elasticsearch(
        environment.ES_HOST,
        api_key=environment.ES_API_KEY or None,
        verify_certs=False,
        ssl_show_warn=False,
        request_timeout=min(5, remaining),
        max_retries=0,
        retry_on_timeout=False,
    )


def bind_knowledge_vectors(actor, collection, dimensions, *, writable=True, resource_tenant_id=None):
    from contracts.constants.constants import ASSET_OWNER_TENANT_ID
    from nexent.storage.errors import ScopeDenied

    tenant = actor.tenant_id if resource_tenant_id is None else resource_tenant_id
    if tenant not in {actor.tenant_id, ASSET_OWNER_TENANT_ID} or writable and tenant != actor.tenant_id:
        raise ScopeDenied()
    scope = StorageScope("runtime", tenant, actor.user_id, {collection})
    return ElasticsearchVectorStore(
        scope,
        (vector_binding(tenant, collection, dimensions, writable=writable, allow_unembedded=not writable or dimensions is not None),),
        _configured_client,
    )


def bind_knowledge_chunk_vectors(actor, collection, *, resource_tenant_id=None, dimensions=None):
    """Grant exact-record maintenance with optional explicit vector replacement."""
    from contracts.constants.constants import ASSET_OWNER_TENANT_ID
    from nexent.storage.errors import ScopeDenied

    tenant = actor.tenant_id if resource_tenant_id is None else resource_tenant_id
    if tenant not in {actor.tenant_id, ASSET_OWNER_TENANT_ID}:
        raise ScopeDenied()
    binding = replace(vector_binding(tenant, collection, dimensions, allow_unembedded=dimensions is not None),
                      mutable_fields=frozenset({"content", "filename", "location"}))
    return ElasticsearchVectorStore(
        StorageScope("runtime", tenant, actor.user_id, {collection}),
        (binding,), _configured_client,
    )


def bind_knowledge_creation_vectors(actor, collection, dimensions, *, resource_tenant_id=None):
    """Explicitly grant payload-only creation and later compatible vector mapping upgrades."""
    from contracts.constants.constants import ASSET_OWNER_TENANT_ID
    from nexent.storage.errors import ScopeDenied

    tenant = actor.tenant_id if resource_tenant_id is None else resource_tenant_id
    if tenant not in {actor.tenant_id, ASSET_OWNER_TENANT_ID}:
        raise ScopeDenied()
    return ElasticsearchVectorStore(
        StorageScope("runtime", tenant, actor.user_id, {collection}),
        (vector_binding(tenant, collection, dimensions, allow_unembedded=True),),
        _configured_client,
    )


def bind_knowledge_media_vectors(actor, resource):
    from nexent.storage.errors import ScopeDenied

    if resource.resource_tenant_id != actor.tenant_id:
        raise ScopeDenied()
    binding = replace(vector_binding(actor.tenant_id, resource.collection, None, allow_unembedded=True),
                      mutable_fields=frozenset({"media_kind"}))
    return ElasticsearchVectorStore(
        StorageScope("runtime", actor.tenant_id, actor.user_id, {resource.collection}),
        (binding,), _configured_client,
    )
