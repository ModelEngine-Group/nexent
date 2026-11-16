# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Trusted KB vector layout; legacy indexes remain intact during the migration."""

import hashlib
import json

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


def vector_binding(tenant_id, collection, dimensions):
    fields = tuple(
        FieldDefinition(name, kind)
        for name, kind in (
            ("knowledge_id", "integer"),
            ("file_id", "string"),
            ("file_version", "integer"),
            ("chunk_index", "integer"),
            ("embedding_model_id", "integer"),
            ("embedding_revision", "string"),
            ("parser_version", "string"),
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
        writable=True,
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


def bind_knowledge_vectors(actor, collection, dimensions):
    scope = StorageScope("runtime", actor.tenant_id, actor.user_id, {collection})
    return ElasticsearchVectorStore(
        scope,
        (vector_binding(actor.tenant_id, collection, dimensions),),
        _configured_client,
    )
