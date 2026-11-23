# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorize exact collection setup/status using the actual editor's current DAC."""

from contracts.constants import environment
from contracts.knowledge_collections import (
    KnowledgeCollectionAuthorization,
    KnowledgeCollectionGrant,
)
from management.services.knowledge_base.chunks_authorization import (
    chunks_resource_grant,
)
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from management.services.knowledge_base.legacy_vector_file_links import (
    require_unique_source_addresses,
)
from nexent.storage.errors import NotFound, ScopeDenied

from infrastructure.knowledge_deletion import knowledge_deletion_ports


def authorize_collection(request, actor, *, context, reader=None):
    if not isinstance(request, KnowledgeCollectionAuthorization):
        raise ScopeDenied()
    try:
        row = (reader or KnowledgeFileReader()).knowledge(None, actor, knowledge_id=request.knowledge_id,
                                                         edit=True, context=context)
    except ValueError as error:
        raise NotFound() from error
    resource = chunks_resource_grant(row)
    if request.untracked_source is not None:
        if not environment.KNOWLEDGE_RUNTIME_HYBRID_ENABLED or resource.resource_tenant_id != actor.tenant_id:
            raise ScopeDenied()
        with knowledge_deletion_ports(actor, context=context) as (_, resources):
            authority = KnowledgeFileAuthorization(resources, user_id=actor.user_id)
            current = authority.resolve_knowledge(request.knowledge_id, edit=True, context=context)
            if current['index_name'] != row['index_name']:
                raise ScopeDenied()
            require_unique_source_addresses(resources, request.knowledge_id, {request.untracked_source},
                                            context=context)
    model = row['embedding_model_id']
    return KnowledgeCollectionGrant(knowledge_id=request.knowledge_id, collection=resource.collection,
        untracked_source=request.untracked_source,
        resource_tenant_id=resource.resource_tenant_id, revision=resource.revision,
        embedding_model_id=model if type(model) is int and model > 0 else None)
