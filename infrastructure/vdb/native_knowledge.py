# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public retrieval from the original Elasticsearch document layout."""

import hashlib
import json
import re
from contextlib import closing, contextmanager
from functools import partial
from time import monotonic
from types import SimpleNamespace

from contracts.agentos_knowledge import (
    KnowledgeContentRequest,
    KnowledgeLegacyImageLocator,
)
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
    Comparison,
    Junction,
    OperationContext,
    PageRequest,
    RecordQuery,
    StorageScope,
    VectorCollectionInfo,
    VectorGroup,
    WriteReceipt,
)
from nexent.vector_database.elasticsearch_core import (
    ElasticSearchCore,
    legacy_index_definition,
)
from nexent.vector_database.utils import extract_highlight_terms
from pydantic import ValidationError

from infrastructure.knowledge_vectors import _configured_client, vector_binding
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_jobs import FILES, bind_knowledge_manifest
from infrastructure.rdb.legacy_index_owner import bind_legacy_index_owner
from infrastructure.vdb.vector_schema import vector
from infrastructure.vdb.vector_statistics import _complete, _integer
from infrastructure.vdb.vector_store import ElasticsearchVectorStore

INGEST_GENERATION = "nexent_ingest_generation"
INGEST_IMAGE = "nexent_ingest_image"
IMAGE_PROCESS_SOURCE = "UniversalImageExtractor"
_SEARCH_FILE = "nexent_native_file"
_SEARCH_LEGACY_IMAGE = "nexent_legacy_image_hit"
_PRIVATE_FIELDS = frozenset({"embedding", "multi_embedding", INGEST_GENERATION, INGEST_IMAGE, _SEARCH_FILE, _SEARCH_LEGACY_IMAGE})


def native_file_document_id(file_id, version, generation, position):
    return f"{file_id}-{version}-{generation}-{position}"


def _published_generations(actor, resource, *, engine, context, file_versions=None):
    scope = StorageScope("runtime", resource.resource_tenant_id, actor.user_id, {FILES})
    with closing(bind_knowledge_manifest(scope, resource.knowledge_id, engine)) as records:
        cursor, visible = None, set()
        where = Comparison("visible_generation", "is_null", False)
        if file_versions is not None:
            where = Junction("and", (where, Comparison("file_id", "in", list(file_versions))))
        query = RecordQuery(where=where, fields=("file_id", "visible_generation", "visible_version", "tombstone_version"))
        while True:
            page = records.query(FILES, query, PageRequest(limit=500, cursor=cursor), context=context)
            for row in page.items:
                generation = row["visible_generation"]
                if row["visible_version"] <= row["tombstone_version"] or not re.fullmatch(r"[0-9a-f]{32}", generation):
                    raise Conflict()
                if file_versions is not None and file_versions.get(row["file_id"]) != row["visible_version"]:
                    continue
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


