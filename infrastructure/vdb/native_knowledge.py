# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public retrieval from the original Elasticsearch document layout."""

import hashlib
import json
import re
from contextlib import closing, contextmanager
from types import SimpleNamespace

from contracts.knowledge_chunk_projection import public_chunk_source
from contracts.knowledge_maintenance import LEGACY_INDEX_OWNER
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import StorageScope, WriteReceipt
from nexent.vector_database.elasticsearch_core import ElasticSearchCore
from nexent.vector_database.utils import extract_highlight_terms

from infrastructure.knowledge_vectors import _configured_client, vector_binding
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.legacy_index_owner import bind_legacy_index_owner
from infrastructure.vdb.vector_schema import vector
from infrastructure.vdb.vector_store import ElasticsearchVectorStore


def require_index_owner(actor, resource, *, context, engine):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", resource.collection):
        raise ScopeDenied()
    principal = SimpleNamespace(user_id=actor.user_id, tenant_id=resource.resource_tenant_id)
    with closing(bind_legacy_index_owner(principal, resource.knowledge_id, resource.collection, engine)) as store:
        row = store.get(LEGACY_INDEX_OWNER, resource.collection, context=context)
    if row is None or row["owner_count"] != 1 or row["selected_owner_count"] != 1:
        raise ScopeDenied()


class _NativeHybrid(ElasticSearchCore):
    def __init__(self, client, owners, context):
        super().__init__(host=None, api_key=None, client=client)
        self.owners, self.context = owners, context
        self.mappings = {}

    def identities(self):
        settings = ElasticsearchVectorStore._call(
            self.client, "indices.get_settings", self.context,
            index=list(self.owners), name="index.uuid", allow_no_indices=False, ignore_unavailable=False,
        )
        if set(settings) != set(self.owners):
            raise ScopeDenied()
        identities = {name: entry.get("settings", {}).get("index", {}).get("uuid") for name, entry in settings.items()}
        if any(not isinstance(value, str) or not value for value in identities.values()):
            raise Unavailable()
        return identities

    def read_mappings(self):
        mappings = ElasticsearchVectorStore._call(
            self.client, "indices.get_mapping", self.context,
            index=list(self.owners), allow_no_indices=False, ignore_unavailable=False,
        )
        if set(mappings) != set(self.owners):
            raise ScopeDenied()
        self.mappings = {name: entry["mappings"].get("properties", {}) for name, entry in mappings.items()}

    def exec_query(self, index_pattern, search_query):
        # The SDK builds a multi-index query from the authorized exact names.
        if index_pattern != ",".join(self.owners):
            raise ScopeDenied()
        targets = tuple(self.owners)
        if knn := search_query.get("knn"):
            targets = tuple(name for name in targets if _searchable_vector(
                self.mappings[name].get(knn["field"], {}), len(knn["query_vector"]),
            ))
            if not targets:
                return []
        response = ElasticsearchVectorStore._call(
            self.client, "search", self.context, index=",".join(targets), body=search_query,
            allow_partial_search_results=False, allow_no_indices=False, ignore_unavailable=False,
        )
        if response.get("timed_out") or response.get("_shards", {}).get("failed", 0):
            raise Unavailable(operation_id=self.context.operation_id)
        results = []
        for hit in response["hits"]["hits"]:
            index, source = hit["_index"], dict(hit["_source"])
            tenant = self.owners.get(index)
            metadata = source.get("metadata")
            if index not in targets or source.get("tenant_id") not in (None, tenant) or (
                isinstance(metadata, dict) and metadata.get("tenant_id") not in (None, tenant)
            ):
                raise ScopeDenied()
            source.setdefault("id", hit["_id"])
            for field in ("embedding", "multi_embedding"):
                source.pop(field, None)
            results.append({"score": hit["_score"], "document": source, "index": index,
                            "highlight_terms": extract_highlight_terms(hit.get("highlight", {}))})
        return results


def _searchable_vector(mapping, dimensions):
    return mapping.get("type") == "dense_vector" and mapping.get("dims") == dimensions and mapping.get("index", True)


