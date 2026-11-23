# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public retrieval from the original Elasticsearch document layout."""

import hashlib
import json
import re
from contextlib import closing, contextmanager
from time import monotonic
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
from nexent.storage.models import (
    OperationContext,
    StorageScope,
    VectorGroup,
    WriteReceipt,
)
from nexent.vector_database.elasticsearch_core import ElasticSearchCore
from nexent.vector_database.utils import extract_highlight_terms

from infrastructure.knowledge_vectors import _configured_client, vector_binding
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.legacy_index_owner import bind_legacy_index_owner
from infrastructure.vdb.vector_schema import vector
from infrastructure.vdb.vector_statistics import _complete, _integer
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
            if index not in targets or not _owns_source(source, tenant):
                raise ScopeDenied()
            source.setdefault("id", hit["_id"])
            for field in ("embedding", "multi_embedding"):
                source.pop(field, None)
            results.append({"score": hit["_score"], "document": source, "index": index,
                            "highlight_terms": extract_highlight_terms(hit.get("highlight", {}))})
        return results


def _searchable_vector(mapping, dimensions):
    return mapping.get("type") == "dense_vector" and mapping.get("dims") == dimensions and mapping.get("index", True)


def _tenant_filter(tenant_id):
    # Inspect _source because legacy indexes do not guarantee tenant keyword fields.
    field = "nexent_read_owned"
    source = """
        def tenant = params._source['tenant_id'];
        def metadata = params._source['metadata'];
        def nested = metadata instanceof Map ? metadata['tenant_id'] : null;
        emit((tenant == null || params.tenant.equals(tenant))
            && (nested == null || params.tenant.equals(nested)));
    """
    mappings = {field: {"type": "boolean", "script": {"source": source, "params": {"tenant": tenant_id}}}}
    return mappings, {"term": {field: True}}


def native_source_groups(actor, resource, limit, *, context):
    """Read original source groups and bounded samples without reading chunk bodies."""
    index, tenant = resource.collection, resource.resource_tenant_id
    fields = {"path": "path_or_url", "filename": "filename", "size": "file_size", "created": "create_time"}
    engine = record_engine(context)
    try:
        require_index_owner(actor, resource, context=context, engine=engine)
        with closing(_configured_client(context.remaining())) as client:
            reader = _NativeHybrid(client, {index: tenant}, context)
            try:
                identity = reader.identities()
            except NotFound:
                return False, ()
            runtime_mappings, query = _tenant_filter(tenant)
            result = ElasticsearchVectorStore._call(
                client, "search", context, index=index, size=0, query=query,
                allow_partial_search_results=False, allow_no_indices=False, ignore_unavailable=False,
                runtime_mappings=runtime_mappings,
                aggregations={"sources": {
                    "terms": {"field": "path_or_url", "size": limit, "order": [{"_count": "desc"}, {"_key": "asc"}]},
                    "aggs": {"sample": {"top_hits": {"size": 1, "_source": [*fields.values(), "tenant_id", "metadata.tenant_id"]}}},
                }},
            )
            _complete(result, context, search=True)
            groups = _native_groups(result, index, tenant, fields, limit, context)
            if reader.identities() != identity:
                raise Conflict()
        require_index_owner(actor, resource, context=context, engine=engine)
    finally:
        close_owned(context, [engine.dispose])
    return True, groups


def _native_groups(result, index, tenant, fields, limit, context):
    try:
        buckets = result["aggregations"]["sources"]["buckets"]
        if not isinstance(buckets, list) or len(buckets) > limit:
            raise ValueError("Invalid source groups")
        groups, seen = [], set()
        for bucket in buckets:
            key, count = bucket["key"], _integer(bucket["doc_count"])
            hits = bucket["sample"]["hits"]["hits"]
            if not isinstance(key, str) or key in seen or not count or len(hits) != 1:
                raise ValueError("Invalid source group")
            source = hits[0]["_source"]
            if hits[0]["_index"] != index or not _owns_source(source, tenant):
                raise ScopeDenied()
            sample = {name: source[field] for name, field in fields.items() if field in source}
            sample["path"] = key
            groups.append(VectorGroup(index, key, count, sample))
            seen.add(key)
        return tuple(groups)
    except (KeyError, TypeError, ValueError):
        raise Unavailable(operation_id=context.operation_id) from None


def _owns_source(source, tenant):
    metadata = source.get("metadata")
    return source.get("tenant_id") in (None, tenant) and (
        not isinstance(metadata, dict) or metadata.get("tenant_id") in (None, tenant)
    )