def _generation_filter(generations, *, include_history=True):
    visible = [legacy_document_filter()] if include_history else []
    for index, values in generations.items():
        if values:
            visible.append({"bool": {"filter": [
                {"term": {"_index": index}}, {"terms": {INGEST_GENERATION: sorted(values)}},
            ]}})
    return {"bool": {"should": visible, "minimum_should_match": 1}} if visible else {"match_none": {}}


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
        self.include_history = True
        self.legacy_file_paths = {}
        self.image_index_ids = None

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
        search_query["seq_no_primary_term"] = True
        visible = _generation_filter(self.generations, include_history=self.include_history)
        if self.legacy_file_paths:
            legacy, runtime_field = _scoped_legacy_filter(self.legacy_file_paths, self.owners)
            visible = {"bool": {"should": [visible, legacy], "minimum_should_match": 1}}
            search_query["runtime_mappings"] = {**search_query.get("runtime_mappings", {}), **runtime_field}
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
            source.pop(_SEARCH_FILE, None)
            source.pop(_SEARCH_LEGACY_IMAGE, None)
            if INGEST_GENERATION not in source:
                if not self.include_history:
                    path = source.get("path_or_url")
                    scope = self.legacy_file_paths.get(index, {}).get(path) if isinstance(path, str) else None
                    if scope is None:
                        raise ScopeDenied()
                    source[_SEARCH_FILE] = _legacy_search_file(source, scope)
                source.pop(INGEST_IMAGE, None)
                if source.get("process_source") == IMAGE_PROCESS_SOURCE:
                    attributes = legacy_image_attributes(source)
                    metadata = source.get("metadata")
                    if isinstance(metadata, dict):
                        source["metadata"] = {key: value for key, value in metadata.items() if key != "image_url"}
                    source.pop("image_url", None)
                    source["content"] = json.dumps({"source_file": source.get("filename", ""),
                                                   "position": attributes[1] if attributes else {}})
                    if attributes:
                        if self.image_index_ids is None:
                            self.image_index_ids = self.identities()
                        source[_SEARCH_LEGACY_IMAGE] = {
                            "chunk_key": hit["_id"], "index_uuid": self.image_index_ids[index],
                            "sequence": hit.get("_seq_no"), "primary_term": hit.get("_primary_term"),
                            "position": attributes[1],
                        }
            else:
                source[_SEARCH_FILE] = _search_file(hit["_id"], source[INGEST_GENERATION])
            source.setdefault("id", hit["_id"])
            for field in ("embedding", "multi_embedding", INGEST_GENERATION):
                source.pop(field, None)
            results.append({"score": hit["_score"], "document": source, "index": index,
                            "highlight_terms": ([] if _SEARCH_LEGACY_IMAGE in source
                                                else extract_highlight_terms(hit.get("highlight", {})))})
        return results


def _legacy_search_file(document, scope):
    metadata = document.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ScopeDenied()
    metadata = metadata or {}
    for fields in (document, metadata):
        claim, version = fields.get("file_id"), fields.get("file_version")
        if claim is not None and claim not in (scope.file_id, scope.alias):
            raise ScopeDenied()
        if version is not None and (type(version) is not int or version != scope.file_version):
            raise ScopeDenied()
    if scope.file_version and document.get("file_version", metadata.get("file_version")) != scope.file_version:
        raise ScopeDenied()
    position = document.get("index")
    if position is None:
        position = metadata.get("chunk_index")
    process = document.get("process_source")
    if type(position) is not int or position < 0 or not isinstance(process, str) or not process.strip():
        raise ScopeDenied()
    return {"file_id": scope.file_id, "file_version": scope.file_version, "chunk_index": position}


def _scoped_legacy_filter(paths, owners):
    field = "nexent_authorized_legacy_file"
    scope_filter = {"bool": {"should": [{"bool": {"filter": [
        {"term": {"_index": index}}, {"terms": {"path_or_url": list(scopes)}},
    ]}} for index, scopes in paths.items()], "minimum_should_match": 1}}
    # The source fields do not always have keyword mappings. Filter within ES before ranking.
    script = """
        def source = params._source;
        def path = source['path_or_url'];
        def index = doc['_index'].value;
        def scope = params.files[index];
        if (!(path instanceof String) || scope == null || !scope.containsKey(path)) { emit(false); return; }
        def expected = scope[path];
        def metadata = source['metadata'];
        if (metadata != null && !(metadata instanceof Map)) { emit(false); return; }
        if (metadata == null) { metadata = [:]; }
        def tenant = params.tenants[index];
        for (def owner : [source, metadata]) {
            def fid = owner['file_id'];
            def version = owner['file_version'];
            def taggedTenant = owner['tenant_id'];
            if (taggedTenant != null && !tenant.equals(taggedTenant)
                || fid != null && !fid.equals(expected.id) && !fid.equals(expected.alias)
                || version != null && (!(version instanceof Integer || version instanceof Long)
                || version != expected.version)) { emit(false); return; }
        }
        def version = source.containsKey('file_version') ? source['file_version'] : metadata['file_version'];
        def position = source['index'] == null ? metadata['chunk_index'] : source['index'];
        def process = source['process_source'];
        emit((expected.version == 0 || version != null && version == expected.version)
            && (position instanceof Integer || position instanceof Long) && position >= 0
            && process instanceof String && process.trim().length() > 0);
    """
    files = {index: {path: {"id": scope.file_id, "alias": scope.alias, "version": scope.file_version}
                     for path, scope in scopes.items()} for index, scopes in paths.items()}
    query = {"bool": {"filter": [legacy_document_filter(), scope_filter, {"term": {field: True}}]}}
    return query, {field: {"type": "boolean", "script": {"source": script, "params": {"files": files, "tenants": owners}}}}