def search_native_knowledge(actor, resources, query, query_vector, top_k, weight_accurate, multimodal, *, context):
    owners = {resource.collection: resource.resource_tenant_id for resource in resources}
    if len(owners) != len(resources) or not owners or any(
        not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", index) for index in owners
    ):
        raise ScopeDenied()
    engine = record_engine(context)
    try:
        for resource in resources:
            require_index_owner(actor, resource, context=context, engine=engine)
        with closing(_configured_client(context.remaining())) as client:
            search = _NativeHybrid(client, owners, context)
            identities = search.identities()
            search.read_mappings()
            hits = search.hybrid_search(list(owners), query, top_k=top_k, weight_accurate=weight_accurate,
                query_embedding=list(query_vector),
                embedding_model=SimpleNamespace(model_type="multimodal" if multimodal else "embedding"))
            if search.identities() != identities:
                raise Conflict()
        for resource in resources:
            require_index_owner(actor, resource, context=context, engine=engine)
    finally:
        close_owned(context, [engine.dispose])
    revisions = {resource.knowledge_id: hashlib.sha256(json.dumps(
        [resource.revision, identities[resource.collection]], separators=(",", ":")).encode()).hexdigest()
        for resource in resources}
    return hits, revisions


@contextmanager
def native_document_creation_ports(actor, resource, dimensions, *, context):
    engine = record_engine(context)
    try:
        require_index_owner(actor, resource, context=context, engine=engine)
        with closing(_configured_client(context.remaining())) as client:
            yield NativeDocumentCreation(client, actor, resource, dimensions)
    finally:
        close_owned(context, [engine.dispose])


class NativeDocumentCreation:
    """Create standalone records without changing an existing index or mapping."""

    def __init__(self, client, actor, resource, dimensions):
        self.client, self.resource, self.dimensions = client, resource, dimensions
        self.scope = StorageScope("runtime", resource.resource_tenant_id, actor.user_id, {resource.collection})

    def _call(self, method, context, **options):
        return ElasticsearchVectorStore._call(self.client, method, context, index=self.resource.collection, **options)

    def _mapping(self, context):
        mapping = self._call("indices.get_mapping", context)
        if set(mapping) != {self.resource.collection}:
            raise ScopeDenied()
        return mapping[self.resource.collection]["mappings"].get("properties", {})

    def ensure_collection(self, collection, *, context):
        if collection != self.resource.collection:
            raise ScopeDenied()
        self._mapping(context)

    def get(self, key, *, include_vector, context):
        self.ensure_collection(key.collection, context=context)
        try:
            self._call("get", context, id=key.key, source=False)
        except NotFound:
            return
        # The append executor issues new random IDs. Never adopt an existing document.
        raise Conflict()

    def put(self, record, *, expected_generation, context):
        if record.key.collection != self.resource.collection or record.payload.get("knowledge_id") != self.resource.knowledge_id:
            raise ScopeDenied()
        if expected_generation is not None or record.generation is None or record.payload.get("file_id") is not None:
            raise Conflict()
        content = record.payload["content"]
        source = public_chunk_source(content, record.payload["location"])
        if source is None:
            raise InvalidInput()
        field = "multi_embedding" if record.payload.get("media_kind") == "image" else "embedding"
        mapping = self._mapping(context)
        vector_mapping = mapping.get(field, {})
        if not _searchable_vector(vector_mapping, self.dimensions):
            raise Conflict()
        binding = vector_binding(self.scope.tenant_id, self.resource.collection, self.dimensions)
        source = {key: value for key, value in source.items() if key not in {"embedding", "multi_embedding"}}
        metadata = source.get("metadata")
        if source.get("tenant_id") not in (None, self.scope.tenant_id) or (
            isinstance(metadata, dict) and metadata.get("tenant_id") not in (None, self.scope.tenant_id)
        ):
            raise ScopeDenied()
        source[field] = vector(binding, record.vector)
        result = self._call("index", context, write=True, id=record.key.key, op_type="create",
                            document=source, refresh="wait_for")
        if result.get("result") != "created" or result.get("_index") != self.resource.collection:
            raise OutcomeUnknown(operation_id=context.operation_id)
        return WriteReceipt(context.operation_id, True)
