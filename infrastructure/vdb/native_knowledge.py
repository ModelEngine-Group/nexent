# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public retrieval from the original Elasticsearch document layout."""

import hashlib
import json
import re
from contextlib import closing, contextmanager
from functools import partial
from time import monotonic
from types import SimpleNamespace

from contracts.knowledge_chunk_projection import public_chunk_source
from contracts.knowledge_maintenance import LEGACY_INDEX_OWNER
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    Comparison,
    OperationContext,
    PageRequest,
    RecordQuery,
    StorageScope,
    VectorCollectionInfo,
    VectorGroup,
    WriteReceipt,
)
from nexent.vector_database.elasticsearch_core import ElasticSearchCore
from nexent.vector_database.utils import extract_highlight_terms

from infrastructure.knowledge_vectors import _configured_client, vector_binding
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_jobs import FILES, bind_knowledge_manifest
from infrastructure.rdb.legacy_index_owner import bind_legacy_index_owner
from infrastructure.vdb.vector_schema import vector
from infrastructure.vdb.vector_statistics import _complete, _integer
from infrastructure.vdb.vector_store import ElasticsearchVectorStore

INGEST_GENERATION = "nexent_ingest_generation"


def _published_generations(actor, resource, *, engine, context):
    scope = StorageScope("runtime", resource.resource_tenant_id, actor.user_id, {FILES})
    with closing(bind_knowledge_manifest(scope, resource.knowledge_id, engine)) as records:
        cursor, visible = None, set()
        query = RecordQuery(where=Comparison("visible_generation", "is_null", False),
                            fields=("visible_generation", "visible_version", "tombstone_version"))
        while True:
            page = records.query(FILES, query, PageRequest(limit=500, cursor=cursor), context=context)
            for row in page.items:
                generation = row["visible_generation"]
                if row["visible_version"] <= row["tombstone_version"] or not re.fullmatch(r"[0-9a-f]{32}", generation):
                    raise Conflict()
                visible.add(generation)
            cursor = page.next_cursor
            if cursor is None:
                return frozenset(visible)


def _generation_snapshot(mappings, actor, resources, *, engine, context):
    result = {}
    for resource in resources:
        marker = mappings[resource.collection].get(INGEST_GENERATION)
        if marker is None:
            result[resource.collection] = frozenset()
            continue
        if marker.get("type") != "keyword" or marker.get("index", True) is not True:
            raise Conflict()
        result[resource.collection] = _published_generations(actor, resource, engine=engine, context=context)
    return result


def legacy_document_filter():
    return {"bool": {"must_not": {"exists": {"field": INGEST_GENERATION}}}}


def _generation_filter(generations):
    visible = [legacy_document_filter()]
    for index, values in generations.items():
        if values:
            visible.append({"bool": {"filter": [
                {"term": {"_index": index}}, {"terms": {INGEST_GENERATION: sorted(values)}},
            ]}})
    return {"bool": {"should": visible, "minimum_should_match": 1}}


def _visible_generation(source, generations):
    if INGEST_GENERATION not in source:
        return True
    generation = source[INGEST_GENERATION]
    return isinstance(generation, str) and generation in generations


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
        self.generations = {}

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
        search_query = dict(search_query)
        visible = _generation_filter(self.generations)
        if knn := search_query.get("knn"):
            targets = tuple(name for name in targets if _searchable_vector(
                self.mappings[name].get(knn["field"], {}), len(knn["query_vector"]),
            ))
            if not targets:
                return []
            search_query["knn"] = {**knn, "filter": [filter_ for filter_ in (knn.get("filter"), visible) if filter_]}
        else:
            search_query["query"] = {"bool": {"must": search_query.get("query", {"match_all": {}}), "filter": visible}}
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
            if not _visible_generation(source, self.generations.get(index, ())):
                raise Conflict()
            source.setdefault("id", hit["_id"])
            for field in ("embedding", "multi_embedding", INGEST_GENERATION):
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
            reader.read_mappings()
            generations = _generation_snapshot(reader.mappings, actor, (resource,), engine=engine, context=context)
            runtime_mappings, query = _tenant_filter(tenant)
            result = ElasticsearchVectorStore._call(
                client, "search", context, index=index, size=0,
                query={"bool": {"filter": [query, _generation_filter(generations)]}},
                allow_partial_search_results=False, allow_no_indices=False, ignore_unavailable=False,
                runtime_mappings=runtime_mappings,
                aggregations={"sources": {
                    "terms": {"field": "path_or_url", "size": limit, "order": [{"_count": "desc"}, {"_key": "asc"}]},
                    "aggs": {"sample": {"top_hits": {"size": 1,
                        "_source": [*fields.values(), "tenant_id", "metadata.tenant_id", INGEST_GENERATION]}}},
                }},
            )
            _complete(result, context, search=True)
            groups = _native_groups(result, index, tenant, fields, limit, generations[index], context)
            if reader.identities() != identity or (
                _generation_snapshot(reader.mappings, actor, (resource,), engine=engine, context=context) != generations
            ):
                raise Conflict()
        require_index_owner(actor, resource, context=context, engine=engine)
    finally:
        close_owned(context, [engine.dispose])
    return True, groups


