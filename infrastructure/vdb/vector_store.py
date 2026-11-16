# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Elasticsearch vector storage with explicit tenant grants and no inference or retries."""

import asyncio
import hashlib
import json
import math
from contextlib import contextmanager

from elastic_transport import TransportError
from elasticsearch import ApiError
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    PartialFailure,
    ScopeDenied,
    StorageError,
    Unavailable,
)
from nexent.storage.models import (
    CapabilitySet,
    DeleteReceipt,
    Revision,
    SearchHit,
    SearchQuery,
    VectorCollectionInfo,
    VectorKey,
    VectorRecord,
    WriteOutcome,
    WriteReceipt,
)
from nexent.vector_database.utils import extract_highlight_terms

from infrastructure.vdb.vector_schema import (
    VectorBinding,
    matches_mapping,
    payload,
    predicate,
    vector,
)


class ElasticsearchVectorStore:
    capabilities = CapabilitySet(
        frozenset(
            {
                "vector.collection.ensure",
                "vector.collection.describe",
                "vector.upsert",
                "vector.get",
                "vector.search.dense",
                "vector.search.text",
                "vector.search.weighted_text",
                "vector.delete",
                "vector.count",
            }
        )
    )

    def __init__(self, scope, bindings: tuple[VectorBinding, ...], client_factory):
        if (
            not isinstance(bindings, (tuple, list))
            or not bindings
            or any(not isinstance(binding, VectorBinding) for binding in bindings)
            or not callable(client_factory)
        ):
            raise InvalidInput()
        self._scope = scope
        self._bindings = {binding.collection: binding for binding in bindings}
        if (
            scope.system
            or scope.resource_prefix
            or scope.service_role not in {"runtime", "management"}
            or len(self._bindings) != len(bindings)
        ):
            raise ScopeDenied()
        self._factory = client_factory
        if any(binding.dimensions is None for binding in bindings):
            self.capabilities = CapabilitySet(frozenset({"vector.count", "vector.delete"}))
        self._closed = False

    @property
    def scope(self):
        return self._scope

    def _binding(self, collection, *, write=False, maintenance=False):
        if (
            self._closed
            or collection not in self.scope.namespaces
            or collection not in self._bindings
        ):
            raise ScopeDenied()
        if write and not self._bindings[collection].writable:
            raise ScopeDenied()
        if self._bindings[collection].dimensions is None and not maintenance:
            raise CapabilityUnsupported()
        return self._bindings[collection]

    def _key(self, collection, key):
        if not isinstance(key, str) or not key or len(key) > 1024:
            raise InvalidInput()
        return hashlib.sha256(
            json.dumps(
                [self.scope.tenant_id, collection, key], separators=(",", ":")
            ).encode()
        ).hexdigest()

    @contextmanager
    def _client(self, context):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise CapabilityUnsupported()
        client = self._factory(context.remaining())
        try:
            yield client
        finally:
            client.close()

    @staticmethod
    def _call(client, method, context, *, write=False, **kwargs):
        remaining = context.remaining()
        try:
            target = client.options(
                request_timeout=min(5, remaining), max_retries=0, retry_on_timeout=False
            )
            for name in method.split("."):
                target = getattr(target, name)
            result = target(**kwargs)
        except ApiError as error:
            body = error.body if isinstance(error.body, dict) else {}
            details = body.get("error", {})
            if (
                isinstance(details, dict)
                and details.get("type") == "resource_already_exists_exception"
            ):
                raise Conflict(operation_id=context.operation_id) from None
            kind = {
                404: NotFound,
                409: Conflict,
                401: ScopeDenied,
                403: ScopeDenied,
                400: InvalidInput,
            }.get(error.status_code, OutcomeUnknown if write else Unavailable)
            raise kind(operation_id=context.operation_id) from None
        except (TransportError, OSError):
            raise (OutcomeUnknown if write else Unavailable)(
                operation_id=context.operation_id
            ) from None
        try:
            context.remaining()
        except StorageError:
            if write:
                raise OutcomeUnknown(operation_id=context.operation_id) from None
            raise
        return result

    def describe_collection(self, collection, *, context):
        binding = self._binding(collection)
        with self._client(context) as client:
            result = self._call(
                client, "indices.get_mapping", context, index=binding.index
            )
        mapping = result.get(binding.index, {}).get("mappings", {})
        if not matches_mapping(binding.mapping(), mapping):
            raise Conflict(operation_id=context.operation_id)
        return VectorCollectionInfo(collection, binding.dimensions, binding.metric)

    def ensure_collection(self, collection, *, context):
        binding = self._binding(collection, write=True)
        with self._client(context) as client:
            exists = self._call(client, "indices.exists", context, index=binding.index)
            if not exists:
                self._call(
                    client,
                    "indices.create",
                    context,
                    write=True,
                    index=binding.index,
                    mappings=binding.mapping(),
                )
        return self.describe_collection(collection, context=context)

    def _filter(self, binding, where):
        terms = [
            {"term": {"_si_tenant": self.scope.tenant_id}},
            {"term": {"_si_collection": binding.collection}},
        ]
        if where is not None:
            terms.append(predicate(binding, where))
        return {"bool": {"filter": terms}}

    def _bulk(self, client, operations, context, count, *, delete=False):
        result = self._call(
            client,
            "bulk",
            context,
            write=True,
            operations=operations,
            refresh="wait_for",
        )
        items = result.get("items", [])
        if len(items) != count:
            raise OutcomeUnknown(operation_id=context.operation_id)
        receipts = []
        for index, item in enumerate(items):
            data = item.get("delete" if delete else "index", {})
            status = data.get("status", 0)
            if type(status) is not int or not 100 <= status <= 599:
                raise OutcomeUnknown(operation_id=context.operation_id)
            success = 200 <= status < 300 or delete and status == 404
            outcome = WriteOutcome.CONFIRMED if success else WriteOutcome.FAILED
            op = context.operation_id + ":" + str(index)
            receipts.append(
                DeleteReceipt(op, status != 404 and success, outcome)
                if delete
                else WriteReceipt(op, success, outcome=outcome)
            )
        if any(row.outcome != WriteOutcome.CONFIRMED for row in receipts):
            raise PartialFailure(
                results=tuple(receipts), operation_id=context.operation_id
            )
        return tuple(receipts)

    def upsert(self, records, *, context):
        if not isinstance(records, tuple) or len(records) > 1000:
            raise InvalidInput()
        operations, keys = [], set()
        for row in records:
            if not isinstance(row, VectorRecord) or not isinstance(row.key, VectorKey):
                raise InvalidInput()
            binding = self._binding(row.key.collection, write=True)
            key = self._key(binding.collection, row.key.key)
            if (binding.index, key) in keys:
                raise InvalidInput()
            keys.add((binding.index, key))
            if row.generation is not None and not isinstance(row.generation, Revision):
                raise InvalidInput()
            data = {
                "_si_tenant": self.scope.tenant_id,
                "_si_key": row.key.key,
                "_si_collection": binding.collection,
                "embedding": vector(binding, row.vector),
                "payload": payload(binding, row.payload),
            }
            if row.generation is not None:
                data["_si_generation"] = row.generation.value
            operations.extend([{"index": {"_index": binding.index, "_id": key}}, data])
        if not records:
            return ()
        with self._client(context) as client:
            return self._bulk(client, operations, context, len(records))

    def _decode(self, binding, source, *, partial=False):
        if not isinstance(source, dict):
            raise Unavailable()
        if (
            source.get("_si_tenant") != self.scope.tenant_id
            or source.get("_si_collection") != binding.collection
        ):
            raise ScopeDenied()
        key = source.get("_si_key")
        self._key(binding.collection, key)
        generation = source.get("_si_generation")
        return (
            VectorKey(binding.collection, key),
            payload(binding, source.get("payload", {}), partial=partial),
            (Revision(generation) if generation is not None else None),
        )

    def get(self, key, *, context):
        if not isinstance(key, VectorKey):
            raise InvalidInput()
        binding = self._binding(key.collection)
        with self._client(context) as client:
            try:
                result = self._call(
                    client,
                    "get",
                    context,
                    index=binding.index,
                    id=self._key(key.collection, key.key),
                    source_includes=[
                        "_si_tenant",
                        "_si_collection",
                        "_si_key",
                        "_si_generation",
                        "embedding",
                    ]
                    + ["payload." + field for field in binding.schema],
                )
            except NotFound:
                return None
        source = result.get("_source", {})
        actual, data, generation = self._decode(binding, source)
        if actual != key:
            raise ScopeDenied()
        return VectorRecord(
            actual, vector(binding, source.get("embedding")), data, generation
        )

    def search(self, collection, query, *, context):
        binding = self._binding(collection)
        if not isinstance(query, SearchQuery):
            raise InvalidInput()
        if (
            type(query.limit) is not int
            or not 1 <= query.limit <= 1000
            or not set(query.fields) <= set(binding.schema)
        ):
            raise InvalidInput()
        filters = self._filter(binding, query.where)
        options = {"index": binding.index, "size": query.limit}
        if query.mode == "dense" and query.text is None:
            options["knn"] = {
                "field": "embedding",
                "query_vector": vector(binding, query.vector),
                "k": query.limit,
                "num_candidates": max(100, query.limit),
                "filter": filters,
            }
            score_kind = "elasticsearch.cosine"
        elif (
            query.mode in {"text", "weighted_text"}
            and query.vector is None
            and isinstance(query.text, str)
            and query.text
        ):
            clause = {"match": {"payload." + binding.text_field: query.text}}
            score_kind = "elasticsearch.bm25"
            if query.mode == "weighted_text":
                from infrastructure.vdb.lexical import weighted_query

                clause, options["highlight"] = weighted_query(binding, query.text)
                score_kind = "elasticsearch.weighted_text"
            options["query"] = {
                "bool": {
                    "filter": [filters],
                    "must": [clause],
                }
            }
        else:
            raise CapabilityUnsupported()
        fields = query.fields or tuple(binding.schema)
        options["source"] = [
            "_si_tenant",
            "_si_collection",
            "_si_key",
            "_si_generation",
        ] + ["payload." + name for name in fields]
        with self._client(context) as client:
            result = self._call(client, "search", context, **options)
        if result.get("timed_out") or result.get("_shards", {}).get("failed", 0):
            raise Unavailable(operation_id=context.operation_id)
        hits = []
        for hit in result.get("hits", {}).get("hits", []):
            key, data, generation = self._decode(
                binding, hit.get("_source", {}), partial=True
            )
            score = hit.get("_score")
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
            ):
                raise Unavailable()
            terms = tuple(extract_highlight_terms(hit.get("highlight", {}))) if query.mode == "weighted_text" else ()
            hits.append(SearchHit(key, float(score), score_kind, data, generation, highlights=terms))
        return tuple(hits)

    def count(self, collection, where, *, context):
        binding = self._binding(collection, maintenance=True)
        query = self._filter(binding, where)
        with self._client(context) as client:
            result = self._call(
                client, "count", context, index=binding.index, query=query
            )
        if (
            result.get("_shards", {}).get("failed", 0)
            or type(result.get("count")) is not int
            or result["count"] < 0
        ):
            raise Unavailable()
        return result["count"]

    def delete(self, collection, where, *, context):
        from infrastructure.vdb.vector_delete import delete_vectors

        binding = self._binding(collection, write=True, maintenance=True)
        if where is None:
            raise InvalidInput()
        return delete_vectors(
            self, binding, self._filter(binding, where), context=context
        )

    def close(self):
        self._closed = True