def _bind_legacy_search_files(resources, mappings, file_versions, legacy_files):
    entries = {resource.knowledge_id: resource.collection for resource in resources}
    paths = {}
    for scope in legacy_files:
        if scope.knowledge_id not in entries or file_versions.get(scope.file_id) != scope.file_version:
            raise ScopeDenied()
        index = entries[scope.knowledge_id]
        field = mappings[index].get("path_or_url", {})
        limit = field.get("ignore_above", 32766)
        if field.get("type") != "keyword" or field.get("index", True) is not True or type(limit) is not int:
            continue
        for address in scope.addresses:
            if len(address.encode("utf-8")) > limit:
                continue
            previous = paths.setdefault(index, {}).setdefault(address, scope)
            if previous != scope:
                raise Conflict()
    return paths


def _searchable_vector(mapping, dimensions):
    return mapping.get("type") == "dense_vector" and mapping.get("dims") == dimensions and mapping.get("index", True)


def _search_file(identity, generation):
    matched = re.fullmatch(r"([0-9a-f]{32})-(0|[1-9][0-9]*)-([0-9a-f]{32})-(0|[1-9][0-9]*)", identity)
    if matched is None or matched[3] != generation:
        raise Conflict()
    return {"file_id": matched[1], "file_version": int(matched[2]), "chunk_index": int(matched[4])}


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
    source = {key: value for key, value in source.items() if key not in _PRIVATE_FIELDS}
    source.setdefault("id", hit["_id"])
    return hit["_id"], source


@contextmanager
def _native_search_reader(actor, resources, *, context, file_versions=None, legacy_files=()):
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
            versions = {resource.collection: _index_revision(client, resource, context) for resource in resources}
            search = _NativeHybrid(client, {index: tenant for index, tenant in owners.items() if versions[index]}, context)
            if search.owners:
                search.read_mappings()
            mappings = {index: search.mappings.get(index, {}) for index in owners}
            generations = _generation_snapshot(mappings, actor, resources, engine=engine, context=context)
            search.generations = generations
            if file_versions is not None:
                search.include_history = False
                search.generations = {resource.collection: (
                    _published_generations(actor, resource, engine=engine, context=context, file_versions=file_versions)
                    if file_versions and INGEST_GENERATION in mappings[resource.collection] else frozenset()
                ) for resource in resources}
                search.legacy_file_paths = _bind_legacy_search_files(resources, mappings, file_versions, legacy_files)

            def revision_parts(resource):
                parts = [resource.revision, versions[resource.collection], sorted(generations[resource.collection])]
                scoped = search.legacy_file_paths.get(resource.collection, {})
                if scoped:
                    parts.append([[path, scoped[path].model_dump(mode="json")] for path in sorted(scoped)])
                return parts

            revisions = {resource.knowledge_id: hashlib.sha256(json.dumps(
                revision_parts(resource),
                separators=(",", ":")).encode()).hexdigest() for resource in resources}
            yield search, revisions
            if any(_index_revision(client, resource, context) != versions[resource.collection] for resource in resources) or (
                _generation_snapshot(mappings, actor, resources, engine=engine, context=context) != generations
            ):
                raise Conflict()
        for resource in resources:
            require_index_owner(actor, resource, context=context, engine=engine)
    finally:
        close_owned(context, [engine.dispose])


