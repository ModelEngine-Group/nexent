# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Delete only the confirmed native generations in an authorized file cleanup."""

from contextlib import closing
from types import SimpleNamespace

from nexent.storage.errors import Conflict, NotFound, ScopeDenied, Unavailable

from infrastructure.knowledge_vectors import _configured_client
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.vdb.native_knowledge import (
    INGEST_GENERATION,
    _NativeHybrid,
    _owns_source,
    legacy_document_filter,
    native_file_document_id,
    require_index_owner,
)
from infrastructure.vdb.vector_delete import delete_index_documents
from infrastructure.vdb.vector_statistics import _complete
from infrastructure.vdb.vector_store import ElasticsearchVectorStore


def _native_target(hit, grant, tenant_id, generations):
    source = hit.get("_source", {})
    generation = source.get(INGEST_GENERATION)
    version = generations.get(generation) if isinstance(generation, str) else None
    position = source.get("index")
    if (hit.get("_index") != grant.collection or version is None or not _owns_source(source, tenant_id)
        or type(position) is not int or position < 0):
        raise ScopeDenied()
    identity = native_file_document_id(grant.file_id, version, generation, position)
    if source.get("id") != identity or hit.get("_id") != identity:
        raise ScopeDenied()


def delete_native_file_generations(actor, grant, generations, *, context):
    if grant.action != "delete" or any(type(version) is not int or not 0 <= version <= grant.file_version
                                      for version in generations.values()):
        raise ScopeDenied()
    if not generations and not grant.legacy_sources:
        return 0
    resource = SimpleNamespace(knowledge_id=grant.knowledge_id, collection=grant.collection,
                               resource_tenant_id=actor.tenant_id)
    engine = record_engine(context)
    try:
        require_index_owner(actor, resource, engine=engine, context=context)
        with closing(_configured_client(context.remaining())) as client:
            native = _delete(client, grant, actor.tenant_id, generations, context=context) if generations else 0
            historical = _delete_legacy(client, grant, actor.tenant_id, context=context) if grant.legacy_sources else 0
            return native + historical
    finally:
        close_owned(context, [engine.dispose])


def _delete(client, grant, tenant_id, generations, *, context):
    reader = _NativeHybrid(client, {grant.collection: tenant_id}, context)
    try:
        identities = reader.identities()
    except NotFound:
        return 0
    reader.read_mappings()
    marker = reader.mappings[grant.collection].get(INGEST_GENERATION)
    if marker is None:
        return 0
    if marker.get("type") != "keyword" or marker.get("index", True) is not True:
        raise Conflict()

    def validate(hit):
        _native_target(hit, grant, tenant_id, generations)

    query = {"terms": {INGEST_GENERATION: sorted(generations)}}
    return _remove_matching(client, grant, reader, identities, query,
                            (INGEST_GENERATION, "id", "index", "tenant_id", "metadata.tenant_id"), validate,
                            context=context)


def _legacy_target(hit, grant, tenant_id):
    source = hit.get("_source", {})
    if (hit.get("_index") != grant.collection or INGEST_GENERATION in source or not _owns_source(source, tenant_id)
        or source.get("path_or_url") not in grant.legacy_sources):
        raise ScopeDenied()
    metadata = source.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise Conflict()
    for fields in (source, metadata or {}):
        file_id, version = fields.get("file_id"), fields.get("file_version")
        if file_id is not None and file_id != grant.file_id:
            raise ScopeDenied()
        if version is not None and (type(version) is not int or not 0 <= version <= grant.file_version):
            raise Conflict()


def _delete_legacy(client, grant, tenant_id, *, context):
    reader = _NativeHybrid(client, {grant.collection: tenant_id}, context)
    try:
        identities = reader.identities()
    except NotFound:
        return 0
    reader.read_mappings()
    field = reader.mappings[grant.collection].get("path_or_url")
    if field is None:
        if _count(client, grant.collection, {"match_all": {}}, context) == 0:
            return 0
        raise Conflict()
    limit = field.get("ignore_above", 32766)
    if (field.get("type") != "keyword" or field.get("index", True) is not True or type(limit) is not int
        or any(len(address.encode("utf-8")) > limit for address in grant.legacy_sources)):
        raise Conflict()

    def validate(hit):
        _legacy_target(hit, grant, tenant_id)

    query = {"bool": {"filter": [
        legacy_document_filter(), {"terms": {"path_or_url": grant.legacy_sources}},
    ]}}
    return _remove_matching(client, grant, reader, identities, query, (
        INGEST_GENERATION, "path_or_url", "tenant_id", "file_id", "file_version",
        "metadata.tenant_id", "metadata.file_id", "metadata.file_version",
    ), validate, context=context)


def _remove_matching(client, grant, reader, identities, query, fields, validate, *, context):
    receipts = delete_index_documents(
        ElasticsearchVectorStore, client, grant.collection, query, fields, validate, context=context, exact_index=True,
    )
    if _count(client, grant.collection, query, context) != 0 or reader.identities() != identities:
        raise Conflict()
    return sum(receipt.deleted for receipt in receipts)


def _count(client, collection, query, context):
    remaining = ElasticsearchVectorStore._call(client, "count", context, index=collection, query=query,
                                               allow_no_indices=False, ignore_unavailable=False)
    _complete(remaining, context)
    count = remaining.get("count")
    if type(count) is not int or count < 0:
        raise Unavailable(operation_id=context.operation_id)
    return count