def _native_groups(result, index, tenant, fields, limit, generations, context):
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
            if not _visible_generation(source, generations):
                raise Conflict()
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
            reader = _NativeHybrid(client, {resource.collection: resource.resource_tenant_id}, context)
            if index_revision:
                reader.read_mappings()
            else:
                reader.mappings = {resource.collection: {}}
            generations = _generation_snapshot(reader.mappings, actor, (resource,), engine=engine, context=context)
            visible = generations[resource.collection]
            revision = hashlib.sha256(json.dumps([resource.revision, index_revision, sorted(visible)]).encode()).hexdigest()
            if expected_revision is not None and expected_revision != revision:
                raise Conflict()
            total, rows = (_native_window(client, resource, path, offset, limit, context, generations=visible)
                           if index_revision else (0, []))
            if _index_revision(client, resource, context) != index_revision or (
                _generation_snapshot(reader.mappings, actor, (resource,), engine=engine, context=context) != generations
            ):
                raise Conflict()
        require_index_owner(actor, resource, context=context, engine=engine)
    finally:
        close_owned(context, [engine.dispose])
    return revision, total, rows


def _native_window(client, resource, path, offset, limit, context, *, generations=frozenset()):
    call = ElasticsearchVectorStore._call
    opened = call(client, "open_point_in_time", context, index=resource.collection, keep_alive="15s",
                  preference="native-knowledge-chunks", allow_partial_search_results=False)
    pit = opened.get("id")
    if not isinstance(pit, str) or not pit:
        raise Unavailable()
    runtime_mappings, owned = _tenant_filter(resource.resource_tenant_id)
    filters = [owned, _generation_filter({resource.collection: generations})]
    if path:
        filters.append({"term": {"path_or_url": path}})
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
            rows.extend(_native_chunk(hit, resource, generations) for hit in hits[max(0, offset - position):])
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