def _index_revision(client, resource, context):
    try:
        result = ElasticsearchVectorStore._call(client, "indices.stats", context, index=resource.collection,
                                                 metric="docs", level="shards")
    except NotFound:
        return None
    _complete(result, context)
    indices = result.get("indices", {})
    if set(indices) != {resource.collection}:
        raise ScopeDenied()
    try:
        index = indices[resource.collection]
        primary = {shard: next(copy for copy in copies if copy["routing"]["primary"])
                   for shard, copies in index["shards"].items()}
        if not primary or not index["uuid"]:
            raise ValueError("Missing index state")
        versions = [(shard, state["routing"]["node"], state["seq_no"]["max_seq_no"],
                     state["docs"]["count"], state["docs"]["deleted"])
                    for shard, state in sorted(primary.items())]
    except (KeyError, StopIteration, TypeError, ValueError):
        raise Unavailable(operation_id=context.operation_id) from None
    return hashlib.sha256(json.dumps([resource.revision, index["uuid"], versions]).encode()).hexdigest()


def native_chunk_window(actor, resource, path, offset, limit, expected_revision, *, context):
    engine = record_engine(context)
    try:
        require_index_owner(actor, resource, context=context, engine=engine)
        with closing(_configured_client(context.remaining())) as client:
            index_revision = _index_revision(client, resource, context)
            revision = index_revision or hashlib.sha256(f"{resource.revision}:missing".encode()).hexdigest()
            if expected_revision is not None and expected_revision != revision:
                raise Conflict()
            total, rows = _native_window(client, resource, path, offset, limit, context) if index_revision else (0, [])
            if _index_revision(client, resource, context) != index_revision:
                raise Conflict()
        require_index_owner(actor, resource, context=context, engine=engine)
    finally:
        close_owned(context, [engine.dispose])
    return revision, total, rows


def _native_window(client, resource, path, offset, limit, context):
    call = ElasticsearchVectorStore._call
    opened = call(client, "open_point_in_time", context, index=resource.collection, keep_alive="15s",
                  preference="native-knowledge-chunks", allow_partial_search_results=False)
    pit = opened.get("id")
    if not isinstance(pit, str) or not pit:
        raise Unavailable()
    runtime_mappings, owned = _tenant_filter(resource.resource_tenant_id)
    filters = [owned] + ([{"term": {"path_or_url": path}}] if path else [])
    options = {"query": {"bool": {"filter": filters}}, "runtime_mappings": runtime_mappings,
               "track_total_hits": True, "sort": ["_seq_no", "_shard_doc"],
               "source_excludes": ["embedding", "multi_embedding"]}
    rows, total, position = [], None, 0
    try:
        while position < offset + limit:
            size = min(1000, offset + limit - position)
            result = call(client, "search", context, pit={"id": pit, "keep_alive": "15s"},
                          size=size, source=position + size > offset, allow_partial_search_results=False, **options)
            pit = result.get("pit_id") or pit
            _complete(result, context, search=True)
            total, hits = _chunk_hits(result, size)
            if len(hits) != min(size, max(0, total - position)):
                raise Unavailable(operation_id=context.operation_id)
            if not hits:
                break
            rows.extend(_native_chunk(hit, resource) for hit in hits[max(0, offset - position):])
            position += len(hits)
            if offset >= total or position >= total:
                break
            options["search_after"] = hits[-1]["sort"]
    finally:
        cleanup = OperationContext(context.operation_id, monotonic() + 1)
        call(client, "close_point_in_time", cleanup, id=pit)
    return total, rows


def _chunk_hits(result, size):
    try:
        hits, total = result["hits"]["hits"], result["hits"]["total"]
        if total["relation"] != "eq" or not isinstance(hits, list) or len(hits) > size:
            raise ValueError("Invalid chunk window")
        if hits and (not isinstance(hits[-1]["sort"], list) or len(hits[-1]["sort"]) != 2):
            raise ValueError("Missing chunk sort position")
        return _integer(total["value"]), hits
    except (KeyError, TypeError, ValueError):
        raise Unavailable() from None


def _native_chunk(hit, resource):
    source = hit["_source"]
    if hit["_index"] != resource.collection or not _owns_source(source, resource.resource_tenant_id):
        raise ScopeDenied()
    source = {key: value for key, value in source.items() if key not in {"embedding", "multi_embedding"}}
    source.setdefault("id", hit["_id"])
    return hit["_id"], source


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
        if not _owns_source(source, self.scope.tenant_id):
            raise ScopeDenied()
        source[field] = vector(binding, record.vector)
        result = self._call("index", context, write=True, id=record.key.key, op_type="create",
                            document=source, refresh="wait_for")
        if result.get("result") != "created" or result.get("_index") != self.resource.collection:
            raise OutcomeUnknown(operation_id=context.operation_id)
        return WriteReceipt(context.operation_id, True)
