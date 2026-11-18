# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Attest exact read-only namespaces with the actual reader's live knowledge DAC."""

from contracts.agentos_knowledge import (
    KnowledgeChunksAuthorization,
    KnowledgeChunksGrant,
)
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from nexent.storage.errors import ScopeDenied

from infrastructure.knowledge_search import knowledge_search_revision


def authorize_chunks_resource(request, actor, *, context, reader=None):
    if not isinstance(request, KnowledgeChunksAuthorization):
        raise ScopeDenied()
    row = (reader or KnowledgeFileReader()).knowledge(None, actor, knowledge_id=request.knowledge_id, context=context)
    return chunks_resource_grant(row)


def chunks_resource_grant(row):
    if row['deletion_request'] is not None or row['knowledge_sources'] != 'elasticsearch':
        raise ScopeDenied()
    return KnowledgeChunksGrant(knowledge_id=row['knowledge_id'], collection=row['index_name'],
                                resource_tenant_id=row['tenant_id'], revision=knowledge_search_revision(row))