def native_search_revisions(actor, resources, *, context, file_versions=None, legacy_files=()):
    with _native_search_reader(actor, resources, context=context, file_versions=file_versions, legacy_files=legacy_files) as (_, revisions):
        return revisions


def search_native_knowledge(actor, resources, query, query_vector, top_k, weight_accurate, multimodal, *,
                            context, mode="hybrid", file_versions=None, legacy_files=()):
    with _native_search_reader(actor, resources, context=context, file_versions=file_versions, legacy_files=legacy_files) as (search, revisions):
        if not search.owners:
            return [], revisions
        indices = list(search.owners)
        model = SimpleNamespace(model_type="multimodal" if multimodal else "embedding")
        if mode == "accurate":
            hits = search.accurate_search(indices, query, top_k=top_k)
        elif mode == "semantic":
            hits = search.semantic_search(indices, query, embedding_model=model, top_k=top_k,
                                          query_embedding=list(query_vector))
            hits = sorted(hits, key=lambda hit: -hit["score"])[:top_k]
        elif mode == "hybrid":
            hits = search.hybrid_search(indices, query, top_k=top_k, weight_accurate=weight_accurate,
                query_embedding=list(query_vector), embedding_model=model)
        else:
            raise InvalidInput()
        knowledge_ids = {resource.collection: resource.knowledge_id for resource in resources}
        for hit in hits:
            document = hit["document"]
            file = document.pop(_SEARCH_FILE, None)
            image = document.pop(INGEST_IMAGE, None)
            legacy = document.pop(_SEARCH_LEGACY_IMAGE, None)
            if legacy is not None:
                hit["legacy_position"] = legacy.pop("position")
                try:
                    hit["legacy_image"] = KnowledgeLegacyImageLocator(
                        knowledge_id=knowledge_ids[hit["index"]], **legacy)
                except ValidationError as error:
                    raise Conflict() from error
            if file_versions is not None and (
                file is None or file_versions.get(file["file_id"]) != file["file_version"]
            ):
                raise ScopeDenied()
            if file is not None:
                hit["file"] = file
            if image is not None:
                hit["image"] = _native_image(image, knowledge_ids[hit["index"]], document)
                if file is None or any(hit["image"][field] != file[field] for field in ("file_id", "file_version")):
                    raise Conflict()
        return hits, revisions


def legacy_image_attributes(document):
    if INGEST_GENERATION in document or document.get("process_source") != IMAGE_PROCESS_SOURCE:
        return None
    metadata, content = document.get("metadata"), document.get("content")
    url = metadata.get("image_url") if isinstance(metadata, dict) else None
    if not isinstance(url, str) or not 0 < len(url) <= 2048 or not isinstance(content, str) or len(content) > 16384:
        return None
    try:
        payload = json.loads(content)
    except (ValueError, RecursionError):
        return None
    if not isinstance(payload, dict) or payload.get("image_url") != url:
        return None
    position = payload.get("position")
    return url, position if isinstance(position, dict) else {}


def read_native_legacy_image(actor, resource, locator, *, context):
    if locator.knowledge_id != resource.knowledge_id:
        raise ScopeDenied()
    engine = record_engine(context)
    try:
        require_index_owner(actor, resource, context=context, engine=engine)
        with closing(_configured_client(context.remaining())) as client:
            index = resource.collection
            reader = _NativeHybrid(client, {index: resource.resource_tenant_id}, context)
            if reader.identities()[index] != locator.index_uuid:
                raise Conflict()
            hit = ElasticsearchVectorStore._call(client, "get", context, index=index, id=locator.chunk_key,
                                                 source_excludes=["embedding", "multi_embedding"])
            source = hit.get("_source")
            if (hit.get("_index") != index or hit.get("_id") != locator.chunk_key or not isinstance(source, dict)
                or not _owns_source(source, resource.resource_tenant_id)):
                raise ScopeDenied()
            if (hit.get("_seq_no"), hit.get("_primary_term")) != (locator.sequence, locator.primary_term):
                raise Conflict()
            attributes = legacy_image_attributes(source)
            if attributes is None or reader.identities()[index] != locator.index_uuid:
                raise ScopeDenied()
            return attributes[0], source.get("filename")
    finally:
        close_owned(context, [engine.dispose])