def _native_chunk(hit, resource, generations):
    source = hit["_source"]
    if hit["_index"] != resource.collection or not _owns_source(source, resource.resource_tenant_id):
        raise ScopeDenied()
    if not _visible_generation(source, generations):
        raise Conflict()
    source = {key: value for key, value in source.items() if key not in {"embedding", "multi_embedding", INGEST_GENERATION}}
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
            search.generations = _generation_snapshot(search.mappings, actor, resources, engine=engine, context=context)
            hits = search.hybrid_search(list(owners), query, top_k=top_k, weight_accurate=weight_accurate,
                query_embedding=list(query_vector),
                embedding_model=SimpleNamespace(model_type="multimodal" if multimodal else "embedding"))
            if search.identities() != identities or (
                _generation_snapshot(search.mappings, actor, resources, engine=engine, context=context) != search.generations
            ):
                raise Conflict()
        for resource in resources:
            require_index_owner(actor, resource, context=context, engine=engine)
    finally:
        close_owned(context, [engine.dispose])
    revisions = {resource.knowledge_id: hashlib.sha256(json.dumps(
        [resource.revision, identities[resource.collection], sorted(search.generations[resource.collection])],
        separators=(",", ":")).encode()).hexdigest()
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


@contextmanager
def native_generation_ports(actor, grant, dimensions, *, context):
    if grant.action != "execute":
        raise ScopeDenied()
    resource = SimpleNamespace(knowledge_id=grant.knowledge_id, collection=grant.collection,
                               resource_tenant_id=actor.tenant_id)
    engine = record_engine(context)
    try:
        with closing(_configured_client(context.remaining())) as client:
            authorize = partial(require_index_owner, actor, resource, engine=engine)
            yield NativeFileGenerationWriter(client, actor, resource, dimensions, grant, authorize=authorize)
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
        source = {key: value for key, value in source.items() if key not in {"embedding", "multi_embedding", INGEST_GENERATION}}
        if not _owns_source(source, self.scope.tenant_id):
            raise ScopeDenied()
        source[field] = vector(binding, record.vector)
        result = self._call("index", context, write=True, id=record.key.key, op_type="create",
                            document=source, refresh="wait_for")
        if result.get("result") != "created" or result.get("_index") != self.resource.collection:
            raise OutcomeUnknown(operation_id=context.operation_id)
        return WriteReceipt(context.operation_id, True)


class NativeFileGenerationWriter(NativeDocumentCreation):
    """Write bounded text batches to the original index before publishing the manifest."""

    def __init__(self, client, actor, resource, dimensions, grant, *, authorize):
        super().__init__(client, actor, resource, dimensions)
        self.grant, self.authorize = grant, authorize

    def _mapping(self, context):
        self.authorize(context=context)
        return super()._mapping(context)

    def ensure_collection(self, collection, *, context):
        if collection != self.resource.collection:
            raise ScopeDenied()
        mapping = self._mapping(context)
        embedding = mapping.get("embedding", {})
        if not _searchable_vector(embedding, self.dimensions) or embedding.get("similarity", "cosine") != "cosine":
            raise Conflict()
        marker = mapping.get(INGEST_GENERATION)
        if marker is None:
            result = self._call("indices.put_mapping", context, write=True, properties={INGEST_GENERATION: {"type": "keyword"}})
            if result.get("acknowledged") is not True:
                raise OutcomeUnknown(operation_id=context.operation_id)
        elif marker.get("type") != "keyword" or marker.get("index", True) is not True:
            raise Conflict()

    def upsert(self, records, *, context):
        if not isinstance(records, tuple) or len(records) > 1000:
            raise InvalidInput()
        if not records:
            return ()
        self.ensure_collection(self.resource.collection, context=context)
        binding = vector_binding(self.scope.tenant_id, self.resource.collection, self.dimensions)
        operations, ids = [], set()
        for record in records:
            if record.key.collection != self.resource.collection or any(
                record.payload.get(field) != getattr(self.grant, field) for field in ("knowledge_id", "file_id", "file_version")
            ):
                raise ScopeDenied()
            if record.payload.get("media_kind") != "text":
                raise CapabilityUnsupported()
            generation = record.generation.value if record.generation is not None else None
            location = record.payload["location"]
            position = record.payload.get("chunk_index")
            if (not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{32}", generation)
                or type(position) is not int or position < 0 or location.get("path_or_url") != self.grant.source.key):
                raise InvalidInput()
            identity = f"{self.grant.file_id}-{self.grant.file_version}-{generation}-{position}"
            if identity in ids:
                raise InvalidInput()
            ids.add(identity)
            document = {field: location[field] for field in ("file_size", "create_time", "language", "title", "author", "date")
                        if location.get(field) is not None}
            document.update(id=identity, path_or_url=self.grant.source.key, filename=self.grant.filename,
                            content=record.payload["content"], source_type="minio", index=position,
                            process_source=location.get("process_source") or "Unstructured",
                            embedding=vector(binding, record.vector))
            document[INGEST_GENERATION] = generation
            operations += [{"index": {"_index": self.resource.collection, "_id": identity}}, document]
        return ElasticsearchVectorStore._bulk(self.client, operations, context, len(records),
                                              expected_index=self.resource.collection)

    def describe_collection(self, collection, *, context):
        if collection != self.resource.collection:
            raise ScopeDenied()
        mapping = self._mapping(context)
        embedding = mapping.get("embedding", {})
        marker = mapping.get(INGEST_GENERATION, {})
        if (not _searchable_vector(embedding, self.dimensions) or embedding.get("similarity", "cosine") != "cosine"
            or marker.get("type") != "keyword" or marker.get("index", True) is not True):
            raise Conflict()
        return VectorCollectionInfo(collection, self.dimensions, "cosine")
