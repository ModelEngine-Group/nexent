# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded original-index sample of complete text documents."""

import hashlib
import json
import random
from contextlib import contextmanager
from time import monotonic

from contracts.agentos_knowledge import (
    KnowledgeFileReference,
    KnowledgeSampleChunk,
    KnowledgeSampleDocument,
)
from nexent.storage.errors import Conflict, ScopeDenied, Unavailable
from nexent.storage.models import OperationContext

from infrastructure.vdb.native_knowledge import (
    IMAGE_PROCESS_SOURCE,
    INGEST_GENERATION,
    _generation_filter,
    _native_search_reader,
    _owns_source,
    _search_file,
    _tenant_filter,
    _visible_generation,
)
from infrastructure.vdb.vector_statistics import SCALAR_SOURCE, _complete
from infrastructure.vdb.vector_store import ElasticsearchVectorStore


@contextmanager
def _snapshot(reader, resource, context):
    call = ElasticsearchVectorStore._call
    client, index = reader.client, resource.collection
    opened = call(client, "open_point_in_time", context, index=index, keep_alive="1m",
                  allow_partial_search_results=False)
    pit = opened.get("id")
    if not isinstance(pit, str) or not pit:
        raise Unavailable()
    runtime, owned = _tenant_filter(resource.resource_tenant_id)
    runtime["nexent_sample_path"] = {"type": "keyword", "script": {"source": SCALAR_SOURCE,
                                              "params": {"paths": [["path_or_url"]]}}}
    runtime["nexent_sample_processor"] = {"type": "keyword", "script": {"source": SCALAR_SOURCE,
                                                   "params": {"paths": [["process_source"]]}}}
    visible = _generation_filter(reader.generations)

    def scan(fields, selected=None):
        nonlocal pit
        filters = [owned, visible]
        if selected is not None:
            filters.append(selected)
        query = {"bool": {"filter": filters,
                          "must_not": {"term": {"nexent_sample_processor": IMAGE_PROCESS_SOURCE}}}}
        after = None
        while True:
            options = {"search_after": after} if after is not None else {}
            result = call(client, "search", context, pit={"id": pit, "keep_alive": "1m"}, query=query,
                runtime_mappings=runtime, sort=["_shard_doc"], size=500, source=fields,
                allow_partial_search_results=False, **options)
            pit = result.get("pit_id", pit)
            _complete(result, context, search=True)
            hits = result["hits"]["hits"]
            if not hits:
                return
            position = hits[-1].get("sort")
            if not isinstance(position, list) or position == after:
                raise Unavailable()
            for hit in hits:
                doc = hit.get("_source")
                if (hit.get("_index") != index or not isinstance(doc, dict)
                    or not _owns_source(doc, resource.resource_tenant_id)
                    or not _visible_generation(doc, reader.generations.get(index, ()))
                    or doc.get("process_source") == IMAGE_PROCESS_SOURCE):
                    raise ScopeDenied()
                yield hit["_id"], doc
            after = position
    try:
        yield scan
    finally:
        cleanup = OperationContext(context.operation_id, monotonic() + 2)
        call(client, "close_point_in_time", cleanup, id=pit)


def _identity(physical, doc):
    if INGEST_GENERATION in doc:
        identity = _search_file(physical, doc[INGEST_GENERATION])
        return ("generation", doc[INGEST_GENERATION]), identity
    address = doc.get("path_or_url")
    return (("path", address) if isinstance(address, str) and address else ("id", physical)), None


def _selected_filter(selected):
    choices = []
    for kind, field in (("generation", INGEST_GENERATION), ("path", "nexent_sample_path"), ("id", None)):
        values = [value for item, value in selected if item == kind]
        if values:
            choices.append({"terms": {field: values}} if field else {"ids": {"values": values}})
    return {"bool": {"should": choices, "minimum_should_match": 1}} if choices else {"match_none": {}}


def _samples(scan, resource, dimensions, limit):
    fields = [INGEST_GENERATION, "path_or_url", "tenant_id", "metadata.tenant_id", "process_source"]
    group_keys, seen = [], set()
    for physical, doc in scan(fields):
        identity, _ = _identity(physical, doc)
        if identity in seen:
            continue
        seen.add(identity)
        if len(group_keys) < limit:
            group_keys.append(identity)
        else:
            pos = random.randrange(len(seen))
            if pos < limit:
                group_keys[pos] = identity
    if not group_keys:
        return []

    groups = {key: [] for key in group_keys}
    for physical, doc in scan([*fields, "content", "filename", "embedding"], _selected_filter(group_keys)):
        identity, parsed = _identity(physical, doc)
        if identity not in groups:
            raise Conflict()
        embedding = doc.get("embedding")
        if embedding is not None and (not isinstance(embedding, list) or len(embedding) != dimensions):
            raise Conflict()
        groups[identity].append((parsed, doc.get("filename", ""), KnowledgeSampleChunk(
            chunk_id=physical, content=doc.get("content", ""), embedding=embedding,
            chunk_index=parsed["chunk_index"] if parsed else None)))
    samples = []
    for key, values in groups.items():
        if not values:
            raise Conflict()
        identity, filename, _ = values[0]
        ref = KnowledgeFileReference(knowledge_id=resource.knowledge_id, file_id=identity["file_id"],
                                     file_version=identity["file_version"]) if identity is not None else None
        if ref is not None and any((item["file_id"], item["file_version"]) != (ref.file_id, ref.file_version)
                                   for item, _, _ in values):
            raise Conflict()
        if ref is None:
            label = "path" if key[0] == "path" else "chunk"
            standalone_key = hashlib.sha256(json.dumps([resource.knowledge_id, label, key[1]],
                                                        separators=(",", ":")).encode()).hexdigest()
        else:
            standalone_key = None
        chunks = sorted((chunk for _, _, chunk in values), key=lambda row: (row.chunk_index, row.chunk_id)
                        if ref else (row.chunk_id,))
        samples.append(KnowledgeSampleDocument(file_ref=ref, standalone_key=standalone_key,
            path_or_url=key[1] if key[0] == "path" else None, filename=filename, chunks=chunks))
    return samples


def sample_native_knowledge(actor, resource, dimensions, limit, *, context):
    with _native_search_reader(actor, (resource,), context=context) as (reader, revisions):
        documents = []
        if reader.owners:
            with _snapshot(reader, resource, context) as scan:
                documents = _samples(scan, resource, dimensions, limit)
        return revisions[resource.knowledge_id], documents