def _native_image(image, knowledge_id, document):
    try:
        if document.get("process_source") != IMAGE_PROCESS_SOURCE or not isinstance(image["location"], dict):
            raise ValueError("Invalid native image")
        request = KnowledgeContentRequest(knowledge_id=knowledge_id, file_id=image["file_id"],
                                          file_version=image["file_version"], image_ref=image["image_ref"])
        if request.image_ref is None or request.image_ref.space != "files":
            raise ValueError("Invalid native image reference")
        return {"file_id": request.file_id, "file_version": request.file_version, "image_ref": request.image_ref,
                "location": image["location"]}
    except (KeyError, TypeError, ValueError):
        raise Conflict() from None


def ensure_native_collection(actor, resource, dimensions, *, context):
    """Create or verify an authorized original index without changing an existing schema."""
    index = resource.collection
    engine = record_engine(context)
    try:
        require_index_owner(actor, resource, context=context, engine=engine)
        with closing(_configured_client(context.remaining())) as client:
            reader = _NativeHybrid(client, {index: resource.resource_tenant_id}, context)
            call = ElasticsearchVectorStore._call
            created = False
            try:
                reader.identities()
            except NotFound:
                settings, mappings = legacy_index_definition(dimensions)
                try:
                    result = call(client, "indices.create", context, write=True, index=index, mappings=mappings,
                                  settings=settings, wait_for_active_shards="1")
                except Conflict:
                    # Verify the exact concurrent creation below without issuing another write.
                    pass
                else:
                    if result.get("acknowledged") is not True or result.get("shards_acknowledged") is not True:
                        raise OutcomeUnknown(operation_id=context.operation_id)
                    created = True
            try:
                identities = reader.identities()
                reader.read_mappings()
                fields = reader.mappings[index]
                embedding = fields.get("embedding", {})
                path = fields.get("path_or_url", {})
                if (not _searchable_vector(embedding, dimensions) or embedding.get("similarity", "cosine") != "cosine"
                    or path.get("type") != "keyword" or path.get("index", True) is not True):
                    raise Conflict()
                if reader.identities() != identities:
                    raise Conflict()
                require_index_owner(actor, resource, context=context, engine=engine)
            except (Conflict, NotFound, ScopeDenied, Unavailable) as error:
                if created:
                    raise OutcomeUnknown(operation_id=context.operation_id) from error
                raise
            return VectorCollectionInfo(index, dimensions, "cosine")
    finally:
        close_owned(context, [engine.dispose])


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
        source = {key: value for key, value in source.items() if key not in _PRIVATE_FIELDS}
        if not _owns_source(source, self.scope.tenant_id):
            raise ScopeDenied()
        source[field] = vector(binding, record.vector)
        result = self._call("index", context, write=True, id=record.key.key, op_type="create",
                            document=source, refresh="wait_for")
        if result.get("result") != "created" or result.get("_index") != self.resource.collection:
            raise OutcomeUnknown(operation_id=context.operation_id)
        return WriteReceipt(context.operation_id, True)


