# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exact conditional edits to flat documents in the original Elasticsearch index."""

import hashlib
import json
from contextlib import closing, contextmanager

from contracts.knowledge_chunk_projection import (
    PUBLIC_CHUNK_SOURCE_KEY,
    public_chunk_source,
)
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    DeleteReceipt,
    Revision,
    StorageScope,
    VectorKey,
    VectorRecord,
    WriteReceipt,
)

from infrastructure.knowledge_vectors import _configured_client, vector_binding
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.vdb.native_knowledge import (
    _PRIVATE_FIELDS,
    IMAGE_PROCESS_SOURCE,
    INGEST_GENERATION,
    _generation_filter,
    _NativeHybrid,
    _owns_source,
    _published_generations,
    _search_file,
    _searchable_vector,
    require_index_owner,
)
from infrastructure.vdb.vector_schema import vector
from infrastructure.vdb.vector_statistics import _complete
from infrastructure.vdb.vector_store import ElasticsearchVectorStore


@contextmanager
def native_mutation_port(actor, grant, *, context, storage_revision=None):
    engine = record_engine(context)
    try:
        require_index_owner(actor, grant, engine=engine, context=context)
        with closing(_configured_client(context.remaining())) as client:
            yield NativeChunkMutation(client, actor, grant, storage_revision, engine)
    finally:
        close_owned(context, [engine.dispose])


