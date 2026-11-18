# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Attest current KB edit rights for one signed normalized chunk operation."""

from contracts.knowledge_chunk_mutation import (
    ChunkMutationAuthorization,
    ChunkMutationGrant,
)
from management.services.knowledge_base.chunks_authorization import (
    chunks_resource_grant,
)
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from nexent.storage.errors import NotFound, ScopeDenied


def authorize_chunk_mutation(request, actor, *, context, reader=None):
    if not isinstance(request, ChunkMutationAuthorization):
        raise ScopeDenied()
    try:
        row = (reader or KnowledgeFileReader()).knowledge(
            None, actor, knowledge_id=request.knowledge_id, edit=True, context=context
        )
    except ValueError as error:
        raise NotFound() from error
    resource = chunks_resource_grant(row)
    model = row["embedding_model_id"]
    return ChunkMutationGrant(
        **request.model_dump(),
        collection=resource.collection,
        resource_tenant_id=resource.resource_tenant_id,
        revision=resource.revision,
        embedding_model_id=model if type(model) is int and model > 0 else None,
    )