class NativeFileGenerationWriter(NativeDocumentCreation):
    """Write bounded file batches to the original index before publishing the manifest."""

    def __init__(self, client, actor, resource, dimensions, grant, *, authorize):
        super().__init__(client, actor, resource, dimensions)
        self.grant, self.authorize = grant, authorize

    def _mapping(self, context):
        self.authorize(context=context)
        return super()._mapping(context)

    def ensure_collection(self, collection, *, context):
        self._ensure_mapping(collection, image=False, context=context)

    def _ensure_mapping(self, collection, *, image, context):
        if collection != self.resource.collection:
            raise ScopeDenied()
        mapping = self._mapping(context)
        embedding = mapping.get("embedding", {})
        if not _searchable_vector(embedding, self.dimensions) or embedding.get("similarity", "cosine") != "cosine":
            raise Conflict()
        marker = mapping.get(INGEST_GENERATION)
        additions = {}
        if marker is None:
            additions[INGEST_GENERATION] = {"type": "keyword"}
        elif marker.get("type") != "keyword" or marker.get("index", True) is not True:
            raise Conflict()
        if image:
            image_vector, image_context = mapping.get("multi_embedding"), mapping.get(INGEST_IMAGE)
            if image_vector is None:
                additions["multi_embedding"] = {"type": "dense_vector", "dims": self.dimensions,
                                                "index": True, "similarity": "cosine"}
            elif not _searchable_vector(image_vector, self.dimensions):
                raise Conflict()
            if image_context is None:
                additions[INGEST_IMAGE] = {"type": "object", "enabled": False}
            elif image_context.get("type") != "object" or image_context.get("enabled") is not False:
                raise Conflict()
        if additions:
            result = self._call("indices.put_mapping", context, write=True, properties=additions)
            if result.get("acknowledged") is not True:
                raise OutcomeUnknown(operation_id=context.operation_id)

    def upsert(self, records, *, context):
        if not isinstance(records, tuple) or len(records) > 1000:
            raise InvalidInput()
        if not records:
            return ()
        binding = vector_binding(self.scope.tenant_id, self.resource.collection, self.dimensions)
        operations, ids, images = [], set(), False
        for record in records:
            if record.key.collection != self.resource.collection or any(
                record.payload.get(field) != getattr(self.grant, field) for field in ("knowledge_id", "file_id", "file_version")
            ):
                raise ScopeDenied()
            kind = record.payload.get("media_kind")
            if kind not in {"text", "image"}:
                raise InvalidInput()
            generation = record.generation.value if record.generation is not None else None
            location = record.payload["location"]
            position = record.payload.get("chunk_index")
            if (not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{32}", generation)
                or type(position) is not int or position < 0 or location.get("path_or_url") != self.grant.source.key):
                raise InvalidInput()
            identity = native_file_document_id(self.grant.file_id, self.grant.file_version, generation, position)
            if identity in ids:
                raise InvalidInput()
            ids.add(identity)
            document = {field: location[field] for field in ("file_size", "create_time", "language", "title", "author", "date")
                        if location.get(field) is not None}
            document.update(id=identity, path_or_url=self.grant.source.key, filename=self.grant.filename,
                            source_type="minio", index=position)
            if kind == "image":
                self._add_image(document, location, position, vector(binding, record.vector))
                images = True
            else:
                document.update(content=record.payload["content"], process_source="Unstructured",
                                embedding=vector(binding, record.vector))
            document[INGEST_GENERATION] = generation
            operations += [{"index": {"_index": self.resource.collection, "_id": identity}}, document]
        self._ensure_mapping(self.resource.collection, image=images, context=context)
        return ElasticsearchVectorStore._bulk(self.client, operations, context, len(records),
                                              expected_index=self.resource.collection)

    def _add_image(self, document, location, position, embedding):
        try:
            request = KnowledgeContentRequest(knowledge_id=self.grant.knowledge_id, file_id=self.grant.file_id,
                file_version=self.grant.file_version, image_ref=location.get("image_ref"))
        except ValidationError:
            raise InvalidInput() from None
        if request.image_ref is None or request.image_ref.space != "files":
            raise InvalidInput()
        placement = {name: location[name] for name in ("page_number", "sheet_name", "coordinates") if name in location}
        document[INGEST_IMAGE] = {"file_id": request.file_id, "file_version": request.file_version,
                                 "image_ref": request.image_ref.model_dump(), "location": {**placement, "chunk_index": position}}
        document.update(process_source=IMAGE_PROCESS_SOURCE, multi_embedding=embedding,
                        content=json.dumps({"source_file": self.grant.filename, "position": placement}, ensure_ascii=False))

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
