# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorize exact collection setup/status using the actual editor's current DAC."""

from contracts.knowledge_collections import (
    KnowledgeCollectionAuthorization,
    KnowledgeCollectionGrant,
)
from management.services.knowledge_base.chunks_authorization import (
    chunks_resource_grant,
)
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from nexent.storage.errors import NotFound, ScopeDenied


def authorize_collection(request, actor, *, context, reader=None):
    if not isinstance(request, KnowledgeCollectionAuthorization):
        raise ScopeDenied()
    try:
        row = (reader or KnowledgeFileReader()).knowledge(None, actor, knowledge_id=request.knowledge_id,
                                                         edit=True, context=context)
    except ValueError as error:
        raise NotFound() from error
    resource = chunks_resource_grant(row)
    model = row['embedding_model_id']
    return KnowledgeCollectionGrant(knowledge_id=request.knowledge_id, collection=resource.collection,
        resource_tenant_id=resource.resource_tenant_id, revision=resource.revision,
        embedding_model_id=model if type(model) is int and model > 0 else None)