class NativeChunkMutation:
    def __init__(self, client, actor, grant, storage_revision, engine):
        self.client, self.actor, self.grant = client, actor, grant
        self.storage_revision, self.engine = storage_revision, engine
        self.scope = StorageScope("runtime", grant.resource_tenant_id, actor.user_id, {grant.collection})

    def _index(self, collection, context):
        if collection != self.grant.collection:
            raise ScopeDenied()
        reader = _NativeHybrid(self.client, {collection: self.scope.tenant_id}, context)
        return reader.identities()[collection]

    def _call(self, method, context, **options):
        return ElasticsearchVectorStore._call(self.client, method, context, index=self.grant.collection, **options)

    def _target(self, result, index_uuid):
        source, physical = result.get("_source"), result.get("_id")
        if (result.get("_index") != self.grant.collection or not isinstance(source, dict)
            or not _owns_source(source, self.scope.tenant_id)):
            raise ScopeDenied()
        seq, term = result.get("_seq_no"), result.get("_primary_term")
        if not isinstance(physical, str) or type(seq) is not int or seq < 0 or type(term) is not int or term < 1:
            raise Unavailable()
        revision = hashlib.sha256(json.dumps([index_uuid, physical, seq, term]).encode()).hexdigest()
        if self.storage_revision is not None and revision != self.storage_revision:
            raise Conflict()
        generation = source.get(INGEST_GENERATION)
        if INGEST_GENERATION in source and not isinstance(generation, str):
            raise Conflict()
        file = _search_file(physical, generation) if generation is not None else {}
        public = {name: value for name, value in source.items() if name not in _PRIVATE_FIELDS and name != "content"}
        public.setdefault("id", physical)
        row = VectorRecord(VectorKey(self.grant.collection, physical), (), {
            "knowledge_id": self.grant.knowledge_id, **file, "content": source.get("content"),
            "filename": source.get("filename"), "location": {PUBLIC_CHUNK_SOURCE_KEY: public},
        }, Revision(generation) if generation is not None else None)
        return row, revision, {"if_seq_no": seq, "if_primary_term": term}, source

    def _get(self, key, context, *, resolve_public_id=False):
        try:
            index_uuid = self._index(key.collection, context)
        except NotFound:
            return None
        try:
            result = self._call("get", context, id=key.key, source_excludes=["embedding", "multi_embedding"])
            if result.get("_id") != key.key:
                raise ScopeDenied()
        except NotFound:
            if not resolve_public_id:
                return None
            reader = _NativeHybrid(self.client, {key.collection: self.scope.tenant_id}, context)
            reader.read_mappings()
            generations = (_published_generations(self.actor, self.grant, engine=self.engine, context=context)
                           if INGEST_GENERATION in reader.mappings[key.collection] else frozenset())
            reply = self._call("search", context, size=2, seq_no_primary_term=True,
                query={"bool": {"filter": [{"term": {"id": key.key}}, _generation_filter({key.collection: generations})]}},
                source_excludes=["embedding", "multi_embedding"], allow_partial_search_results=False)
            _complete(reply, context, search=True)
            hits = reply["hits"]["hits"]
            if not hits:
                return None
            if len(hits) != 1:
                raise Conflict()
            result = hits[0]
        if self._index(key.collection, context) != index_uuid:
            raise Conflict()
        return self._target(result, index_uuid)

    def find(self, key, *, resolve_public_id, context):
        target = self._get(key, context, resolve_public_id=resolve_public_id)
        return target[:2] if target is not None else (None, None)

    def get(self, key, *, include_vector, context):
        return self.find(key, resolve_public_id=False, context=context)[0]

    def ensure_collection(self, collection, *, context):
        self._index(collection, context)

    def _write_target(self, key, expected_generation, context):
        if self.storage_revision is None:
            raise InvalidInput()
        target = self._get(key, context)
        if target is None:
            raise NotFound()
        row, _, cas, source = target
        if row.generation != expected_generation:
            raise Conflict()
        return cas, source

    def _update(self, key, fields, expected_generation, context, *, replacement=None):
        cas, current = self._write_target(key, expected_generation, context)
        document = public_chunk_source(fields.get("content", current.get("content")), fields.get("location", {}))
        if document is None:
            document = {name: fields[name] for name in ("content", "filename") if name in fields}
        patch = {name: value for name, value in document.items() if name not in _PRIVATE_FIELDS}
        if not _owns_source(patch, self.scope.tenant_id):
            raise ScopeDenied()
        if INGEST_GENERATION in current and any(
            name in patch and patch[name] != current.get(name) for name in ("id", "index", "path_or_url", "source_type", "process_source")
        ):
            raise InvalidInput()
        if replacement is not None:
            field = "multi_embedding" if current.get("process_source") == IMAGE_PROCESS_SOURCE else "embedding"
            patch[field] = self._vector(key.collection, field, replacement, context)
        result = self._call("update", context, write=True, id=key.key, doc=patch, refresh="wait_for", **cas)
        if result.get("_index") != key.collection or result.get("result") not in {"updated", "noop"}:
            raise OutcomeUnknown(operation_id=context.operation_id)
        return WriteReceipt(context.operation_id, True)

    def patch_payload(self, key, patch, *, expected_generation, context):
        return self._update(key, patch.set_values, expected_generation, context)

    def put(self, record, *, expected_generation, context):
        if record.payload.get("knowledge_id") != self.grant.knowledge_id:
            raise ScopeDenied()
        if self.storage_revision is not None:
            return self._update(record.key, record.payload, expected_generation, context, replacement=record.vector or None)
        if expected_generation is not None or record.payload.get("file_id") is not None:
            raise Conflict()
        self.ensure_collection(record.key.collection, context=context)
        document = public_chunk_source(record.payload["content"], record.payload["location"])
        if document is None:
            raise InvalidInput()
        source = {name: value for name, value in document.items() if name not in _PRIVATE_FIELDS}
        if not _owns_source(source, self.scope.tenant_id):
            raise ScopeDenied()
        if record.vector:
            field = "multi_embedding" if record.payload.get("media_kind") == "image" else "embedding"
            source[field] = self._vector(record.key.collection, field, record.vector, context)
        result = self._call("index", context, write=True, id=record.key.key, document=source,
                            op_type="create", refresh="wait_for")
        if result.get("_index") != record.key.collection or result.get("result") != "created":
            raise OutcomeUnknown(operation_id=context.operation_id)
        return WriteReceipt(context.operation_id, True)

    def _vector(self, collection, field, values, context):
        mapping = self._call("indices.get_mapping", context)
        if set(mapping) != {collection}:
            raise ScopeDenied()
        embedding = mapping[collection]["mappings"].get("properties", {}).get(field, {})
        if not _searchable_vector(embedding, len(values)):
            raise Conflict()
        return vector(vector_binding(self.scope.tenant_id, collection, len(values)), values)

    def delete_key(self, key, *, expected_generation, context):
        cas, _ = self._write_target(key, expected_generation, context)
        result = self._call("delete", context, write=True, id=key.key, refresh="wait_for", **cas)
        if result.get("_index") != key.collection or result.get("result") != "deleted":
            raise OutcomeUnknown(operation_id=context.operation_id)
        return DeleteReceipt(context.operation_id, True)
