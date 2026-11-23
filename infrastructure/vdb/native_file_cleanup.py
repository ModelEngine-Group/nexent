# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Delete authorized native generations and exact historical sources."""

from contextlib import closing
from types import SimpleNamespace

from nexent.storage.errors import (
    Conflict,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
    StorageError,
    Unavailable,
)

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
    return _remove_matching(client, grant.collection, reader, identities, query,
                            (INGEST_GENERATION, "id", "index", "tenant_id", "metadata.tenant_id"), validate,
                            context=context)


def _legacy_target(hit, collection, tenant_id, addresses, *, file_id=None, file_version=None):
    source = hit.get("_source", {})
    if (hit.get("_index") != collection or INGEST_GENERATION in source or not _owns_source(source, tenant_id)
        or source.get("path_or_url") not in addresses):
        raise ScopeDenied()
    metadata = source.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise Conflict()
    for fields in (source, metadata or {}):
        claimed_id, version = fields.get("file_id"), fields.get("file_version")
        if claimed_id is not None and claimed_id != file_id:
            raise ScopeDenied()
        if version is not None and (file_version is None or type(version) is not int or not 0 <= version <= file_version):
            raise Conflict()


def delete_untracked_native_source(actor, resource, address, *, context):
    """Apply an exact source deletion after Management proves there is no file ledger."""
    if not isinstance(address, str) or not 0 < len(address) <= 2048:
        raise ScopeDenied()
    engine = record_engine(context)
    try:
        require_index_owner(actor, resource, engine=engine, context=context)
        with closing(_configured_client(context.remaining())) as client:
            return _delete_legacy_sources(client, resource.collection, resource.resource_tenant_id,
                                          [address], context=context)
    finally:
        close_owned(context, [engine.dispose])


def _delete_legacy(client, grant, tenant_id, *, context):
    return _delete_legacy_sources(client, grant.collection, tenant_id, grant.legacy_sources,
                                  file_id=grant.file_id, file_version=grant.file_version, context=context)


def _delete_legacy_sources(client, collection, tenant_id, addresses, *, context, file_id=None, file_version=None):
    reader = _NativeHybrid(client, {collection: tenant_id}, context)
    try:
        identities = reader.identities()
    except NotFound:
        return 0
    reader.read_mappings()
    field = reader.mappings[collection].get("path_or_url")
    if field is None:
        if _count(client, collection, {"match_all": {}}, context) == 0:
            return 0
        raise Conflict()
    limit = field.get("ignore_above", 32766)
    if (field.get("type") != "keyword" or field.get("index", True) is not True or type(limit) is not int
        or any(len(address.encode("utf-8")) > limit for address in addresses)):
        raise Conflict()

    def validate(hit):
        _legacy_target(hit, collection, tenant_id, addresses, file_id=file_id, file_version=file_version)

    query = {"bool": {"filter": [
        legacy_document_filter(), {"terms": {"path_or_url": addresses}},
    ]}}
    return _remove_matching(client, collection, reader, identities, query, (
        INGEST_GENERATION, "path_or_url", "tenant_id", "file_id", "file_version",
        "metadata.tenant_id", "metadata.file_id", "metadata.file_version",
    ), validate, context=context, validate_all=file_id is None)


def _remove_matching(client, collection, reader, identities, query, fields, validate, *, context, validate_all=False):
    receipts = delete_index_documents(
        ElasticsearchVectorStore, client, collection, query, fields, validate, context=context, exact_index=True,
        validate_all=validate_all,
    )
    try:
        if _count(client, collection, query, context) != 0 or reader.identities() != identities:
            raise Conflict()
    except StorageError as error:
        if validate_all and receipts:
            raise OutcomeUnknown(operation_id=context.operation_id) from error
        raise
    return sum(receipt.deleted for receipt in receipts)


def _count(client, collection, query, context):
    remaining = ElasticsearchVectorStore._call(client, "count", context, index=collection, query=query,
                                               allow_no_indices=False, ignore_unavailable=False)
    _complete(remaining, context)
    count = remaining.get("count")
    if type(count) is not int or count < 0:
        raise Unavailable(operation_id=context.operation_id)
    return count
