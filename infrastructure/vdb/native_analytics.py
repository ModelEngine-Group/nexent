# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read metadata from the original ES index with published-generation visibility."""

from contextlib import contextmanager

from contracts.knowledge_collections import KnowledgeVectorMedia
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    StorageScope,
    VectorCollectionInfo,
    VectorCollectionStatistics,
)

from infrastructure.vdb.native_knowledge import (
    IMAGE_PROCESS_SOURCE,
    _generation_filter,
    _native_search_reader,
    _tenant_filter,
)
from infrastructure.vdb.vector_statistics import (
    SCALAR_SOURCE,
    _complete,
    _integer,
    _summaries,
)
from infrastructure.vdb.vector_store import ElasticsearchVectorStore


@contextmanager
def native_collection_analytics(actor, resource, *, context):
    with _native_search_reader(actor, (resource,), context=context) as (reader, _):
        yield NativeCollectionAnalytics(reader, actor, resource)


_SUMMARY_FIELDS = {"source": "path_or_url", "processor": "process_source", "model": "embedding_model_name"}


class NativeCollectionAnalytics:
    def __init__(self, reader, actor, resource):
        self.reader, self.index = reader, resource.collection
        self.scope = StorageScope("runtime", resource.resource_tenant_id, actor.user_id, {self.index})

    def collection_exists(self, collection, *, context):
        context.remaining()
        if collection != self.index:
            raise ScopeDenied()
        return self.index in self.reader.owners

    def describe_collection(self, collection, *, context):
        if not self.collection_exists(collection, context=context):
            raise NotFound()
        embedding = self.reader.mappings[self.index].get("embedding")
        if embedding is None:
            return VectorCollectionInfo(collection, None, "cosine")
        dimensions = embedding.get("dims")
        if (type(dimensions) is not int or dimensions < 1 or embedding.get("type") != "dense_vector"
            or embedding.get("similarity", "cosine") != "cosine"):
            raise Conflict()
        return VectorCollectionInfo(collection, dimensions, "cosine")

    def _metric_search(self, runtime, aggregations, context):
        ownership, owned = _tenant_filter(self.scope.tenant_id)
        result = ElasticsearchVectorStore._call(self.reader.client, "search", context, index=self.index, size=0,
            track_total_hits=True, runtime_mappings={**runtime, **ownership},
            query={"bool": {"filter": [owned, _generation_filter(self.reader.generations)]}},
            aggregations=aggregations, allow_partial_search_results=False, ignore_unavailable=False)
        _complete(result, context, search=True)
        return result

    def statistics(self, collection, fields=(), *, context):
        if not self.collection_exists(collection, context=context):
            raise NotFound()
        names = [field.name for field in fields]
        if len(names) != len(set(names)) or any(name not in _SUMMARY_FIELDS for name in names):
            raise InvalidInput()
        runtime, aggregations = {}, {}
        for index, name in enumerate(names):
            field = "nexent_native_stat_" + name
            runtime[field] = {"type": "keyword", "script": {"source": SCALAR_SOURCE,
                "params": {"paths": [[_SUMMARY_FIELDS[name]]]}}}
            aggregations[f"s{index}"] = {"cardinality": {"field": field}}
            aggregations[f"t{index}"] = {"terms": {"field": field, "size": 10,
                                                           "order": [{"_count": "desc"}, {"_key": "asc"}]}}
        report = self._metric_search(runtime, aggregations, context)
        call, client = ElasticsearchVectorStore._call, self.reader.client
        stats = call(client, "indices.stats", context, index=self.index)
        _complete(stats, context)
        settings = call(client, "indices.get_settings", context, index=self.index)
        if set(stats["indices"]) != {self.index} or set(settings) != {self.index}:
            raise ScopeDenied()
        try:
            primary = stats["indices"][self.index]["primaries"]
            created = settings[self.index]["settings"]["index"]["creation_date"]
            total = report["hits"]["total"]
            if total["relation"] != "eq" or not isinstance(created, str) or not created.isascii() or not created.isdecimal():
                raise ValueError("Invalid original collection statistics")
            return VectorCollectionStatistics(collection, _integer(total["value"]), _integer(primary["store"]["size_in_bytes"]),
                int(created), _integer(primary["search"]["query_total"]), _integer(primary["request_cache"]["hit_count"]),
                _summaries(report, fields))
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise Unavailable(operation_id=context.operation_id) from error

    def vector_media(self, collection, *, context):
        if not self.collection_exists(collection, context=context):
            raise NotFound()
        field = "nexent_native_media"
        runtime = {field: {"type": "keyword", "script": {"source": SCALAR_SOURCE,
            "params": {"paths": [["process_source"]]}}}}
        marker = {"term": {field: IMAGE_PROCESS_SOURCE}}
        embedding, alternate = ({"exists": {"field": name}} for name in ("embedding", "multi_embedding"))
        result = self._metric_search(runtime, {
            "total": {"filter": {"bool": {"should": [embedding, alternate], "minimum_should_match": 1}}},
            "text": {"filter": {"bool": {"filter": embedding, "must_not": [marker, alternate]}}},
            "image": {"filter": {"bool": {"filter": [marker, alternate], "must_not": embedding}}},
        }, context)
        try:
            counts = result["aggregations"]
            total, text, image = (_integer(counts[name]["doc_count"]) for name in ("total", "text", "image"))
            if text + image > total:
                raise Conflict()
            return KnowledgeVectorMedia(text=text, image=image, unclassified=total - text - image)
        except (KeyError, TypeError, ValueError) as error:
            raise Unavailable(operation_id=context.operation_id) from error
