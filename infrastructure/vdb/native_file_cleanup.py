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
    if not generations:
        return 0
    resource = SimpleNamespace(knowledge_id=grant.knowledge_id, collection=grant.collection,
                               resource_tenant_id=actor.tenant_id)
    engine = record_engine(context)
    try:
        require_index_owner(actor, resource, engine=engine, context=context)
        with closing(_configured_client(context.remaining())) as client:
            return _delete(client, grant, actor.tenant_id, generations, context=context)
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
    receipts = delete_index_documents(
        ElasticsearchVectorStore, client, grant.collection, query,
        (INGEST_GENERATION, "id", "index", "tenant_id", "metadata.tenant_id"), validate,
        context=context, exact_index=True,
    )
    remaining = ElasticsearchVectorStore._call(client, "count", context, index=grant.collection, query=query,
                                               allow_no_indices=False, ignore_unavailable=False)
    _complete(remaining, context)
    count = remaining.get("count")
    if type(count) is not int or count < 0:
        raise Unavailable(operation_id=context.operation_id)
    if count != 0 or reader.identities() != identities:
        raise Conflict()
    return sum(receipt.deleted for receipt in receipts)
